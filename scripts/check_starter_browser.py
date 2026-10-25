"""Chrome QA for the route -> phone counts and historic annotation workflows.

Fixtures live only in a fresh QA browser profile and temporary intake directory.
The export clicks are intercepted so no fixture is written into user Downloads.
"""
import html
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
from urllib.parse import urlencode
from la_parking.observations import ingest

root=Path.cwd();qa=root/'.browser-qa';qa.mkdir(exist_ok=True)
browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
if not browser.exists():raise SystemExit('Chrome unavailable; browser QA not run')
plan=json.loads((root/'reports/field_route.json').read_text());assignment=plan['assignments'][0]
fragment=urlencode({'face':assignment['block_face_id'],'session':assignment['survey_session_id'],'assignment':assignment['assignment_id'],'planned':assignment['scheduled_local']})
template='''<!doctype html><html><meta charset="utf-8"><title>Starter flow QA</title><body>
<iframe id="route" style="width:390px;height:844px" src="__ROUTE__"></iframe>
<iframe id="collector" style="width:390px;height:844px" src="__COLLECTOR__"></iframe>
<iframe id="imagery" style="width:390px;height:844px" src="__IMAGERY__"></iframe><pre id="result">RUNNING</pre><script>
window.onload=async()=>{
const checks=[],ok=(v,name)=>{if(!v)throw Error(name);checks.push(name)},get=id=>document.getElementById(id);
try{
const route=get('route').contentWindow,rd=route.document;
ok(rd.getElementById('visits').children.length===20,'route displays 20 selectable faces');
rd.getElementById('small-batch').click();
ok(rd.getElementById('visits').children.length===8,'small batch displays eight prefilled repeated visits');
ok(new Set([...rd.querySelectorAll('#visits a')].map(a=>new URLSearchParams(a.hash.slice(1)).get('face'))).size===2,'small batch repeats two real faces');
rd.getElementById('session').selectedIndex=0;rd.getElementById('session').dispatchEvent(new Event('change'));
ok(rd.querySelector('#visits a').getAttribute('href').includes('assignment='),'route links carry stable assignment IDs');
ok(rd.documentElement.scrollWidth<=route.innerWidth,'route fits 390px viewport');
const win=get('collector').contentWindow,d=win.document,$=id=>d.getElementById(id);
ok($('face').value==='__FACE__','route preselects real inventory face');
ok($('assignment-id').value==='__ASSIGNMENT__'&&$('survey-session').value==='__SESSION__','session and assignment prefilled');
$('observer').value='browser-fixture-only';$('side-confirmed').checked=true;$('use-pin').click();$('parking-type').value='unmetered';
$('capacity-basis').value='estimated_positions';$('start').click();$('occupied').value='3';$('vacant_legal').value='0';$('unsuitable').value='1';$('surveyed_capacity').value='4';
$('gap-lengths').value='0';$('obstructed-length').value='0';$('counting-convention').value='synthetic QA positions only';$('save').click();
const records=JSON.parse(win.localStorage.getItem('spotless-field-records-v1'));
ok(records.length===1&&records[0].vacant_legal===0,'count saved with observed zero');
ok(Array.isArray(records[0].gap_lengths_m)&&records[0].gap_lengths_m.length===0,'checked absence of gaps differs from unmeasured');
ok(records[0].assignment_id==='__ASSIGNMENT__'&&records[0].survey_session_id==='__SESSION__','route metadata survives collection');
ok(d.documentElement.scrollWidth<=win.innerWidth,'expanded collector fits 390px viewport');
const iw=get('imagery').contentWindow,doc=iw.document,i$=id=>doc.getElementById(id),canvas=i$('image');
await new Promise(r=>setTimeout(r,250));ok(i$('task').options.length===24,'24 real imagery tasks loaded');
ok(canvas.width===600&&canvas.getContext('2d').getImageData(100,100,1,1).data[3]>0,'real historic image rendered');
// Synthetic pointer events have no active device pointer; neutralize capture only in this QA frame.
canvas.setPointerCapture=()=>{};const rect=canvas.getBoundingClientRect();
const event=(kind,x,y)=>canvas.dispatchEvent(new iw.PointerEvent(kind,{pointerId:1,bubbles:true,clientX:rect.left+x/600*rect.width,clientY:rect.top+y/600*rect.height}));
i$('tool').value='visible_curb';i$('tool').dispatchEvent(new iw.Event('change'));
for(const [x,y] of [[10,10],[100,10],[100,100],[10,100]])event('pointerdown',x,y);i$('finish').click();
i$('tool').value='curbside_vehicle_candidate';i$('tool').dispatchEvent(new iw.Event('change'));event('pointerdown',20,20);event('pointerup',30,30);
i$('annotator').value='synthetic-browser-fixture';i$('annotator').dispatchEvent(new iw.Event('input'));i$('reviewed').checked=true;i$('reviewed').dispatchEvent(new iw.Event('input'));i$('complete').checked=true;i$('complete').dispatchEvent(new iw.Event('input'));
const annotations=Object.values(JSON.parse(iw.localStorage.getItem('spotless-imagery-annotations-v1'))),review=annotations[0];
ok(review.shapes.length===2&&review.shapes[0].class==='visible_curb','visible mask and vehicle rectangle saved separately');
ok(review.capture_time_precision==='date_only'&&review.time_specific_truth===false,'historic date-only status preserved');
let exported=null;iw.URL.createObjectURL=blob=>{exported=blob;return 'blob:qa-only';};iw.URL.revokeObjectURL=()=>{};iw.HTMLAnchorElement.prototype.click=()=>{};i$('export').click();
ok(exported&&JSON.parse(await exported.text())[0].image_sha256===review.image_sha256,'annotation export preserves exact image hash');
i$('task').selectedIndex=1;i$('task').dispatchEvent(new iw.Event('change'));i$('task').selectedIndex=0;i$('task').dispatchEvent(new iw.Event('change'));
ok(i$('shape-count').textContent.startsWith('2 shapes'),'annotations persist across task switches');
ok(doc.documentElement.scrollWidth<=iw.innerWidth,'annotation workflow fits 390px viewport');
document.getElementById('result').textContent=JSON.stringify({passed:true,checks,collector_record:records[0],annotation:review});
}catch(e){document.getElementById('result').textContent=JSON.stringify({passed:false,error:e.message,checks});}
};</script></body></html>'''
values={'__ROUTE__':(root/'reports/field_route.html').as_uri(),'__COLLECTOR__':(root/'reports/collector.html').as_uri()+'#'+fragment,
    '__IMAGERY__':(root/'reports/imagery/annotator.html').as_uri(),'__FACE__':assignment['block_face_id'],
    '__ASSIGNMENT__':assignment['assignment_id'],'__SESSION__':assignment['survey_session_id']}
for key,value in values.items():template=template.replace(key,value)
harness=qa/'starter-harness.html';harness.write_text(template,encoding='utf8');run_id=uuid.uuid4().hex
args=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--allow-file-access-from-files',
    f'--user-data-dir={qa/("starter-profile-"+run_id)}','--virtual-time-budget=5000','--dump-dom',harness.as_uri()]
result=subprocess.run(args,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60,
    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
if not match:raise RuntimeError('Chrome did not return QA results: '+result.stderr[-500:])
payload=json.loads(html.unescape(match[1]))
if not payload.get('passed'):raise AssertionError(payload)
with tempfile.TemporaryDirectory(dir=qa) as temp:
    record=Path(temp)/'synthetic-only.jsonl';record.write_text(json.dumps(payload.pop('collector_record')),encoding='utf8')
    accepted=ingest(record,output=Path(temp)/'synthetic-intake')
    if accepted['accepted']!=1:raise AssertionError(accepted)
    annotation=payload.pop('annotation');(Path(temp)/'synthetic-annotation.json').write_text(json.dumps(annotation))
payload['python_intake_accepted_test_record']=True;payload['real_observation_store_modified']=False
Path('reports/starter/browser_validation.json').write_text(json.dumps(payload,indent=2),encoding='utf8');print(json.dumps(payload,indent=2))
