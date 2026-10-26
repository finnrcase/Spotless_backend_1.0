import copy
import json
import pytest
from shapely.geometry import box, mapping
from la_parking.signals import features_asof, normalize_events, normalize_weather, timestamp

CFG = {'maximum_snapshot_age_hours': 24, 'event_feature_radius_m': 1000,
       'event_feature_window_minutes': 120}
REQ = {'request_id': 'a', 'issued_at_utc': '2026-10-20T12:00:00Z',
       'arrival_time_utc': '2026-10-20T13:00:00Z', 'latitude': 34.063, 'longitude': -118.445}


def weather():
    return normalize_weather({'geometry': mapping(box(-118.46,34.05,-118.43,34.08)),
        'properties': {'updateTime': '2026-10-20T10:00:00Z', 'periods': [
        {'startTime': '2026-10-20T13:00:00Z', 'endTime': '2026-10-20T14:00:00Z',
         'temperature': 68, 'temperatureUnit': 'F', 'probabilityOfPrecipitation': {'value': None}}]}},
        '2026-10-20T11:00:00Z')


def events():
    return normalize_events([{'id': 'e', 'dates': {'start': {'dateTime': '2026-10-20T13:30:00Z'},
        'status': {'code': 'onsale'}}, '_embedded': {'venues': [
        {'location': {'latitude': '34.063', 'longitude': '-118.445'}}]}}],
        '2026-10-20T11:00:00Z', '2026-10-20T00:00:00Z', '2026-10-22T00:00:00Z')


def test_known_weather_uses_requested_hour_and_missing_precip_is_not_zero():
    result = features_asof([REQ],[weather()],CFG)[0]
    assert result['weather_temperature_c'] == 20
    assert result['weather_precipitation_probability_percent'] is None
    assert result['feature_available_at_utc'] == '2026-10-20T11:00:00Z'


@pytest.mark.parametrize('field',['received_at_utc','issued_at_utc'])
def test_future_snapshot_or_forecast_issue_cannot_enter_features(field):
    w = weather(); w[field] = '2026-10-20T12:01:00Z'
    result = features_asof([REQ],[w],CFG)[0]
    assert result['weather_temperature_c'] is None


def test_old_forecast_outside_geometry_and_expired_period_abstain():
    for changes in [{'received_at_utc':'2026-10-18T00:00:00Z'},
                    {'coverage_geometry':mapping(box(0,0,1,1))}, {'periods':[]}]:
        w = {**weather(), **changes}
        assert features_asof([REQ],[w],CFG)[0]['weather_temperature_c'] is None


def test_latest_snapshot_without_coverage_does_not_hide_valid_older_one():
    new = {**weather(),'received_at_utc':'2026-10-20T11:30:00Z','periods':[]}
    assert features_asof([REQ],[weather(),new],CFG)[0]['weather_temperature_c'] == 20


def test_events_are_predictors_and_cancellation_or_distance_changes_count():
    e = events()
    assert features_asof([REQ],[e],CFG)[0]['listed_events_starting_near_arrival'] == 1
    assert e['events'][0]['attendance'] is None and e['occupancy_labels'] == 0
    for changes in [{'status':'cancelled'},{'status':'postponed'},{'latitude':35.0},
                    {'start_utc':None},{'latitude':None}]:
        altered = copy.deepcopy(e); altered['events'][0].update(changes)
        assert features_asof([REQ],[altered],CFG)[0]['listed_events_starting_near_arrival'] == 0


def test_unavailable_events_are_null_and_partial_time_coverage_is_not_zero():
    e = events(); e['query_start_utc'] = '2026-10-20T12:30:00Z'
    for snapshots in [[],[e]]:
        assert features_asof([REQ],snapshots,CFG)[0]['listed_events_starting_near_arrival'] is None


def test_duplicate_ids_invalid_locations_and_naive_timestamps_rejected():
    with pytest.raises(ValueError): features_asof([REQ,REQ],[],CFG)
    with pytest.raises(ValueError): features_asof([{**REQ,'latitude':91}],[],CFG)
    with pytest.raises(ValueError): timestamp('2026-10-20T12:00:00')
    with pytest.raises(ValueError): features_asof([{**REQ,'arrival_time_utc':'2026-10-20T11:00:00Z'}],[],CFG)
    with pytest.raises(ValueError): normalize_events([{'id':'e'},{'id':'e'}],REQ['issued_at_utc'],REQ['issued_at_utc'],REQ['arrival_time_utc'])


def test_extra_request_outcomes_cannot_be_copied_into_feature_table():
    request = {**REQ,'occupied':12,'target_occupancy_rate':1.0}
    result = features_asof([request],[weather()],CFG)[0]
    assert 'occupied' not in result and 'target_occupancy_rate' not in result


def test_overlapping_forecast_intervals_fail_instead_of_selecting_arbitrarily():
    w = weather(); w['periods'] *= 2
    with pytest.raises(ValueError,match='Overlapping'): features_asof([REQ],[w],CFG)


def test_missing_source_issue_time_rejected():
    with pytest.raises(ValueError,match='issue time'): normalize_weather({'properties':{'periods':[]}},REQ['issued_at_utc'])


def test_acquisition_handles_missing_keys_and_refuses_oversize_event_export(tmp_path,monkeypatch):
    import la_parking.signals as module
    class FakeStore:
        def __init__(self,root,**kw):
            self.root = tmp_path/'requests'; (self.root/'cache').mkdir(parents=True,exist_ok=True)
        def json(self,url,params=None,**kw):
            if '/points/' in url: return {'properties':{'forecastHourly':'https://api.weather.gov/test'}},{}
            if 'api.weather.gov' in url:
                w = weather()
                return {'geometry':w['coverage_geometry'],'properties':{'updateTime':w['issued_at_utc'],'periods':[]}}, {'received_at_utc':w['received_at_utc']}
            return {'page':{'totalElements':1001,'totalPages':6}},{}
    def assets(store,*args,**kwargs):
        record = {'success':True,'url':'https://maps.lacity.org/lahub/rest/services/LADOT/MapServer/16/query','received_at_utc':'2026-10-20T11:00:00Z'}
        (store.root/'cache'/'asset.json').write_text(json.dumps(record))
        return {'features':[]},{'name':'sensor assets'},'OBJECTID'
    monkeypatch.setattr(module,'Store',FakeStore)
    monkeypatch.setattr('la_parking.environment.load_local_env',lambda **kw:{k:{'loaded':bool(__import__('os').environ.get(k)),'source':'test_fixture'} for k in kw['keys']})
    monkeypatch.setattr(module,'arcgis',assets)
    monkeypatch.delenv('TICKETMASTER_API_KEY',raising=False)
    monkeypatch.delenv('CURBIQ_TOKEN',raising=False)
    config = {'output_root':str(tmp_path/'signals'),'weather_point':[34.063,-118.445],
              'pilot_bbox':[-118.47,34.04,-118.42,34.08],
              'sensor_layer':'https://maps.lacity.org/lahub/rest/services/LADOT/MapServer/16',
              'ticketmaster_days':14,'ticketmaster_max_events':900}
    path = tmp_path/'config.json'; path.write_text(json.dumps(config))
    result = module.acquire_signals(str(path))
    assert result['sources']['ticketmaster']['status']=='missing_credentials'
    assert result['sources']['nws_hourly']['status']=='downloaded'
    assert result['sources']['ladot_sensor_assets']['status']=='downloaded'
    assert result['sources']['curbiq_zones']['status']=='access_request_required'
    monkeypatch.setenv('TICKETMASTER_API_KEY','test-only-not-real')
    result = module.acquire_signals(str(path))
    assert result['sources']['ticketmaster']['status']=='unavailable'
    assert 'test-only-not-real' not in json.dumps(result)
    assert not list((tmp_path/'signals'/'snapshots'/'ticketmaster').glob('*.json'))
