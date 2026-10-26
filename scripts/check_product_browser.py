"""Isolated phone-sized Chrome checks; no real observation/trial stores modified."""
import html,json,os,re,subprocess,tempfile,uuid
from pathlib import Path
from la_parking.contracts import ManualObservation
from la_parking.product_contracts import PilotTrial
from la_parking.observations import ingest

root=Path.cwd();qa=root/'.browser-qa/product';qa.mkdir(parents=True,exist_ok=True)
chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
if not chrome.exists():raise SystemExit('Chrome unavailable; browser checks not run')
face=json.loads((root/'reports/field_route.json').read_text())['faces'][0]['block_face_id']
harness='''<!doctype html><meta charset="utf-8"><iframe id="collector" style="width:390px;height:844px" src="__COLLECTOR__"></iframe><iframe id="pilot" style="width:390px;height:844px" src="__PILOT__"></iframe><pre id="result">RUNNING</pre><script>
onload=async()=>{const checks=[],ok=(v,n)=>{if(!v)throw Error(n);checks.push(n)};try{
const w=document.getElementById('collector').contentWindow,d=w.document,get=id=>d.getElementById(id);
get('observer').value='synthetic-browser-only';get('survey-session').value='synthetic-repeat-session';get('side-confirmed').checked=true;get('use-pin').click();get('repeat-offset').value='0';get('parking-type').value='unmetered';get('capacity-basis').value='estimated_positions';get('start').click();
for(const [id,value] of Object.entries({occupied:'3',vacant_legal:'1',unsuitable:'0',surveyed_capacity:'4'}))get(id).value=value;get('save').click();
let records=JSON.parse(w.localStorage.getItem('spotless-field-records-v1'));
ok(records.length===1&&records[0].repeat_offset_minutes===0,'first repeat saves actual time and stable group');
ok(records[0].arrivals_observed===null&&records[0].departures_observed===null,'unobserved movements remain missing');
get('repeat-next').click();ok(get('repeat-offset').value==='15'&&get('occupied').value==='','next repeat clears counts and advances planned offset');
get('side-confirmed').checked=true;get('use-pin').click();get('start').click();
for(const [id,value] of Object.entries({occupied:'3',vacant_legal:'1',unsuitable:'0',surveyed_capacity:'4'}))get(id).value=value;
get('movement-coverage').value='partial';get('movement-start').value=new Date(Date.now()-20000).toISOString();get('movement-end').value=new Date().toISOString();get('arrivals').value='1';get('departures').value='1';get('save').click();
records=JSON.parse(w.localStorage.getItem('spotless-field-records-v1'));
ok(records.length===2&&records[1].previous_observation_id===records[0].observation_id,'repeat links prior real snapshot');
ok(records[1].arrivals_observed===1&&records[1].departures_observed===1&&records[1].movement_coverage==='partial','actual watching window and movements survive save');
ok(d.documentElement.scrollWidth<=w.innerWidth,'repeat and movement form fits phone width');
const p=document.getElementById('pilot').contentWindow,pd=p.document,g=id=>pd.getElementById(id);
ok(g('trial').options.length===24,'prospective allocation has 24 planned slots');ok(g('face').value==='__FACE__','map face link prefills trial face ID');
for(const [id,value] of Object.entries({received_recommendation_at_utc:'2026-11-23T17:00Z',search_started_at_utc:'2026-11-23T17:01Z',reached_recommended_face_at_utc:'2026-11-23T17:04Z',parked_at_utc:'2026-11-23T17:05Z',search_ended_at_utc:'2026-11-23T17:05Z',walk_started_at_utc:'2026-11-23T17:06Z',destination_reached_at_utc:'2026-11-23T17:11Z',success:'true',followed:'true'}))g(id).value=value;
g('save').click();const trials=JSON.parse(p.localStorage.getItem('spotless-product-trials-v1'));
ok(trials.length===1&&trials[0].verified===false,'trip saves locally and remains unreviewed');ok(trials[0].predicted_probability_suitable===null,'unsupported suitable probability stays null');
let exported=null;p.URL.createObjectURL=b=>{exported=b;return 'blob:synthetic-only'};p.URL.revokeObjectURL=()=>{};p.HTMLAnchorElement.prototype.click=()=>{};g('export').click();
ok(exported&&JSON.parse((await exported.text()).trim()).trial_id===trials[0].trial_id,'trial JSONL export retains allocation ID');
const transfer=new p.DataTransfer();transfer.items.add(new p.File([await exported.text()],'synthetic.jsonl',{type:'application/json'}));g('restore').files=transfer.files;g('restore').dispatchEvent(new p.Event('change'));await new Promise(r=>setTimeout(r,200));
ok(JSON.parse(p.localStorage.getItem('spotless-product-trials-v1')).length===1,'trial backup import is idempotent');
ok(pd.documentElement.scrollWidth<=p.innerWidth,'trip ledger fits phone width');
document.getElementById('result').textContent=JSON.stringify({passed:true,checks,records,trials});
}catch(e){document.getElementById('result').textContent=JSON.stringify({passed:false,error:e.message,checks});}};
</script>'''
for k,v in {'__COLLECTOR__':(root/'reports/collector.html').as_uri()+'#face='+face,'__PILOT__':(root/'reports/product/pilot.html').as_uri()+'#face='+face,'__FACE__':face}.items():harness=harness.replace(k,v)
p=qa/'harness.html';p.write_text(harness,encoding='utf8')
result=subprocess.run([str(chrome),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--allow-file-access-from-files',f'--user-data-dir={qa/("profile-"+uuid.uuid4().hex)}','--virtual-time-budget=6000','--dump-dom',p.as_uri()],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
if not match:raise RuntimeError('Chrome did not return product results: '+result.stderr[-400:])
payload=json.loads(html.unescape(match[1]))
if not payload.get('passed'):raise AssertionError(payload)
with tempfile.TemporaryDirectory(dir=qa) as tmp:
    source=Path(tmp)/'synthetic-observations.jsonl';source.write_text(''.join(json.dumps(r)+'\n' for r in payload.pop('records')),encoding='utf8')
    accepted=ingest(source,output=Path(tmp)/'intake')
    if accepted['accepted']!=2:raise AssertionError(accepted)
    for t in payload.pop('trials'):PilotTrial.model_validate(t)
payload.update(real_outcome_stores_modified=False,fixture_records_are_performance_evidence=False)
(root/'reports/product/browser_validation.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf8');print(json.dumps(payload,indent=2))
