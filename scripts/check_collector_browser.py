"""Real Chrome smoke test; fixtures stay in ignored .browser-qa, never training data."""
import json
import os
from pathlib import Path
import re
import subprocess
import html
import tempfile
import uuid
from la_parking.observations import ingest

root=Path.cwd(); qa=root/'.browser-qa'; qa.mkdir(exist_ok=True)
browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
if not browser.exists(): raise SystemExit('Chrome not available: browser check not run')
target=(root/'reports/collector.html').as_uri()
harness='''<!doctype html><html><meta charset="utf-8"><title>Collector browser tests</title><body>
<iframe id="app" style="width:390px;height:844px" src="__TARGET__"></iframe><pre id="result">RUNNING</pre>
<script>
document.getElementById('app').onload=async()=>{
 const win=document.getElementById('app').contentWindow, d=win.document, get=id=>d.getElementById(id); const checks=[];
 const ok=(test,name)=>{if(!test) throw Error(name);checks.push(name)};
 try {
  ok(get('face').options.length>1,'real inventory loaded');
  ok(d.documentElement.scrollWidth<=win.innerWidth,'390px viewport has no horizontal overflow');
  get('face').selectedIndex=1; get('face').dispatchEvent(new Event('change'));
  ok(!get('face-detail').hidden,'side diagram displayed');
  get('observer').value='browser-fixture-only'; get('side-confirmed').checked=true;
  get('use-pin').click(); get('parking-type').value='unmetered'; get('capacity-basis').value='marked_spaces'; get('rules-checked').checked=true;
  ok(get('parking-type').value==='unmetered','unmetered type selectable');
  get('start').click();
  get('occupied').value='3';get('vacant_legal').value='0';get('unsuitable').value='1';get('surveyed_capacity').value='9';
  get('save').click(); ok(get('saved-count').textContent==='0','bad counts rejected');
  get('surveyed_capacity').value='4'; get('save').click();
  ok(get('saved-count').textContent==='1','valid count saved');
  const records=JSON.parse(win.localStorage.getItem('spotless-field-records-v1'));
  ok(records[0].vacant_legal===0,'observed zero preserved');
  ok(records[0].location_method==='confirmed_map_pin'&&records[0].gps_accuracy_m===null,'map pin never GPS');
  ok(records[0].parking_type==='unmetered','field parking type preserved');
  ok(d.documentElement.scrollWidth<=win.innerWidth,'selected face fits the phone viewport');
  const backup=new win.File([JSON.stringify(records[0])+'\\n'],'fixture.jsonl',{type:'application/x-ndjson'});
  const transfer=new win.DataTransfer();transfer.items.add(backup);get('restore').files=transfer.files;get('restore').dispatchEvent(new Event('change'));
  await new Promise(r=>setTimeout(r,100));ok(get('saved-count').textContent==='1','backup restore deduplicates');
  document.getElementById('result').textContent=JSON.stringify({passed:true,checks,record:records[0]});
 } catch(e) {document.getElementById('result').textContent=JSON.stringify({passed:false,error:e.message,checks});}
};</script></body></html>'''.replace('__TARGET__',target)
(qa/'harness.html').write_text(harness,encoding='utf8')
run_id=uuid.uuid4().hex
flags=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--allow-file-access-from-files',f'--user-data-dir={qa / ("profile-"+run_id)}']
result=subprocess.run([*flags,'--virtual-time-budget=4000','--dump-dom',(qa/'harness.html').as_uri()],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
if not match: raise RuntimeError('Browser did not return test results: '+result.stderr[-1000:])
payload=json.loads(html.unescape(match.group(1)))
if not payload.get('passed'): raise AssertionError(payload)
# Validate the browser's test-only export through the real Python intake.
with tempfile.TemporaryDirectory(dir=qa) as temp:
    record_path=Path(temp)/'test-only.jsonl'; record_path.write_text(json.dumps(payload.pop('record')),encoding='utf8')
    intake=ingest(record_path,output=Path(temp)/'intake')
    if intake['accepted']!=1: raise AssertionError(intake)
    payload['python_intake_accepted_fixture']=True
# Separate clean profile for the untouched mobile-sized screenshot.
(qa/'mobile-preview.html').write_text('<!doctype html><html><body style="margin:0"><iframe style="width:390px;height:844px;border:0" src="'+target+'"></iframe></body></html>',encoding='utf8')
shot=subprocess.run([str(browser),'--headless=new','--disable-gpu','--no-first-run','--allow-file-access-from-files',f'--user-data-dir={qa / ("screenshot-"+run_id)}','--window-size=390,844',f'--screenshot={root / "reports/collector_mobile.png"}',(qa/'mobile-preview.html').as_uri()],capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
payload['mobile_screenshot_created']=(root/'reports/collector_mobile.png').exists()
Path('reports/collector_browser_validation.json').write_text(json.dumps(payload,indent=2),encoding='utf8')
print(json.dumps(payload,indent=2))
