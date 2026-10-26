"""Synthetic local review UI -> schema -> intake; no real media/outcomes altered."""
import html,json,os,re,subprocess,tempfile,uuid
from pathlib import Path
from PIL import Image
from la_parking.capture_collection import import_captures,audit,import_reviews

root=Path.cwd();qa=root/'.browser-qa/capture-review';qa.mkdir(parents=True,exist_ok=True)
chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
if not chrome.exists():raise SystemExit('Chrome unavailable; capture review UI not tested')
with tempfile.TemporaryDirectory(dir=qa) as tmp:
    directory=Path(tmp);image=directory/'synthetic.jpg';Image.new('RGB',(64,64),'gray').save(image)
    face=json.loads((root/'reports/collection/development_plan.json').read_text())['faces_detail'][0]['block_face_id']
    capture={'capture_id':'synthetic-browser-capture','block_face_id':face,'session_id':'synthetic-session','visit_id':'synthetic-visit','source':'walking_camera','media_path':str(image),'capture_at_utc':'2026-10-01T12:00Z','time_precision':'exact_offset','latitude':34.06,'longitude':-118.44,'detector_count_candidate':99}
    manifest=directory/'synthetic.jsonl';manifest.write_text(json.dumps(capture)+'\n');db=directory/'db';out=directory/'review'
    import_captures(manifest,db);audit(db,out)
    harness='''<!doctype html><iframe id="app" style="width:390px;height:844px" src="__QUEUE__"></iframe><pre id="result">RUNNING</pre><script>onload=async()=>{const checks=[],ok=(v,n)=>{if(!v)throw Error(n);checks.push(n)};try{const w=document.getElementById('app').contentWindow,d=w.document,g=id=>d.getElementById(id);ok(g('task').options.length===1,'local capture metadata appears in queue');ok(!g('queue').textContent.includes('detector_count_candidate'),'CV candidates are withheld from blinded reviewer');g('reviewer').value='synthetic-blind-rater';g('scope').value='full-fixture-face';g('count').value='3';g('fraction').value='0.5';for(const id of ['privacy','time','location','blind'])g(id).checked=true;g('save').click();ok(g('status').textContent.startsWith('Saved'),'manual independent review saved without promoting a label');let exported=null;w.URL.createObjectURL=b=>{exported=b;return 'blob:synthetic'};w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=()=>{};g('export').click();const row=JSON.parse((await exported.text()).trim());ok(row.occupied_visible===3&&row.full_face_visible===false,'partial count remains visible-only');ok(row.legal_capacity===null&&row.legal_capacity_status==='unknown','missing legal supply stays unknown');ok(d.documentElement.scrollWidth<=w.innerWidth,'capture review fits phone width');document.getElementById('result').textContent=JSON.stringify({passed:true,checks,row});}catch(e){document.getElementById('result').textContent=JSON.stringify({passed:false,error:e.message,checks});}};</script>'''
    target=directory/'harness.html';target.write_text(harness.replace('__QUEUE__',(out/'review_queue.html').as_uri()),encoding='utf8')
    result=subprocess.run([str(chrome),'--headless=new','--disable-gpu','--allow-file-access-from-files','--no-first-run','--no-default-browser-check',f'--user-data-dir={qa/("profile-"+uuid.uuid4().hex)}','--virtual-time-budget=4000','--dump-dom',target.as_uri()],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S)
    if not match:raise RuntimeError('No Chrome review result')
    payload=json.loads(html.unescape(match[1]))
    if not payload.get('passed'):raise AssertionError(payload)
    reviews=directory/'reviews.jsonl';reviews.write_text(json.dumps(payload.pop('row'))+'\n');assert import_reviews(reviews,db)['accepted_reviews']==1
    payload.update(real_outcome_stores_modified=False,synthetic_fixture_not_performance=True)
Path('reports/collection/browser_validation.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf8');print(json.dumps(payload,indent=2))
