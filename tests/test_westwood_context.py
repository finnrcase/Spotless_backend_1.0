"""Source-semantic fixtures are not occupancy observations."""
import json
import pytest
from la_parking.westwood_context import Page,ics_event,listing_event,normalize_sweeping,normalize_reservation
from la_parking.http import Store


def test_actual_ucla_ics_shape_preserves_utc_and_missing_geo():
    text='BEGIN:VEVENT\r\nUID:fixture@ucla\r\nDTSTART:20261026T203000Z\r\nDTEND:20261026T223000Z\r\nSUMMARY:Long\r\n\t title\r\nLOCATION:Murphy Hall\r\nEND:VEVENT'
    row=ics_event(text);assert row['start_utc']=='2026-10-26T20:30:00+00:00' and row['title']=='Long title'
    assert row['latitude'] is None and row['longitude'] is None
    import html
    body=html.escape(json.dumps({'content':text}),quote=True)
    assert Page('<a onclick="downloadIcsFile('+body+')">ICS</a>').ics==[text]


def test_local_listing_date_without_timezone_is_not_invented_utc():
    row={'id':1,'title':'Fixture','tags':[{'slug':'events_feed_predicted'}],
        'meta':{'vibemap_event_latitude':'34.06','vibemap_event_longitude':'-118.44','vibemap_event_start_date':'2026-11-02T12:00:00'}}
    result=listing_event(row,[-118.47,34.04,-118.42,34.08])
    assert result['inside_pilot_bbox'] and result['start_utc'] is None and result['listing_quality']=='provider_predicted_recurring'
    row['meta']['vibemap_event_start_date']='2026-11-02T12:00:00-08:00'
    assert listing_event(row,[-118.47,34.04,-118.42,34.08])['start_utc']=='2026-11-02T20:00:00+00:00'


def test_sweeping_route_polygon_does_not_authorize_face_parking():
    result=normalize_sweeping({'properties':{'OBJECTID':1,'Posted_Time':'10 am - 12 pm','Posted_Day':'Monday','Weeks':'1 & 3'},'geometry':{'type':'Polygon','coordinates':[]}})
    assert result['local_start']=='10:00' and result['local_end']=='12:00'
    assert not result['automatic_eligibility'] and result['effective_from_utc'] is None and result['physical_capacity'] is None


def test_reservation_normalization_omits_contacts_and_never_invents_closure():
    row=normalize_reservation({'properties':{'AutoID':1,'PWRS_ID':'fixture','StartDate':1782604800000,'ContactPhone':'private-fixture','REPORT_URL':'token-bearing-fixture'},'geometry':None},'AutoID')
    assert not row['verified_closure'] and row['eligible_capacity_effect'] is None and row['time_precision'].startswith('date_only')
    assert 'private-fixture' not in json.dumps(row) and 'token-bearing-fixture' not in json.dumps(row)


def test_html_must_be_explicit_and_cached_html_is_not_api_data(tmp_path,monkeypatch):
    store=Store(tmp_path);monkeypatch.setattr('la_parking.http.time.sleep',lambda x:None)
    class Response:
        status_code=200;url='https://fixture.invalid/page';headers={'Content-Type':'text/html','Content-Length':'4'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,*a):yield b'test'
    monkeypatch.setattr(store.session,'get',lambda *a,**k:Response())
    with pytest.raises(RuntimeError,match='HTML'):store.get(Response.url)
    store.get(Response.url,allow_html=True)
    with pytest.raises(ValueError,match='Cached HTML'):store.json(Response.url)


def test_context_receipt_and_freshness_gates_do_not_backfill_or_authorize(tmp_path):
    from la_parking.westwood_context import features_asof
    p=tmp_path/'fixture.json';p.write_text(json.dumps([{'geometry':{'type':'Polygon','coordinates':[[[-118.46,34.05],[-118.43,34.05],[-118.43,34.08],[-118.46,34.08],[-118.46,34.05]]]}}]))
    coverage={'bbox':[-118.47,34.04,-118.42,34.09],'sources':{'sweeping':{'status':'acquired','received_at_utc':'2026-10-26T12:00Z','normalized_path':str(p)}}}
    def request(issue):return {'request_id':'fixture','issued_at_utc':issue,'arrival_time_utc':issue,'latitude':34.06,'longitude':-118.44}
    assert features_asof([request('2026-08-25T12:00Z')],coverage)[0]['sweeping_route_candidate_count'] is None
    fresh=features_asof([request('2026-10-26T13:00Z')],coverage)[0]
    assert fresh['sweeping_route_candidate_count']==1 and fresh['legal_eligibility']=='unknown'
    assert features_asof([request('2026-10-30T13:00Z')],coverage)[0]['sweeping_route_candidate_count'] is None
