"""Generate machine-readable source registry from measured metadata and reports."""
from datetime import datetime,timezone
from pathlib import Path
import json
import pandas as pd
from la_parking.sources import NAV,SODA,DATASETS,PILOT

now=datetime.now(timezone.utc).isoformat(); stage=Path('data/staged'); rows=[]
manifest=[json.loads(line) for line in Path('data/manifest.jsonl').read_text(encoding='utf8').splitlines()]
def retrieved(url):
 times=[r['retrieved_at_utc'] for r in manifest if r.get('success') and r.get('url')==url]
 return max(times) if times else None
statuses={}
for p in ['reports/acquisition_status.json','reports/supplement_status.json','reports/activity_status.json']:
 if Path(p).exists(): statuses.update(json.loads(Path(p).read_text()))
def add(id,owner,url,category,priority,**kw):
 row=dict(id=id,owner=owner,verified_url=url,endpoint_url=None,category=category,priority=priority,status='candidate/unverified',license_terms='Unverified; do not assume public-domain rights from public visibility',geographic_coverage='City of Los Angeles relevance; exact coverage unverified',temporal_coverage='unverified',actual_observation_dates=None,retrieved_at_utc=None,refresh_cadence='unverified',access_requirements='unverified',cost='unverified',pagination='unverified',useful_fields=[],notes='',evidence_type='context')
 row.update(kw); rows.append(row)

for name,ident in DATASETS.items():
 path=stage/f'{name}_metadata.json'
 if not path.exists(): continue
 m=json.loads(path.read_text()); updated=datetime.fromtimestamp(m['rowsUpdatedAt'],timezone.utc).isoformat() if m.get('rowsUpdatedAt') else None
 status=statuses.get(name,{}).get('status','verified/not downloaded')
 downloaded=(stage/f'{name}.parquet').exists() or (name=='history' and bool(list(stage.glob('history_20*.json'))))
 if name=='history': status='verified/downloaded' if downloaded else 'verified/not downloaded'
 if name in ['sweeping','permits','signs']: status='stale'
 notes={'sweeping':'2014 metadata; route boundaries/time strings do not establish current recurring weekday rules.', 'permits':'2015 polygons; district presence does not establish user eligibility, exemptions or current posted rules.', 'signs':'Calendar sign status/count polygons; not full sign text or arrows/effective rules.', 'business':'Registration accounts are not necessarily unique active physical destinations; missing NAICS/geocodes and absent opening hours.', 'occupancy':'Last-known metered sensor transaction states, not guaranteed present occupancy. Column eventtime documented UTC.', 'history':'Monthly attachment dates must be read from content; rowsUpdatedAt is misleading for attachments. Metadata lists 2023_09 through 2026_08.', 'meters':'Current supply/policy snapshot, not historical inventory. Rate ranges and time limits are not complete tariffs/rules.'}[name]
 obs=None
 if name=='history':
  obs={'downloaded_months':[p.stem.removeprefix('history_') for p in stage.glob('history_20*.json')], 'available_months':[a['filename'] for a in m.get('metadata',{}).get('attachments',[])]}
 elif name=='occupancy' and (stage/'occupancy.parquet').exists():
  f=pd.read_parquet(stage/'occupancy.parquet'); obs={'min_utc_text':f.eventtime.min(),'max_utc_text':f.eventtime.max()}
 add(name,m.get('attribution','LADOT / City of Los Angeles'),f'{SODA}/d/{ident}', 'A direct parking' if name in ['occupancy','history','meters'] else ('D activity' if name=='business' else 'B supply/rules'),1 if name in ['occupancy','history','meters'] else 2,
  endpoint_url=f'{SODA}/api/views/{ident}.json' if name=='history' else f'{SODA}/resource/{ident}.json',status=status,downloaded=downloaded,license_terms=m.get('license'),source_updated_at_utc=updated,actual_observation_dates=obs,retrieved_at_utc=statuses.get(name+'_metadata',{}).get('result',{}).get('retrieved_at_utc'),temporal_coverage='See source_updated_at_utc and actual_observation_dates; retrieval is not observation',geographic_coverage=list(PILOT) if name=='business' else 'Published City source extent; meter geometry checked against official city boundary in build',refresh_cadence='live/as available' if name=='occupancy' else ('monthly attachments' if name=='history' else 'provider-dependent; timestamps recorded'),access_requirements='Anonymous public; optional SOCRATA_APP_TOKEN for quotas',cost='No fee for these public requests',pagination='SODA count + ordered pages, 5000/page; mutable feed has no transaction isolation' if name!='history' else 'Attachment list -> exact monthly asset; 450 MB/file cap',useful_fields=[{'name':c.get('fieldName'),'type':c.get('dataTypeName'),'description':c.get('description')} for c in m.get('columns',[])],notes=notes,evidence_type='occupancy' if name in ['occupancy','history'] else 'context')

for name,ident in [('boundary',414),('streets',341),('curbs',324),('driveways',325),('hydrants',107),('regulatory_signs',177),('bikeways',157),('red_curb',431),('buildings',393),('zoning',75),('construction',1),('construction_streets',212)]:
 p=stage/f'{name}_metadata.json'
 if not p.exists(): continue
 m=json.loads(p.read_text()); s=statuses.get(name,{})
 add(name,'City of Los Angeles Bureau of Engineering / NavigateLA',f'{NAV}/{ident}', 'C built environment' if name in ['buildings','zoning'] else 'B supply/rules',1 if name in ['boundary','streets','curbs'] else 2,endpoint_url=f'{NAV}/{ident}/query',status='verified/downloaded' if (stage/f'{name}.geojson').exists() else s.get('status','verified/not downloaded'),downloaded=(stage/f'{name}.geojson').exists(),license_terms={'copyright':m.get('copyrightText'),'terms':'Layer copyright/attribution retained. No explicit reuse license verified; review applicable City/LARIAC terms before redistribution.'},geographic_coverage='Full published source then City boundary clipping' if name in ['streets','boundary'] else list(PILOT),temporal_coverage='Current snapshot; per-feature creation/modification dates do not prove current legal validity',actual_observation_dates={'layer_vintage':m.get('name'),'effective_dates':'unverified'},retrieved_at_utc=now,refresh_cadence='Unspecified; retain successive immutable snapshots',access_requirements='Anonymous ArcGIS REST query; no purchase',cost='No fee for requests tested',pagination=f"Return IDs then short range batches <=500; exact ID reconciliation. Server maxRecordCount={m.get('maxRecordCount')}",useful_fields=[{'name':f['name'],'type':f['type']} for f in m.get('fields',[])],notes={'curbs':'Physical curb footprints, not legal parking extent.', 'regulatory_signs':'Actual DESCRIPTIO/LegendDesc exists, but observed samples are traffic/speed signs; completeness for parking rules not established.', 'red_curb':'Operational area polygons and completion dates; unsuitable as red-painted curb length geometry.', 'construction':'Permit points alone do not prove active closure.', 'construction_streets':'Project date strings require parsing; not every construction project blocks curb parking.', 'buildings':'Layer named 2023 LARIAC7; individual features include older source dates; physical form is not housing-unit count.'}.get(name,'Preserve source IDs and attributes; verify spatial and temporal suitability.'))

supp=[('lodes','US Census Bureau','https://lehd.ces.census.gov/data/lodes/LODES8/ca/wac/ca_wac_S000_JT00_2023.csv.gz','C built environment',2,'US federal public data; apply Census attribution and disclosure notices','CA file filtered to LA County blocks; LODES8/2020 blocks','2023 workplace jobs; released file modified 2025-12-03','Annual release; do not mix LODES releases',['w_geocode','C000','industry/worker categories']),('lax_weather_2025','NOAA NCEI / NOAA public archive','https://noaa-global-hourly-pds.s3.amazonaws.com/2025/72295023174.csv','E changing conditions',2,'US government data; NOAA attribution','LAX station, not Westwood microclimate','2025 hourly','Annual/current-year updates',['DATE','TMP','WND','VIS','AA1 quality codes']),('lax_weather_2026','NOAA NCEI / NOAA public archive','https://noaa-global-hourly-pds.s3.amazonaws.com/2026/72295023174.csv','E changing conditions',2,'US government data; NOAA attribution','LAX station, not Westwood microclimate','2026 available portion','Annual/current-year updates',['DATE','TMP','WND','VIS','AA1 quality codes']),('weather_forecast','NOAA National Weather Service','https://api.weather.gov/points/34.0689,-118.4452','E changing conditions',2,'Free public data for any purpose; https://www.weather.gov/documentation/services-web-api','NWS forecast grid covering UCLA','Rolling hourly forecast; retain generatedAt and retrieval','Several updates/day',['generatedAt','startTime','endTime','temperature','windSpeed','probabilityOfPrecipitation']),('ucla_calendar','UCLA Registrar','https://registrar.ucla.edu/file/fa0541df-37fc-4e16-9041-f217b8317c22','D activity',2,'Public official calendar; no explicit redistribution license verified','UCLA; professional schools can differ','2026–27 term calendar','Annual and revisions',['UID','DTSTART','DTEND','SUMMARY']),('metro_rail_gtfs','LA Metro','https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip','E changing conditions',2,'Metro developer terms referenced by official feed README; review before distribution','Published Metro rail service; does not cover all local bus operators','feed_info/calendar validity inspected separately','Rail feed generally daily Tue–Sat per official README',['stop_id','stop_lat','stop_lon','calendar','trips','stop_times']),('metro_canceled_service','LA Metro','https://api.metro.net/canceled_service/all','E changing conditions',2,'Metro API terms not independently resolved','Metro bus cancellations; no guarantee all disruptions covered','Current response, not historical archive','Every 15 minutes per API home',['line','cancellation status'])]
for ident,owner,url,cat,priority,terms,geo,temporal,cadence,fields in supp:
 s=statuses.get(ident,{}); result=s.get('result',{})
 add(ident,owner,url,cat,priority,endpoint_url=url,status=s.get('status','verified/not downloaded'),license_terms=terms,geographic_coverage=geo,temporal_coverage=temporal,actual_observation_dates=result,retrieved_at_utc=now,refresh_cadence=cadence,access_requirements='Public anonymous endpoint attempted',cost='No fee for requests tested',pagination='Bounded single file/response; byte limit enforced',useful_fields=fields,notes=s.get('error','Source issue/observation dates retained; no occupancy labels implied.'))

add('acs','US Census Bureau','https://www.census.gov/programs-surveys/acs/data/data-via-api.html','C built environment',2,endpoint_url='https://api.census.gov/data/2024/acs/acs5',status='blocked',geographic_coverage='LA County tract query; City subset needs geographic join',temporal_coverage='2020–2024 five-year period estimates',access_requirements='Anonymous attempted, returned HTML. CENSUS_API_KEY connector implemented; key may be needed. Exact failure cause not established.',cost='Free public API/key',license_terms='US federal public data',pagination='Small selected-variable query, one county; include estimate margins of error before inference',useful_fields=['B01003 population','B08201 household vehicle availability','B08301 commuting','B11001 households','B25001 housing units'],notes='ACS API documentation verified. HTML response is not accepted as data. No ACS values fabricated.')

candidates=[
 ('parcels','City BOE',f'{NAV}/399','C built environment',2,'verified/not downloaded','Verified layer/schema/sample; connector requires small bounding box and caches it. No bulk default. APN/assessment attributes may need a separate County Assessor source.'),
 ('surveys','LADOT / WVIA','https://planning.lacity.gov/odocument/7f3c2281-70da-42e6-b265-a931f0b0a7d5/CPC_Staff_Report.pdf','A direct parking',1,'stale','Official report cites September 2013 Westwood parking study; raw block-face/time observations and license not verified. Aggregate includes visitor parking; not usable contemporary unmetered labels.'),
 ('unmetered_partnerships','LADOT / UCLA Transportation / WVIA','https://ladot.lacity.gov/projects/parking-la','A direct parking',1,'candidate/unverified','No verified public unmetered occupancy endpoint found. Request raw anonymized surveys with sampling protocol and rights; no outreach sent.'),
 ('parking_sign_rules','LADOT / BOE',f'{NAV}/177','B supply/rules',1,'candidate/unverified','Traffic sign descriptions exist, but a complete authoritative parking sign text/direction/effective-rule feed is unverified. Calendar-sign locations are insufficient.'),
 ('loading_zones','LADOT', 'https://ladot.lacity.gov/projects/parking-la','B supply/rules',1,'candidate/unverified','Need curb extents, hours, vehicle classes and effective dates; no machine-readable source verified.'),
 ('bus_stops','LA Metro','https://api.metro.net/docs','B supply/rules',1,'verified/not downloaded','OpenAPI verified; route/stops paths documented. Rail stops downloaded separately; bus stop clearance extents and other operators still needed.'),
 ('permit_eligibility','LADOT','https://ladot.lacity.gov/projects/parking-la','B supply/rules',1,'candidate/unverified','Old district polygons do not establish eligibility, permit classes, hours or exemptions.'),
 ('intersection_exclusions','City BOE',f'{NAV}/341','B supply/rules',1,'verified/not downloaded','Centerline endpoints available; verified curb setbacks/crosswalk extents and applicable current rules still needed. No automatic legal buffer applied.'),
 ('temporary_event_rules','LADOT / City BOE',f'{NAV}/1','B supply/rules',1,'candidate/unverified','Permit geometry/status is context; no complete real-time curb closure feed established.'),
 ('offstreet','LADOT / private operators','https://ladot.lacity.gov/projects/parking-la','C built environment',3,'candidate/unverified','Public facilities and development studies may identify supply; no complete private-space inventory or occupancy label source verified.'),
 ('housing_units','Census / County Assessor','https://www.census.gov/programs-surveys/acs/data/data-via-api.html','C built environment',2,'blocked','ACS connector blocked; building footprints alone are not unit counts. Assess parcel attributes on demand.'),
 ('schools_campuses_hospitals_offices','City BOE / institutions',f'{NAV}','D activity',3,'candidate/unverified','Separate POI inventories and campus boundaries need verification; business registry contains activity categories but omits many institutions and true hours.'),
 ('opening_hours','Businesses / licensed providers','https://data.lacity.org/d/6rrh-rzua','D activity',3,'unsuitable','Verified City business registry has no opening-hour field. Commercial/map provider storage terms and pricing must be evaluated before use.'),
 ('sports_events','UCLA Athletics / venue operators','https://uclabruins.com/','D activity',2,'candidate/unverified','Official schedule page is a discovery source, not a verified API. Need stable identifiers, revisions, venue capacities and timezones.'),
 ('venue_capacity_attractions','Venue operators','https://uclabruins.com/','D activity',3,'candidate/unverified','Capacity is not actual attendance; verify each venue, scheduled events and reuse terms.'),
 ('holidays','US Office of Personnel Management','https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/','D activity',3,'candidate/unverified','Federal holidays alone do not establish LA parking exemptions or local school closures. Verify local calendars separately.'),
 ('traffic','City / Caltrans PeMS','https://pems.dot.ca.gov/','E changing conditions',3,'candidate/unverified','Account/terms likely relevant; street-level congestion coverage and API access unverified. No credential endpoint invented.'),
 ('citations','LADOT','https://data.lacity.org/d/wjz9-h9np','F weak proxy',3,'stale','Official catalog identifies archived citations. Enforcement deployment, patrol schedules, policy and geocoding bias dominate exposure; never occupancy labels.'),
 ('service_requests','City MyLA311','https://data.lacity.org/','F weak proxy',3,'candidate/unverified','No current specific endpoint selected. Reporting and neighborhood participation bias; requests are not observed supply/occupancy.')]
for ident,owner,url,cat,priority,status,notes in candidates:
 add(ident,owner,url,cat,priority,status=status,notes=notes,endpoint_url=f'{NAV}/399/query' if ident=='parcels' else None,access_requirements='Public discovery only; exact connector requirements unverified' if status=='candidate/unverified' else 'See notes',cost='No purchase made; future terms/cost unresolved')

Path('config').mkdir(exist_ok=True)
for row in rows:
 observed_retrieval=retrieved(row.get('endpoint_url')) or retrieved(row['verified_url'])
 if observed_retrieval: row['retrieved_at_utc']=observed_retrieval
 elif row['status'] in ['candidate/unverified','unsuitable','verified/not downloaded']: row['retrieved_at_utc']=None
 if row['id']=='lax_weather_2025' and row['status']=='verified/downloaded':
  row['status']='stale'; row['notes']='Actual file ends 2025-08-27; no overlap with acquired September 2025/August 2026 occupancy. Do not impute missing weather as zero.'
supplement=Path('config/source_registry_supplement.json')
if supplement.exists():
 extra=json.loads(supplement.read_text(encoding='utf8'));indexed={r['id']:r for r in rows}
 for r in extra:indexed[r['id']]=r
 rows=list(indexed.values())
 for r in rows:
  if r['id'] in ['curbs','driveways']:
   r.update(source_imagery_year=2014,inventory_created_year=2017,temporal_coverage='Historic 2017 asset inventory based on 2014 imagery; current maintenance not verified')
   r['notes']+=' Historic supply prior; never parking stalls or verified current legal capacity.'
Path('config/source_registry.json').write_text(json.dumps({'schema_version':'1.0','generated_at_utc':now,'sources':rows},indent=2),encoding='utf8')
table=['# Source registry\n','Machine-readable details: `config/source_registry.json`. `candidate/unverified` means a discovery lead, never an invented usable API. Downloaded sources retain raw request evidence in `data/manifest.jsonl`.\n','| Source | Status | Priority | Coverage / limitation |','|---|---|---:|---|']
for r in rows: table.append(f"| [{r['id']}]({r['verified_url']}) | {r['status']} | {r['priority']} | {r['notes']} |")
Path('docs/source_registry.md').write_text('\n'.join(table)+'\n',encoding='utf8')
print(len(rows),'sources registered')
