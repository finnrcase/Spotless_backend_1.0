"""Owns a temporary loopback server and Chrome profile; never inserts real observations."""
from pathlib import Path
import html,json,os,re,socket,subprocess,sys,time,uuid
import requests

root=Path.cwd();qa=root/'.browser-qa/service';qa.mkdir(parents=True,exist_ok=True)
run=uuid.uuid4().hex;directory=qa/run;directory.mkdir();report=root/'reports/service';report.mkdir(exist_ok=True)
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
harness='''<!doctype html><html><meta charset="utf-8"><body style="margin:0"><iframe id="app" src="/" style="width:1200px;height:900px;border:0"></iframe><pre id="result">RUNNING</pre><script>
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn){for(let i=0;i<300;i++){if(fn())return;await pause(100);}throw Error('Timed out waiting for UI response');}
document.getElementById('app').onload=async()=>{
 const win=document.getElementById('app').contentWindow,d=win.document,get=id=>d.getElementById(id),checks=[];
 const ok=(test,name)=>{if(!test)throw Error(name);checks.push(name)};
 const errors=[];win.addEventListener('error',e=>errors.push(e.message));win.addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
 try{
  await until(()=>get('arrival').value&&d.querySelectorAll('#map path').length>0);ok(true,'map shell and real street geometry loaded');
  get('destination-search').value='WESTWOOD';get('search').click();await until(()=>get('destinations').options.length>1);ok(true,'destination street search reached API');
  get('mode').value='historical_replay';get('mode').dispatchEvent(new Event('change'));
  await until(()=>get('notice').textContent.startsWith('HISTORICAL REPLAY'));
  ok(d.querySelectorAll('#results li').length>0,'nearby forecasts rendered');ok(d.querySelectorAll('#map .face').length>0,'block-face overlays rendered');
  const chooseModel=()=>{const p=[...d.querySelectorAll('#map .face')].find(x=>x.getAttribute('stroke')==='#2e64b8');if(!p)throw Error('No supported model overlay in the real replay');p.dispatchEvent(new MouseEvent('click',{bubbles:true}));};
  chooseModel();
  ok(get('details').textContent.includes('Experimental panel'),'trained panel estimate shown with experimental scope');
  ok(get('details').textContent.includes('unknown'),'missing rules remain unknown in UI');
  ok(get('details').textContent.includes('2014'),'historic curb asset age is visible in details');
  get('time-slider').value='30';get('time-slider').dispatchEvent(new Event('input'));
  await pause(600);await until(()=>get('notice').textContent.startsWith('HISTORICAL REPLAY')&&!get('predict').disabled);
  chooseModel();
  ok(get('offset').textContent.includes('30'),'time slider triggers a new arrival request');
  ok(get('details').textContent.includes('Panel net change'),'15/30/60 change display is explicit');
  const face=d.querySelector('#map .face');face.dispatchEvent(new MouseEvent('click',{bubbles:true}));ok(get('details').textContent.includes('Eligibility for entire stay'),'map click opens full-stay details');
  get('mode').value='live';get('mode').dispatchEvent(new Event('change'));await until(()=>get('notice').textContent.startsWith('LIVE REQUEST'));
  ok(get('details').textContent.includes('No supported recent feature window')||get('details').textContent.includes('newest observed'),'live stale evidence is visible');
  get('obs-submit').click();await pause(200);ok(get('notice').textContent.includes('Confirm the in-person'),'UI does not fabricate a field observation');
  ok(errors.length===0,'no uncaught browser errors');
  document.getElementById('result').textContent=JSON.stringify({passed:true,checks,browser_errors:errors});
 }catch(e){document.getElementById('result').textContent=JSON.stringify({passed:false,error:e.message,checks,browser_errors:errors});}
};</script></body></html>'''
(directory/'harness.html').write_text(harness,encoding='utf8')
server_code="from pathlib import Path; from la_parking.service.api import create_app; from fastapi.responses import HTMLResponse; import uvicorn; app=create_app(observations_dir=Path("+repr(str(directory/'observations'))+")); app.add_api_route('/__qa',lambda:HTMLResponse(Path("+repr(str(directory/'harness.html'))+").read_text(encoding='utf8')),include_in_schema=False); uvicorn.run(app,host='127.0.0.1',port="+str(port)+")"
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
log=(directory/'server.log').open('w',encoding='utf8')
server=subprocess.Popen([sys.executable,'-c',server_code],cwd=root,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
url=f'http://127.0.0.1:{port}'
try:
    for _ in range(160):
        try:
            if requests.get(url+'/api/config',timeout=1).status_code==200:break
        except requests.RequestException:pass
        if server.poll() is not None:raise RuntimeError('Server exited: '+(directory/'server.log').read_text(encoding='utf8')[-2000:])
        time.sleep(.25)
    else:raise RuntimeError('Local server did not become ready')
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    args=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',f'--user-data-dir={directory / "profile"}',
          '--virtual-time-budget=45000','--window-size=1440,1000','--dump-dom',url+'/__qa']
    output=subprocess.run(args,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=90,creationflags=flags)
    match=re.search(r'<pre id="result">(.*?)</pre>',output.stdout,re.S)
    if not match:raise RuntimeError('No browser result: '+output.stderr[-1000:])
    payload=json.loads(html.unescape(match.group(1)))
    if not payload.get('passed'):raise AssertionError(payload)
    assert not (directory/'observations/manual_observations.parquet').exists()
    payload['no_synthetic_observations_written']=True
    payload['server_log']=str((directory/'server.log').relative_to(root))
    (report/'browser_validation.json').write_text(json.dumps(payload,indent=2),encoding='utf8')
    print(json.dumps(payload,indent=2),flush=True)
finally:
    server.terminate()
    try:server.wait(timeout=10)
    except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
    log.close()
