import test from 'node:test';import assert from 'node:assert/strict';
import {validateRecord} from '../web/imagery/model.mjs';
const tasks=[{task_id:'fixture',image:{sha256:'fixture-hash',width:100,height:100}}];
test('annotation references require the correct image and explicit visible masks',()=>{
  const base={task_id:'fixture',image_sha256:'fixture-hash',shapes:[],annotator:'',reviewed_by_human:false,annotation_complete:false};
  assert.equal(validateRecord(base,tasks),base);
  assert.throws(()=>validateRecord({...base,image_sha256:'wrong'},tasks));
  assert.throws(()=>validateRecord({...base,annotation_complete:true},tasks));
  assert.throws(()=>validateRecord({...base,reviewed_by_human:true},tasks));
  assert.throws(()=>validateRecord({...base,shapes:[{class:'curbside_vehicle_candidate',box:[90,90,20,20]}]},tasks));
  const r={...base,annotator:'fixture-human',reviewed_by_human:true,annotation_complete:true,shapes:[{class:'visible_curb',points:[[0,0],[100,0],[100,100]]}]};
  assert.equal(validateRecord(r,tasks),r);
});
