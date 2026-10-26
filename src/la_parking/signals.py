"""Prospective predictors with received-time gates, never occupancy labels."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from shapely.geometry import Point, shape
from .connectors import arcgis
from .http import Store


def timestamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone-aware timestamps required')
    return result.astimezone(timezone.utc)


def normalize_weather(obj, received_at):
    p = obj['properties']
    issued = p.get('updateTime') or p.get('generatedAt')
    if not issued:
        raise ValueError('Forecast issue time missing')
    timestamp(issued)
    periods = []
    for row in p['periods']:
        start, end = timestamp(row['startTime']), timestamp(row['endTime'])
        if end <= start:
            raise ValueError('Invalid forecast interval')
        temp, unit = row.get('temperature'), row.get('temperatureUnit')
        celsius = (temp-32)*5/9 if temp is not None and unit == 'F' else temp if unit == 'C' else None
        periods.append({'start_utc': start.isoformat(), 'end_utc': end.isoformat(),
                        'temperature_c': celsius,
                        'precipitation_probability_percent': (row.get('probabilityOfPrecipitation') or {}).get('value')})
    return {'source': 'nws_hourly', 'received_at_utc': received_at,
            'issued_at_utc': issued, 'coverage_geometry': obj.get('geometry'),
            'periods': periods, 'occupancy_labels': 0}


def normalize_events(rows, received_at, start, end):
    events, seen = [], set()
    for row in rows:
        ident = row.get('id')
        if not ident or ident in seen:
            raise ValueError('Missing or duplicate event ID')
        seen.add(ident)
        dates = row.get('dates', {})
        time = dates.get('start', {}).get('dateTime')
        venues = row.get('_embedded', {}).get('venues', [])
        location = venues[0].get('location', {}) if len(venues) == 1 else {}
        lat, lon = location.get('latitude'), location.get('longitude')
        if time:
            time = timestamp(time).isoformat()
        if lat is not None and lon is not None:
            lat, lon = float(lat), float(lon)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError('Invalid venue coordinates')
        else:
            lat, lon = None, None
        events.append({'event_id': ident, 'name': row.get('name'),
                       'start_utc': time, 'latitude': lat, 'longitude': lon,
                       'status': dates.get('status', {}).get('code'),
                       'attendance': None, 'end_utc': None})
    return {'source': 'ticketmaster', 'received_at_utc': received_at,
            'query_start_utc': start, 'query_end_utc': end,
            'query_city': 'Los Angeles', 'events': events,
            'coverage_note': 'Ticketmaster listings, not all events or attendance.',
            'occupancy_labels': 0}


def acquire_signals(config_path='config/signal_sources.json', refresh=False):
    from .environment import load_local_env
    credentials=load_local_env(keys=('TICKETMASTER_API_KEY','CURBIQ_TOKEN'))
    cfg = json.loads(Path(config_path).read_text())
    root = Path(cfg['output_root']); root.mkdir(parents=True, exist_ok=True)
    store = Store(root=str(root/'requests'), refresh=refresh, max_mb=10)
    report = {'sources': {}, 'occupancy_labels_added': 0,
              'historical_benchmarks_rerun': False, 'models_activated': False,'credential_status':credentials}

    def save(source, fn):
        try:
            result = fn()
            body = json.dumps(result, indent=2, allow_nan=False).encode()
            digest = hashlib.sha256(body).hexdigest()
            path = root/'snapshots'/source/(digest+'.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists(): path.write_bytes(body)
            (root/f'{source}_latest.json').write_bytes(body)
            report['sources'][source] = {'status': 'downloaded', 'snapshot': str(path),
                'sha256': digest, 'received_at_utc': result['received_at_utc'],
                'rows': len(result.get('periods', result.get('events', result.get('features', []))))}
        except Exception as exc:
            # Provider messages may contain URLs with keys; never print them.
            report['sources'][source] = {'status': 'unavailable', 'error_type': type(exc).__name__}

    def weather():
        lat, lon = cfg['weather_point']
        point, _ = store.json(f'https://api.weather.gov/points/{lat},{lon}')
        url = point['properties']['forecastHourly']
        if not url.startswith('https://api.weather.gov/'):
            raise ValueError('Unexpected forecast host')
        obj, rec = store.json(url)
        return normalize_weather(obj, rec.get('received_at_utc') or datetime.now(timezone.utc).isoformat())

    def sensors():
        obj, meta, oid = arcgis(store, cfg['sensor_layer'], bbox=cfg['pilot_bbox'], max_features=1500, batch=100,
            out_fields='OBJECTID,SENSOR_UNIQUE_ID,GPSX,GPSY,MTYPE,ADDRESS_SPACE')
        if any('SENSOR_STATUS' in f['properties'] for f in obj['features']):raise ValueError('Reserved occupancy status values must not be acquired')
        # Cached responses retain their original receipt time.
        receipts = []
        for cache in (store.root/'cache').glob('*.json'):
            r = json.loads(cache.read_text())
            if r.get('success') and r['url'].startswith(cfg['sensor_layer']):
                receipts.append(r.get('received_at_utc') or datetime.now(timezone.utc).isoformat())
        return {'source': 'ladot_sensor_assets', 'features': obj['features'],
                'received_at_utc': max(receipts), 'object_id_field': oid,
                'source_name': meta.get('name'), 'bbox': cfg['pilot_bbox'],
                'status_values_requested':False,
                'occupancy_labels': 0,
                'note': 'Asset inventory only; status codes are not verified health or historical status.'}

    def events():
        now = datetime.now(timezone.utc).replace(microsecond=0)
        end = now + timedelta(days=cfg['ticketmaster_days'])
        fmt = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
        base = 'https://app.ticketmaster.com/discovery/v2/events.json'
        params = {'city': 'Los Angeles', 'stateCode': 'CA', 'countryCode': 'US',
                  'startDateTime': fmt(now), 'endDateTime': fmt(end),
                  'size': 200, 'page': 0, 'sort': 'date,asc'}
        rows, expected, last_receipt = [], None, None
        while True:
            obj, rec = store.json(base, params, secret_params={'apikey': os.environ['TICKETMASTER_API_KEY']})
            total = int(obj['page']['totalElements'])
            if total > cfg['ticketmaster_max_events'] or total >= 1000:
                raise ValueError('Event budget/deep-page limit; narrow time window')
            if expected is None: expected = total
            elif total != expected: raise ValueError('Event catalog changed during pagination')
            rows.extend(obj.get('_embedded', {}).get('events', []))
            last_receipt = rec.get('received_at_utc') or datetime.now(timezone.utc).isoformat()
            if params['page']+1 >= int(obj['page']['totalPages']): break
            params = {**params, 'page': params['page']+1}
        if len(rows) != expected: raise ValueError('Incomplete event export')
        return normalize_events(rows, last_receipt, fmt(now), fmt(end))

    def curbs():
        west, south, east, north = cfg['pilot_bbox']
        obj, rec = store.json('https://v2.curbiq-curb-api.io/curbs/zones',
            {'min_lat': south, 'min_lng': west, 'max_lat': north,
             'max_lng': east, 'include_geometry': 'true', 'response_size': 100},
            secret_params={'curbiq_token': os.environ['CURBIQ_TOKEN']})
        # Deliberately bounded first-page probe, not a complete curb inventory.
        return {'source': 'curbiq_zones', 'received_at_utc': rec.get('received_at_utc') or datetime.now(timezone.utc).isoformat(),
                'response': obj, 'scope': 'first_page_only_max_100_records',
                'normalization_status': 'requires_schema_and_coverage_review',
                'occupancy_labels': 0, 'automatic_legal_rule_updates': False}

    save('nws_hourly', weather)
    save('ladot_sensor_assets', sensors)
    if os.getenv('TICKETMASTER_API_KEY'): save('ticketmaster', events)
    else: report['sources']['ticketmaster'] = {'status': 'missing_credentials', 'required_variable': 'TICKETMASTER_API_KEY'}
    if os.getenv('CURBIQ_TOKEN'): save('curbiq_zones', curbs)
    else: report['sources']['curbiq_zones'] = {'status': 'access_request_required', 'required_variable': 'CURBIQ_TOKEN'}
    (root/'acquisition_status.json').write_text(json.dumps(report, indent=2))
    return report


def distance_m(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    dlat, dlon = b-a, math.radians(lon2-lon1)
    h = math.sin(dlat/2)**2 + math.cos(a)*math.cos(b)*math.sin(dlon/2)**2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(h)))


def features_asof(requests, snapshots, config):
    """Requests are IDs, times and verified coordinates, never parking outcomes."""
    output, seen = [], set()
    for request in requests:
        ident = request['request_id']
        if ident in seen: raise ValueError('Duplicate request ID')
        seen.add(ident)
        issued, arrival = timestamp(request['issued_at_utc']), timestamp(request['arrival_time_utc'])
        if arrival < issued: raise ValueError('Arrival precedes issue time')
        lat, lon = float(request['latitude']), float(request['longitude'])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError('Invalid location')
        result = {k: request[k] for k in ['request_id','issued_at_utc','arrival_time_utc','latitude','longitude']}
        result.update(weather_temperature_c=None, weather_precipitation_probability_percent=None,
                      listed_events_starting_near_arrival=None,
                      weather_status='unavailable_at_issue_or_outside_coverage',
                      events_status='unavailable_at_issue_or_outside_coverage', feature_available_at_utc=None)
        candidates = [s for s in snapshots if timestamp(s['received_at_utc']) <= issued
                      and issued-timestamp(s['received_at_utc']) <= timedelta(hours=config['maximum_snapshot_age_hours'])]
        receipts = []
        weather = sorted([s for s in candidates if s['source']=='nws_hourly'
                          and timestamp(s['issued_at_utc']) <= issued],
                         key=lambda s: timestamp(s['received_at_utc']), reverse=True)
        for snapshot in weather:
            geo = snapshot.get('coverage_geometry')
            if not geo or not shape(geo).covers(Point(lon,lat)): continue
            rows = [p for p in snapshot['periods'] if timestamp(p['start_utc']) <= arrival < timestamp(p['end_utc'])]
            if not rows: continue
            if len(rows)!=1: raise ValueError('Overlapping forecast periods')
            p = rows[0]
            result.update(weather_temperature_c=p['temperature_c'],
                          weather_precipitation_probability_percent=p['precipitation_probability_percent'],
                          weather_status='forecast_known_at_issue')
            receipts.append(snapshot['received_at_utc']); break
        window = timedelta(minutes=config['event_feature_window_minutes'])
        events = sorted([s for s in candidates if s['source']=='ticketmaster'
                         and timestamp(s['query_start_utc']) <= arrival-window
                         and arrival+window < timestamp(s['query_end_utc'])],
                        key=lambda s: timestamp(s['received_at_utc']), reverse=True)
        if events:
            nearby = [e for e in events[0]['events'] if e['start_utc']
                      and e['latitude'] is not None and e['longitude'] is not None
                      and e['status'] in ['onsale','offsale']
                      and abs(timestamp(e['start_utc'])-arrival) <= window
                      and distance_m(lat,lon,e['latitude'],e['longitude']) <= config['event_feature_radius_m']]
            result.update(listed_events_starting_near_arrival=len(nearby),
                          events_status='ticketmaster_listings_only_not_attendance')
            receipts.append(events[0]['received_at_utc'])
        if receipts: result['feature_available_at_utc'] = max(receipts,key=timestamp)
        output.append(result)
    return output


def build_signal_features(requests_path, output_path, config_path='config/signal_sources.json'):
    cfg = json.loads(Path(config_path).read_text())
    requests = [json.loads(line) for line in Path(requests_path).read_text().splitlines() if line.strip()]
    snapshots = [json.loads(p.read_text()) for p in (Path(cfg['output_root'])/'snapshots').glob('*/*.json')]
    result = features_asof(requests,snapshots,cfg)
    path = Path(output_path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in result))
    return {'requests':len(result),'output':str(path),'occupancy_labels':0}
