// Pure collection rules shared by the browser and Node tests.
export const PROTOCOL = 'manual-curb-survey/1.4';
export function gapLengths(value) {
  if (value == null || value.trim() === '') return null;
  if (value.trim() === '0') return [];
  const values=value.split(',').map(v=>Number(v.trim()));
  if (value.split(',').some(v=>v.trim()==='') || values.some(v=>!Number.isFinite(v)||v<=0)) throw Error('Enter positive gap lengths in metres separated by commas, 0 for no gaps, or blank if unmeasured.');
  return values;
}
export function countValue(value) {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0) throw new Error('Counts must be whole numbers, zero or greater.');
  return n;
}
export function makeObservation(draft, face, now = new Date()) {
  if (!face || draft.block_face_id !== face.id) throw new Error('Choose a known block face.');
  if (!draft.side_confirmed) throw new Error('Confirm the street side and the two ends of this block face.');
  if (!draft.observer?.trim()) throw new Error('Enter an observer nickname.');
  if (!draft.start) throw new Error('Start the observation before counting.');
  const start = new Date(draft.start), end = new Date(now);
  if (!Number.isFinite(start.getTime()) || start > end) throw new Error('The observation start time is invalid.');
  if (end - start > 15 * 60 * 1000) throw new Error('This observation is over 15 minutes old. Start a new snapshot.');
  const counts = ['occupied', 'vacant_legal', 'unsuitable', 'surveyed_capacity'].map(k => countValue(draft[k]));
  if (draft.complete_face && (counts.some(n => n === null) || counts[0] + counts[1] + counts[2] !== counts[3])) {
    throw new Error('For a complete count, fill every count and reconcile the total positions.');
  }
  const duration = countValue(draft.duration);
  if (duration !== null && duration < 1) throw new Error('Intended parking duration must be positive.');
  const location = draft.location;
  if (!location || !Number.isFinite(location.latitude) || !Number.isFinite(location.longitude)) throw new Error('Use a location fix or explicitly confirm the selected face pin.');
  if (location.method === 'gps' && (!(location.accuracy >= 0) || location.accuracy > 30)) throw new Error('GPS accuracy must be 30 m or better. Retry or confirm the map pin.');
  if (location.method === 'gps' && (!location.captured_at || end - new Date(location.captured_at) > 15 * 60 * 1000)) throw new Error('Your GPS fix is older than 15 minutes. Refresh your location.');
  if (face.paths && faceDistance(location, face) > Math.max(40, 2 * (location.accuracy || 0))) throw new Error('Your location is too far from this street side. Check the face or confirm its map pin.');
  const id = draft.id;
  if (!id) throw new Error('Observation ID is missing. Start a new snapshot.');
  if (draft.curb_length !== '' && draft.curb_length != null && (!Number.isFinite(Number(draft.curb_length)) || Number(draft.curb_length) < 0)) throw new Error('Measured curb length must be nonnegative or left blank.');
  const gaps=gapLengths(draft.gap_lengths);
  const physical=countValue(draft.physical_capacity),eligible=countValue(draft.eligible_capacity);
  if(physical!==null&&eligible!==null&&eligible>physical)throw Error('Eligible supply cannot exceed physical positions.');
  if(eligible!==null&&counts[1]!==null&&counts[1]>eligible)throw Error('Suitable vacancies cannot exceed eligible positions.');
  if(draft.repeat_offset_minutes!=null&&draft.repeat_offset_minutes!==''&&(![0,15,30,60].includes(Number(draft.repeat_offset_minutes))||!draft.repeat_group_id))throw Error('Repeat snapshots require a group and a 0/15/30/60 offset.');
  const obstructed=draft.obstructed_length==null||draft.obstructed_length===''?null:Number(draft.obstructed_length);
  if(obstructed!==null&&(!Number.isFinite(obstructed)||obstructed<0))throw Error('Obstructed length must be nonnegative or blank.');
  const provenance = Object.fromEntries(['occupied', 'vacant_legal', 'unsuitable', 'surveyed_capacity'].map((k, i) => [k, counts[i] === null ? 'unavailable' : 'observed']));
  provenance.latitude = provenance.longitude = location.method === 'gps' ? 'observed' : 'assumed';
  provenance.parking_type = draft.parking_type === 'unknown' ? 'unavailable' : 'observed';
  provenance.surveyed_capacity = counts[3] === null ? 'unavailable' : draft.capacity_basis === 'marked_spaces' ? 'observed' : draft.capacity_basis === 'estimated_positions' ? 'assumed' : 'unavailable';
  provenance['meter_bays.state']=draft.meter_bays?.length?'observed':'unavailable';
  provenance['meter_bays.identity']=draft.meter_bays?.length?(draft.meter_bays.every(b=>b.identity_verified===true)?'observed':'assumed'):'unavailable';
  return {
    schema_version: '1.0', source_id: 'manual_phone', source_record_id: id,
    source_version: PROTOCOL, retrieved_at_utc: end.toISOString(), field_provenance: provenance,
    confidence: location.method === 'gps' && draft.rules_checked ? 0.7 : 0.4,
    observation_id: id, block_face_id: face.id, observer_pseudonym: draft.observer.trim(),
    survey_session_id:draft.survey_session_id?.trim()||null,assignment_id:draft.assignment_id?.trim()||null,
    survey_start_utc: start.toISOString(), survey_end_utc: end.toISOString(),
    occupied: counts[0], vacant_legal: counts[1], unsuitable: counts[2], surveyed_capacity: counts[3],
    complete_face: Boolean(draft.complete_face), location_method: location.method,
    gps_accuracy_m: location.method === 'gps' ? location.accuracy : null,
    latitude: location.latitude, longitude: location.longitude,
    parking_type: draft.parking_type || 'unknown', rules_checked: Boolean(draft.rules_checked),
    intended_duration_minutes: duration, vehicle_class: draft.vehicle_class || 'standard_passenger',
    capacity_basis: draft.capacity_basis || 'unknown', permit_class: draft.permit_class?.trim() || null,
    sampling_stratum: draft.sampling_stratum?.trim() || null, sampling_method: draft.sampling_method || 'unspecified',
    observer_confidence: draft.observer_confidence === '' || draft.observer_confidence == null ? null : Number(draft.observer_confidence),
    restrictions_text: draft.restrictions_text?.trim() || '',
    curb_usable_length_m: draft.curb_length === '' || draft.curb_length == null ? null : Number(draft.curb_length),
    measurement_method: draft.measurement_method?.trim() || null, notes: draft.notes?.trim() || ''
    ,gap_lengths_m:gaps,obstructed_curb_length_m:obstructed,counting_convention:draft.counting_convention?.trim()||null,exclusions_text:draft.exclusions_text?.trim()||''
    ,meter_bays:validateBayChecks(draft.meter_bays,face,start,end)
    ,...movementFields(draft,end),physical_capacity:countValue(draft.physical_capacity),eligible_capacity:countValue(draft.eligible_capacity)
    ,repeat_group_id:draft.repeat_group_id||null,repeat_offset_minutes:draft.repeat_offset_minutes==null||draft.repeat_offset_minutes===''?null:Number(draft.repeat_offset_minutes),previous_observation_id:draft.previous_observation_id||null
    ,previous_observation_age_minutes:draft.previous_observed_at_utc?Math.max(0,(start-new Date(draft.previous_observed_at_utc))/60000):null
  };
}
export function movementFields(draft,end){
  const coverage=draft.movement_coverage||'not_observed',a=countValue(draft.arrivals),d=countValue(draft.departures);
  if(coverage==='not_observed'){
    if(draft.movement_start||draft.movement_end||a!==null||d!==null)throw Error('Clear unobserved movements or record their actual watching window.');
    return {movement_coverage:coverage,movement_start_utc:null,movement_end_utc:null,arrivals_observed:null,departures_observed:null};
  }
  const start=new Date(draft.movement_start),finish=new Date(draft.movement_end),aware=v=>typeof v==='string'&&/(Z|[+-]\d\d:\d\d)$/.test(v);
  if(!['partial','continuous'].includes(coverage)||!aware(draft.movement_start)||!aware(draft.movement_end)||!Number.isFinite(+start)||!Number.isFinite(+finish)||start>=finish||finish>end)throw Error('Movement watching needs actual start/end timestamps with offsets, ending by now.');
  if(coverage==='continuous'&&(a===null||d===null))throw Error('Continuous watching requires both movement counts; record 0 only after checking.');
  return {movement_coverage:coverage,movement_start_utc:start.toISOString(),movement_end_utc:finish.toISOString(),arrivals_observed:a,departures_observed:d};
}
export function repeatStatus(records,faceId,session,now=new Date()){
  const same=records.filter(r=>r.block_face_id===faceId&&r.survey_session_id===session),last=same.slice().sort((a,b)=>Date.parse(b.survey_end_utc)-Date.parse(a.survey_end_utc))[0];
  const anchor=same.find(r=>r.repeat_offset_minutes===0),next=[0,15,30,60].find(n=>!same.some(r=>r.repeat_offset_minutes===n));
  return {previous_id:last?.observation_id||null,previous_at:last?.survey_end_utc||null,age_minutes:last?Math.max(0,(now-new Date(last.survey_end_utc))/60000):null,next_offset:next??null,
    due_at:anchor&&next!=null?new Date(Date.parse(anchor.survey_start_utc)+next*60000).toISOString():null};
}
export function validateBayChecks(bays,face,start,end){
  if(bays==null||bays.length===0)return null;
  if(!Array.isArray(bays)||bays.length>100)throw Error('At most 100 bay observations per snapshot.');
  const allowed=new Set((face.meter_bays||[]).map(b=>b.space_id)),seen=new Set();
  return bays.map(b=>{const at=new Date(b.observed_at_utc);if(!allowed.has(b.space_id)||seen.has(b.space_id))throw Error('Unknown, incorrectly mapped or duplicate meter bay.');if(!['OCCUPIED','VACANT','UNKNOWN'].includes(b.state)||!Number.isFinite(+at)||at<start||at>end)throw Error('Bay state/time is invalid or outside this snapshot.');seen.add(b.space_id);return {space_id:b.space_id,state:b.state,observed_at_utc:at.toISOString(),identity_verified:b.identity_verified===true};});
}
export function jsonl(records) { return records.map(r => JSON.stringify(r)).join('\n') + (records.length ? '\n' : ''); }
export function distanceMeters(a, b) {
  const rad = Math.PI / 180, lat = (a.latitude + b.latitude) * rad / 2;
  return Math.hypot((a.longitude - b.longitude) * Math.cos(lat) * 111320, (a.latitude - b.latitude) * 111320);
}
export function faceDistance(point, face) {
  const lat = point.latitude * Math.PI / 180, scaleX = Math.cos(lat) * 111320;
  let best = Infinity;
  for (const path of face.paths || []) {
    for (let i = 1; i < path.length; i++) {
      const ax = (path[i - 1][0] - point.longitude) * scaleX, ay = (path[i - 1][1] - point.latitude) * 111320;
      const bx = (path[i][0] - point.longitude) * scaleX, by = (path[i][1] - point.latitude) * 111320;
      const dx = bx - ax, dy = by - ay, d = dx * dx + dy * dy;
      const t = d ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / d)) : 0;
      best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
    }
  }
  return best;
}
