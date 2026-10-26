import test from 'node:test';
import assert from 'node:assert/strict';
import { makeObservation, countValue, jsonl, faceDistance,gapLengths,validateBayChecks } from '../web/collector/model.mjs';
const now = new Date('2026-10-25T12:05:00Z');
const face = { id: 'face-1', paths: [[[-118.45,34.06],[-118.44,34.06]]] };
const draft = () => ({ id: 'test-only', block_face_id: 'face-1', observer: 'fixture', side_confirmed: true,
  start: '2026-10-25T12:00:00Z', occupied: '3', vacant_legal: '0', unsuitable: '1', surveyed_capacity: '4',
  complete_face: true, parking_type: 'unmetered', capacity_basis: 'estimated_positions', rules_checked: true, duration: '60',
  location: { latitude: 34.06, longitude: -118.445, accuracy: null, method: 'confirmed_map_pin' } });
test('unknown counts remain null, observed zero remains zero', () => { assert.equal(countValue(''), null); assert.equal(countValue('0'), 0); assert.throws(() => countValue('-1')); });

test('independent bay observations retain identity uncertainty without changing face counts',()=>{
  const f={...face,meter_bays:[{space_id:'fixture-bay'}]},b={space_id:'fixture-bay',state:'VACANT',observed_at_utc:'2026-10-25T12:02Z',identity_verified:false};
  const d={...draft(),meter_bays:[b]};const r=makeObservation(d,f,now);
  assert.equal(r.meter_bays[0].identity_verified,false);assert.equal(r.vacant_legal,0);
  assert.throws(()=>validateBayChecks([b,b],f,new Date(d.start),now));
  assert.throws(()=>validateBayChecks([{...b,space_id:'other'}],f,new Date(d.start),now));
  assert.throws(()=>validateBayChecks([{...b,observed_at_utc:'2026-10-25T11:00Z'}],f,new Date(d.start),now));
});
test('complete count reconciles and preserves map-pin provenance', () => {
  const r = makeObservation(draft(), face, now); assert.equal(r.vacant_legal, 0); assert.equal(r.gps_accuracy_m, null);
  assert.equal(r.field_provenance.latitude, 'assumed'); assert.equal(r.field_provenance.surveyed_capacity, 'assumed');
  assert.equal(r.parking_type, 'unmetered'); assert.equal(JSON.parse(jsonl([r])).observation_id, r.observation_id);
});
test('incomplete counts never become full-face labels', () => {
  const d = draft(); d.complete_face = false; d.occupied = ''; const r = makeObservation(d, face, now); assert.equal(r.occupied, null); assert.equal(r.field_provenance.occupied, 'unavailable');
});
test('count mismatch, unconfirmed side and stale sweep are rejected', () => {
  for (const change of [{ surveyed_capacity: '9' }, { side_confirmed: false }, { start: '2026-10-25T11:00:00Z' }]) assert.throws(() => makeObservation({ ...draft(), ...change }, face, now));
});
test('bad or stale GPS and distant locations cannot pass client validation', () => {
  for (const change of [{ accuracy: 100 }, { latitude: 35 }, { captured_at: '2026-10-25T11:00:00Z' }]) {
    const d = draft(); d.location = { ...d.location, method: 'gps', accuracy: 5, captured_at: '2026-10-25T12:00:00Z', ...change }; assert.throws(() => makeObservation(d, face, now));
  }
  assert.ok(faceDistance({ latitude: 34.06, longitude: -118.445 }, face) < 1);
});
test('raw gaps preserve unmeasured, no gaps and lengths without inventing capacity',()=>{
  assert.equal(gapLengths(''),null);assert.deepEqual(gapLengths('0'),[]);assert.deepEqual(gapLengths('4.5, 9.2'),[4.5,9.2]);
  for(const bad of ['-1','4,','0,4','NaN'])assert.throws(()=>gapLengths(bad));
  const d={...draft(),gap_lengths:'4.5,9.2',survey_session_id:'fixture-session',assignment_id:'fixture-assignment'};
  const r=makeObservation(d,face,now);assert.deepEqual(r.gap_lengths_m,[4.5,9.2]);assert.equal(r.assignment_id,'fixture-assignment');assert.equal(r.surveyed_capacity,4);
});
