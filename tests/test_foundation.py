import json
import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box
from pydantic import ValidationError
from la_parking.contracts import ManualObservation, OccupancyObservation, CurbInventory, Forecast
from la_parking.temporal import parse_time, intervals
from la_parking.spatial import canonical_line, inventory, assign_meters, clean_geometry
from la_parking.connectors import verify_ids, parcel_on_demand, socrata
from la_parking.build import normalize_events

BASE=dict(source_id='test',source_record_id='1',source_version='v1',retrieved_at_utc='2026-10-24T12:00:00Z',field_provenance={'state':'observed'},confidence=.5)


def test_dst_ambiguity_not_guessed():
    t=parse_time(pd.Series(['2026-11-01 01:30:00','2026-03-08 02:30:00','2026-06-01 12:00:00']),'America/Los_Angeles')
    assert t.isna().tolist()==[True,True,False]
    assert t.iloc[2].hour==19


def test_utc_is_not_reinterpreted_as_local():
    assert parse_time(pd.Series(['2026-08-01 07:00:00']),'UTC').iloc[0].hour==7


def test_gaps_conflicts_and_unknown():
    t=pd.to_datetime(['2026-01-01T00:00Z','2026-01-01T02:00Z','2026-01-01T02:00Z','2026-01-01T03:00Z'])
    f=pd.DataFrame({'space_id':['a']*4,'observed_at_utc':t,'state':['OCCUPIED','OCCUPIED','VACANT','UNKNOWN']})
    iv=intervals(f,15)
    assert iv.seconds.max()==900
    assert iv.loc[iv.observed_at_utc==t[1],'state'].tolist()==['UNKNOWN']
    assert iv.known.sum()==1


def test_unknown_is_never_zero():
    with pytest.raises(ValidationError): OccupancyObservation(**BASE,observation_id='a',observed_at_utc='2026-10-24T11:00Z',state='UNKNOWN',available_spaces=0,evidence_type='sensor',stale=False)


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError): OccupancyObservation(**BASE,observation_id='a',observed_at_utc='2026-10-24T11:00',state='VACANT',evidence_type='sensor',stale=False)


def test_capacity_unknown_and_forecast_abstention():
    with pytest.raises(ValidationError): CurbInventory(**BASE,block_face_id='a',valid_from_utc='2026-10-24T00:00Z',capacity_method='unavailable',exclusions_complete=False,physical_capacity=10)
    with pytest.raises(ValidationError): Forecast(**BASE,forecast_id='a',block_face_id='b',issued_at_utc='2026-10-24T00:00Z',arrival_at_utc='2026-10-24T01:00Z',duration_minutes=60,model_version='x',support='unsupported',probability_suitable_space=.9)


def test_manual_counts_must_reconcile():
    with pytest.raises(ValidationError): ManualObservation(**BASE,observation_id='a',block_face_id='a',observer_pseudonym='p',survey_start_utc='2026-10-24T10:00Z',survey_end_utc='2026-10-24T10:05Z',occupied=3,vacant_legal=2,unsuitable=1,surveyed_capacity=7,complete_face=True,gps_accuracy_m=5,latitude=34,longitude=-118)


def test_source_ids_complete_not_just_row_counts():
    with pytest.raises(ValueError): verify_ids([1,2],[{'properties':{'OID':1}},{'properties':{'OID':1}}],'OID')
    with pytest.raises(ValueError): verify_ids([1,2],[{'properties':{'OID':1}},{'properties':{'OID':3}}],'OID')


def test_socrata_truncation_fails():
    class Fake:
        def json(self,url,params,**kw):
            return ([{'count':'3'}] if '$select' in params else [{'a':1}]),{}
    with pytest.raises(ValueError,match='pagination'): socrata(Fake(),'test',page_size=3)


def test_parcels_cannot_default_to_bulk():
    with pytest.raises(ValueError): parcel_on_demand(None,'x',None)
    with pytest.raises(ValueError): parcel_on_demand(None,'x',[-119,33,-117,35])


def test_orientation_and_city_clipping():
    a=LineString([(-118.5,34),(-118.4,34)])
    assert canonical_line(a).equals_exact(canonical_line(LineString(list(a.coords)[::-1])),0)
    streets=gpd.GeoDataFrame({'OBJECTID':[1],'ASSETID':[5],'Street_Designation':['Freeway']},geometry=[a],crs=4326)
    city=gpd.GeoDataFrame(geometry=[box(-118.48,33.9,-118.42,34.1)],crs=4326)
    result=inventory(streets,city)
    assert result.geometry.iloc[0].bounds[0]>=-118.48
    assert result.applicability.iloc[0]=='excluded'


def test_intersection_join_ambiguity_retained():
    segs=gpd.GeoDataFrame({'segment_id':['a','b']},geometry=[LineString([(-118.45,34.06),(-118.44,34.06)]),LineString([(-118.445,34.055),(-118.445,34.065)])],crs=4326)
    pts=gpd.GeoDataFrame({'spaceid':['x']},geometry=[Point(-118.445,34.06)],crs=4326)
    result=assign_meters(pts,segs)
    assert result.join_status.iloc[0]=='ambiguous'
    assert result.block_face_id.iloc[0] is None


def test_four_dimensional_arcgis_coordinates():
    obj={'features':[{'geometry':{'type':'LineString','coordinates':[[1,2,0,None],[3,4,0,None]]}}]}
    assert clean_geometry(obj)['features'][0]['geometry']['coordinates']==[[1,2],[3,4]]
    assert len(obj['features'][0]['geometry']['coordinates'][0])==4


def test_joined_planning_rows_do_not_duplicate_physical_streets():
    line=LineString([(-118.45,34.06),(-118.44,34.06)])
    f=gpd.GeoDataFrame({'OBJECTID':[1,1],'ASSETID':[5,5],'AutoID':[1,2],'Street_Designation':['Local Street','Local Street']},geometry=[line,line],crs=4326)
    city=gpd.GeoDataFrame(geometry=[box(-118.5,34,-118.4,34.1)],crs=4326)
    result=inventory(f,city)
    assert len(result)==1
    assert json.loads(result.source_api_row_ids.iloc[0])==['1','2']


def test_invalid_curb_is_not_silently_used():
    from shapely.geometry import Polygon
    from la_parking.spatial import faces
    seg=gpd.GeoDataFrame({'segment_id':['x'],'applicability':['needs_review']},geometry=[LineString([(-118.45,34.06),(-118.44,34.06)])],crs=4326)
    curb=gpd.GeoDataFrame({'OBJECTID':[1]},geometry=[Polygon([(-118.45,34.06),(-118.44,34.061),(-118.45,34.061),(-118.44,34.06),(-118.45,34.06)])],crs=4326)
    assert not curb.is_valid.all()
    out=faces(seg,curb)
    assert len(out)==2 and (out.geometry_method=='approximate_centerline_offset').all()


def test_invalid_future_and_duplicate_observations():
    f=pd.DataFrame({'SpaceID':['a','a','b','c'],'EventTime_UTC':['2026-01-01']*2+['bad','2027-01-01'],'OccupancyState':['VACANT']*4})
    good,bad,duplicates=normalize_events(f,'test','2026-10-24T12:00Z')
    assert len(good)==1 and len(bad)==2 and duplicates==1


def test_intervals_stop_at_export_boundary():
    t=pd.to_datetime(['2026-09-01T06:59:00Z'])
    f=pd.DataFrame({'space_id':['x'],'observed_at_utc':t,'state':['VACANT']})
    assert intervals(f,15,window_end='2026-09-01T07:00:00Z').seconds.iloc[0]==60


def test_raw_cache_verifies_hash_and_redacts_query_secret(tmp_path,monkeypatch):
    from la_parking.http import Store
    monkeypatch.setattr('la_parking.http.time.sleep',lambda _:None)
    class Response:
        status_code=200
        headers={'Content-Type':'application/json','Content-Length':'2'}
        url='https://example.org/data?key=test-secret'
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def raise_for_status(self): pass
        def iter_content(self,*_): yield b'[]'
    class Session:
        calls=0
        def get(self,*_,**kw): self.calls+=1; return Response()
    s=Store(tmp_path); s.session=Session()
    path,rec=s.get('https://example.org/data',secret_params={'key':'test-secret'})
    s.get('https://example.org/data',secret_params={'key':'test-secret'})
    assert s.session.calls==1
    assert 'test-secret' not in (tmp_path/'manifest.jsonl').read_text()
    path.write_bytes(b'corrupted')
    with pytest.raises(RuntimeError,match='corrupt'): s.get('https://example.org/data')
    assert s.session.calls==2


@pytest.mark.parametrize('headers,body', [({'Content-Type':'text/html'},b'<html>login</html>'),({'Content-Type':'application/json','Content-Length':'100000'},b'[]')])
def test_html_and_large_responses_never_become_snapshots(tmp_path,monkeypatch,headers,body):
    from la_parking.http import Store
    monkeypatch.setattr('la_parking.http.time.sleep',lambda _:None)
    class Response:
        status_code=200
        url='https://example.org/data'
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def raise_for_status(self): pass
        def iter_content(self,*_): yield body
    r=Response(); r.headers=headers
    class Session:
        def get(self,*_,**kw): return r
    s=Store(tmp_path,max_mb=.001); s.session=Session()
    with pytest.raises(RuntimeError): s.get(r.url)
    assert not list((tmp_path/'cache').iterdir())
    assert not list((tmp_path/'raw').iterdir())


def test_manual_intake_accepts_valid_survey_and_rejects_duplicate(tmp_path):
    from la_parking.observations import ingest
    inventory_path=tmp_path/'faces.parquet'
    gpd.GeoDataFrame({'block_face_id':['face1']},geometry=[LineString([(-118.45,34.06),(-118.44,34.06)])],crs=4326).to_parquet(inventory_path)
    record={**BASE,'observation_id':'fixture-only','block_face_id':'face1','observer_pseudonym':'test',
            'survey_start_utc':'2026-10-24T10:00Z','survey_end_utc':'2026-10-24T10:05Z','occupied':3,'vacant_legal':2,
            'unsuitable':1,'surveyed_capacity':6,'complete_face':True,'gps_accuracy_m':5,'latitude':34.06,'longitude':-118.445}
    p=tmp_path/'survey.jsonl'; p.write_text(json.dumps(record))
    assert ingest(p,inventory_path,tmp_path/'observations')['accepted']==1
    repeat=ingest(p,inventory_path,tmp_path/'observations')
    assert repeat['accepted']==0 and len(repeat['rejected'])==1
