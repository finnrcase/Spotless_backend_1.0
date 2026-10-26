'use strict';
const inventory = JSON.parse(document.getElementById('inventory').textContent);
const $ = id => document.getElementById(id);
const facesById = new Map(inventory.faces.map(f => [f.id, f]));
const KEYS = { records: 'spotless-field-records-v1', draft: 'spotless-field-draft-v1', observer: 'spotless-field-observer-v1' };
let records = [], currentLocation = null, started = null, observationId = null, nearby = false, storageOkay = true;
let meterDraft = {};
const formatTime = iso => new Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(iso));
function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); $('message').hidden = false; }
function write(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch { storageOkay = false; $('draft-status').textContent = 'Browser storage unavailable. Keep this page open and export before leaving.'; return false; }
}
function read(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }
records = read(KEYS.records, []); if (!Array.isArray(records)) records = [];
$('observer').value = read(KEYS.observer, '');
function selectedFace() { return facesById.get($('face').value); }
function populateFaces(selected = $('face').value) {
  const q = $('search').value.toLowerCase().trim();
  let list = inventory.faces.filter(f => `${f.street} ${f.code} ${f.side_label}`.toLowerCase().includes(q));
  if (nearby && currentLocation) list.sort((a, b) => faceDistance(currentLocation, a) - faceDistance(currentLocation, b));
  const shown = list.slice(0, 100);
  if (selected && !shown.some(f => f.id === selected) && facesById.has(selected)) shown.unshift(facesById.get(selected));
  $('face').replaceChildren(new Option('Choose a street side…', ''), ...shown.map(f => new Option(`${f.street} · ${f.side_label} · ${f.code}`, f.id)));
  $('face').value = selected;
  $('face-count').textContent = `(${list.length} matching; first ${Math.min(100, list.length)} shown)`;
}
function renderMap(face) {
  const svg = $('map'); svg.replaceChildren();
  const [cx, cy] = face.center; const span = Math.max(face.span || .0015, .0015);
  const project = p => [160 + (p[0] - cx) / span * 230, 85 - (p[1] - cy) / span * 230];
  function path(coords, color, width) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    el.setAttribute('d', coords.map((p, i) => `${i ? 'L' : 'M'}${project(p).join(',')}`).join(' '));
    el.setAttribute('fill', 'none'); el.setAttribute('stroke', color); el.setAttribute('stroke-width', width); el.setAttribute('stroke-linecap', 'round'); svg.append(el);
  }
  for (const line of inventory.streets) if (Math.abs(line.center[0] - cx) < span * 2 && Math.abs(line.center[1] - cy) < span * 2) path(line.path, '#d0d9c9', 5);
  path(face.centerline, '#b1c2aa', 10);
  for (const p of face.paths) path(p, '#1e6954', 4);
  const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  circle.setAttribute('cx', '160'); circle.setAttribute('cy', '85'); circle.setAttribute('r', '5'); circle.setAttribute('fill', '#e4ae52'); circle.setAttribute('stroke', '#fff'); circle.setAttribute('stroke-width', '2'); svg.append(circle);
}
function showFace() {
  const face = selectedFace(); $('face-detail').hidden = !face;
  if (face) {
    $('face-name').textContent = `${face.street} · ${face.side_label} · ${face.code}`;
    $('face-evidence').textContent = `${face.method === 'authoritative_curb' ? 'Associated physical curb footprint' : 'Approximate centerline offset'}. Any linked curb assets are a historic supply prior: ${inventory.support.curb_asset_vintage}. They are not parking stalls. Street designation: ${face.street_designation}. ${face.meter_links} linked meter(s) in the inventory; verify parking type and public access in person. Endpoints: ${face.endpoints}.`;
    renderMap(face);
  }
  renderBayChecks();
}
function renderBayChecks() {
  const face=selectedFace(),container=$('meter-bays');container.replaceChildren();
  if(!face?.meter_bays?.length){container.textContent='No uniquely linked bay IDs on this face. This does not establish unmetered status or unrestricted parking.';return;}
  for(const bay of face.meter_bays){
    const row=document.createElement('div'),label=document.createElement('label'),select=document.createElement('select'),checkLabel=document.createElement('label'),check=document.createElement('input'),stamp=document.createElement('small');
    label.textContent=`${bay.space_id} · ${Number(bay.latitude).toFixed(5)}, ${Number(bay.longitude).toFixed(5)}`;
    select.setAttribute('aria-label',`Human state for bay ${bay.space_id}`);select.dataset.bayId=bay.space_id;
    for(const [value,text] of [['','Not observed'],['OCCUPIED','Occupied'],['VACANT','Vacant (rules separate)'],['UNKNOWN','Unknown / not visible']])select.add(new Option(text,value));
    select.value=meterDraft[bay.space_id]?.state||'';stamp.textContent=meterDraft[bay.space_id]?.observed_at_utc?formatTime(meterDraft[bay.space_id].observed_at_utc):'';
    check.type='checkbox';check.checked=meterDraft[bay.space_id]?.identity_verified||false;checkLabel.className='check';checkLabel.append(check,document.createTextNode('I matched this physical bay to the inventory ID/map position.'));
    select.onchange=()=>{if(!started){select.value='';message('Start the observation clock before checking a bay.',true);return;}if(select.value){meterDraft[bay.space_id]={space_id:bay.space_id,state:select.value,observed_at_utc:new Date().toISOString(),identity_verified:check.checked};stamp.textContent=formatTime(meterDraft[bay.space_id].observed_at_utc);}else{delete meterDraft[bay.space_id];stamp.textContent='';}persistDraft();};
    check.onchange=()=>{if(meterDraft[bay.space_id])meterDraft[bay.space_id].identity_verified=check.checked;persistDraft();};
    row.append(label,select,checkLabel,stamp);container.append(row);
  }
}
function collectDraft() {
  return { block_face_id: $('face').value, side_confirmed: $('side-confirmed').checked, observer: $('observer').value,
    start: started, id: observationId, location: currentLocation, occupied: $('occupied').value, vacant_legal: $('vacant_legal').value,
    unsuitable: $('unsuitable').value, surveyed_capacity: $('surveyed_capacity').value, complete_face: $('complete').checked,
    parking_type: $('parking-type').value, duration: $('duration').value, permit_class: $('permit').value,
    capacity_basis: $('capacity-basis').value, rules_checked: $('rules-checked').checked, vehicle_class: $('vehicle').value,
    sampling_stratum: $('stratum').value, sampling_method: $('sampling-method').value, observer_confidence: $('observer-confidence').value,
    restrictions_text: $('restrictions-text').value, curb_length: $('curb-length').value, measurement_method: $('measurement-method').value, notes: $('notes').value,
    gap_lengths:$('gap-lengths').value,obstructed_length:$('obstructed-length').value,counting_convention:$('counting-convention').value,exclusions_text:$('exclusions-text').value,
    survey_session_id:$('survey-session').value,assignment_id:$('assignment-id').value,meter_bays:Object.values(meterDraft) };
}
function persistDraft() { write(KEYS.draft, collectDraft()); write(KEYS.observer, $('observer').value); reconcile(); }
function reconcile() {
  try {
    const nums = ['occupied', 'vacant_legal', 'unsuitable', 'surveyed_capacity'].map(k => countValue($(k).value));
    $('reconcile').textContent = nums.some(n => n === null) ? 'Unknown counts stay blank. A complete snapshot needs all four counts.' : `${nums[0]} + ${nums[1]} + ${nums[2]} = ${nums[0] + nums[1] + nums[2]} · Total inspected: ${nums[3]}${nums[0] + nums[1] + nums[2] === nums[3] ? ' ✓' : ' — please reconcile'}`;
  } catch (e) { $('reconcile').textContent = e.message; }
}
function resetCount() {
  started = null; observationId = null;
  meterDraft={};renderBayChecks();
  for (const k of ['occupied', 'vacant_legal', 'unsuitable', 'surveyed_capacity', 'notes', 'restrictions-text', 'curb-length', 'measurement-method','gap-lengths','obstructed-length','exclusions-text']) $(k).value = '';
  $('side-confirmed').checked = false; $('rules-checked').checked = false;
  $('start').textContent = 'Start observation'; $('timer').textContent = 'Not started'; persistDraft();
}
function renderRecords() {
  $('saved-count').textContent = records.length;
  $('export').disabled = $('share').disabled = records.length === 0;
  $('saved-list').replaceChildren();
  for (const record of records.slice().reverse().slice(0, 12)) {
    const item = document.createElement('div'); item.className = 'saved-item';
    const heading = document.createElement('strong'); heading.textContent = `${facesById.get(record.block_face_id)?.street || 'Unknown face'} · ${record.parking_type}`;
    const desc = document.createElement('p'); desc.textContent = `${formatTime(record.survey_end_utc)} · ${record.occupied ?? '?'} occupied / ${record.vacant_legal ?? '?'} suitable empty · ${record.complete_face ? 'complete face' : 'partial view'}${record.location_method === 'confirmed_map_pin' ? ' · map pin, review needed' : ''}`;
    const undo = document.createElement('button'); undo.type = 'button'; undo.textContent = 'Remove'; undo.setAttribute('aria-label', `Remove saved observation from ${formatTime(record.survey_end_utc)}`);
    undo.addEventListener('click', () => { if (!window.confirm('Remove this device’s copy? Previously exported files are unchanged.')) return; const next = records.filter(r => r.observation_id !== record.observation_id); if (write(KEYS.records, next)) { records = next; renderRecords(); } else message('Could not save this removal. Export a backup first.', true); });
    item.append(undo, heading, desc); $('saved-list').append(item);
  }
}
populateFaces(); showFace(); renderRecords();
$('version').textContent = `· ${PROTOCOL}`;
$('support-note').textContent = `${inventory.faces.length.toLocaleString()} pilot faces loaded. ${inventory.support.fresh_faces} had partial fresh metered evidence at the ${formatTime(inventory.support.snapshot_utc)} snapshot; the rest had no fresh observed support. These are historical evidence counts, not current availability. Citywide accuracy remains unvalidated; areas outside this pilot are unsupported.`;
$('search').addEventListener('input', () => populateFaces());
$('face').addEventListener('change', () => { if (started) resetCount(); if (currentLocation?.method === 'confirmed_map_pin') currentLocation = null; $('assignment-id').value='';$('assignment-note').hidden=true; $('side-confirmed').checked = false; showFace(); persistDraft(); });
$('locate').addEventListener('click', () => {
  if (!navigator.geolocation || !window.isSecureContext) { message('GPS is unavailable in this browser context. Choose the street, verify the side, then confirm its map pin. HTTPS is needed for phone GPS.', true); return; }
  $('location-status').textContent = 'Finding location…';
  navigator.geolocation.getCurrentPosition(position => {
    currentLocation = { latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy: position.coords.accuracy, method: 'gps', captured_at: new Date().toISOString() };
    nearby = true; populateFaces(); $('location-status').textContent = `GPS ±${Math.round(position.coords.accuracy)} m`;
    if (position.coords.accuracy > 30) message('GPS is too imprecise for intake. Retry or explicitly confirm the selected face pin.', true);
    else message('Nearby faces appear first. Check the street side before counting.'); persistDraft();
  }, error => { $('location-status').textContent = 'No GPS fix'; message(`${error.message} Choose and confirm a map pin instead.`, true); }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
});
$('use-pin').addEventListener('click', () => {
  const face = selectedFace(); if (!face) return;
  currentLocation = { longitude: face.center[0], latitude: face.center[1], accuracy: null, method: 'confirmed_map_pin' };
  $('location-status').textContent = 'Confirmed map pin · review needed'; persistDraft(); message('Map pin selected as an estimated location. Confirm the side in person.');
});
$('start').addEventListener('click', () => {
  if (!selectedFace() || !$('side-confirmed').checked) { message('Choose and confirm the street side first.', true); return; }
  if (started && !window.confirm('Restart the observation clock? Keep the counts only if they are a fresh snapshot.')) return;
  started = new Date().toISOString(); observationId = globalThis.crypto?.randomUUID?.() || `manual-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  meterDraft={};renderBayChecks();
  if(!$('survey-session').value)$('survey-session').value=`session-${started.slice(0,10)}-${observationId.slice(0,8)}`;
  $('start').textContent = 'Restart clock'; persistDraft(); message('Observation started. Unknown counts stay blank.');
});
document.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => { const input = $(button.closest('.counter').dataset.field); input.value = Math.max(0, (Number(input.value) || 0) + Number(button.dataset.step)); persistDraft(); }));
document.querySelectorAll('input:not([type=file]),select,textarea').forEach(el => el.addEventListener('change', persistDraft));
document.querySelectorAll('input:not([type=file]),textarea').forEach(el => el.addEventListener('input', persistDraft));
$('save').addEventListener('click', () => {
  try {
    const record = makeObservation(collectDraft(), selectedFace());
    if (records.some(r => r.observation_id === record.observation_id)) throw new Error('This observation is already saved. Start another snapshot.');
    const next = [...records, record]; const persisted = write(KEYS.records, next); records = next; renderRecords(); resetCount();
    message(persisted ? 'Saved on this device. Export a backup after your walk.' : 'Saved in this open page only. Export now; browser storage is unavailable.', !persisted);
  } catch (e) { message(e.message, true); }
});
function exportFile() { return new File([jsonl(records)], `spotless-observations-${new Date().toISOString().slice(0, 10)}.jsonl`, { type: 'application/x-ndjson' }); }
$('export').addEventListener('click', () => {
  if (!records.length) return;
  const file = exportFile(), url = URL.createObjectURL(file), a = document.createElement('a'); a.href = url; a.download = file.name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  message('Export requested. Check your Downloads/Files app. Your saved records remain here.');
});
$('share').addEventListener('click', async () => {
  if (!records.length) return;
  const file = exportFile();
  if (!navigator.canShare?.({ files: [file] })) { message('File sharing is unavailable here. Use Export JSONL and transfer the file from Downloads.'); return; }
  try { await navigator.share({ files: [file], title: 'Spotless field observations' }); } catch (e) { if (e.name !== 'AbortError') message(e.message, true); }
});
$('restore').addEventListener('change', async event => {
  try {
    const file = event.target.files[0]; if (!file) return; if (file.size > 10_000_000) throw new Error('Backup exceeds the 10 MB restore limit. Split it before import.');
    const incoming = (await file.text()).split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line));
    const merged = new Map(records.map(r => [r.observation_id, r]));
    for (const r of incoming) {
      if (r.source_id !== 'manual_phone' || !r.observation_id || !facesById.has(r.block_face_id) || !r.survey_end_utc) throw new Error('Backup contains an unsupported record or unknown face.');
      if (merged.has(r.observation_id) && JSON.stringify(merged.get(r.observation_id)) !== JSON.stringify(r)) throw new Error('Conflicting observation IDs found. No backup records were imported.');
      merged.set(r.observation_id, r);
    }
    const next = [...merged.values()]; if (!write(KEYS.records, next)) throw new Error('Storage unavailable; keep the backup file.');
    records = next; renderRecords(); message('Backup merged. Full validation happens when you import into the Python project.');
  } catch (e) { message(e.message, true); }
  finally { event.target.value = ''; }
});
const restored = read(KEYS.draft, null);
if (restored) {
  meterDraft=Object.fromEntries((restored.meter_bays||[]).map(b=>[b.space_id,{...b,identity_verified:false}]));
  if (facesById.has(restored.block_face_id)) { populateFaces(restored.block_face_id); showFace(); }
  for (const [key, id] of Object.entries({ observer: 'observer', parking_type: 'parking-type', duration: 'duration', permit_class: 'permit', vehicle_class: 'vehicle', capacity_basis: 'capacity-basis', sampling_stratum: 'stratum', sampling_method:'sampling-method',observer_confidence:'observer-confidence',restrictions_text:'restrictions-text',curb_length:'curb-length',measurement_method:'measurement-method',gap_lengths:'gap-lengths',obstructed_length:'obstructed-length',counting_convention:'counting-convention',exclusions_text:'exclusions-text',survey_session_id:'survey-session',assignment_id:'assignment-id',notes: 'notes', occupied: 'occupied', vacant_legal: 'vacant_legal', unsuitable: 'unsuitable', surveyed_capacity: 'surveyed_capacity' })) if (restored[key] !== undefined) $(id).value = restored[key] ?? '';
  $('complete').checked = restored.complete_face ?? true; $('rules-checked').checked = restored.rules_checked ?? false;
  $('side-confirmed').checked = false; // Reconfirm the physical side after reopening.
  currentLocation = null; // A restored draft never implies a fresh GPS fix or pin confirmation.
  started = restored.start; observationId = restored.id; if (started) $('start').textContent = 'Restart clock';
}
function applyRoute(){
  const params=new URLSearchParams(location.hash.slice(1)),fid=params.get('face');if(!fid)return;
  if(!facesById.has(fid)){message('Route refers to an unknown face. Keep your existing draft.',true);return;}
  if(started&&$('face').value!==fid){message('A different face has an unfinished draft. Save or finish that observation before following this route link.',true);return;}
  populateFaces(fid);showFace();$('side-confirmed').checked=false;currentLocation=null;
  $('assignment-id').value=(params.get('assignment')||'').slice(0,120);$('survey-session').value=(params.get('session')||'').slice(0,120);
  $('sampling-method').value='repeat_visit';$('stratum').value='planned-field-route';
  $('assignment-note').hidden=false;$('assignment-note').textContent=`Planned visit: ${params.get('planned')||'time not supplied'}. This is a schedule, not an observation; actual start/end times are recorded when you count.`;persistDraft();
}
addEventListener('hashchange',applyRoute);applyRoute();
setInterval(() => { if (started) { const seconds = Math.floor((Date.now() - new Date(started).getTime()) / 1000); $('timer').textContent = seconds > 900 ? 'Expired · start a fresh snapshot' : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')} elapsed`; } }, 1000);
reconcile();
renderBayChecks();
