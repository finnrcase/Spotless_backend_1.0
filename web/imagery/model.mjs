export const VEHICLE_CLASSES = ['curbside_vehicle_candidate','traffic_lane_vehicle','uncertain_vehicle'];
export const MASK_CLASSES = ['visible_curb','tree_occluded','shadow_occluded','other_occluded'];
export function validateRecord(record, tasks) {
  const task = tasks.find(t => t.task_id === record.task_id);
  if (!task || record.image_sha256 !== task.image.sha256) throw Error('Unknown task or image hash mismatch.');
  if (!Array.isArray(record.shapes)) throw Error('Annotation shapes must be a list.');
  const {width,height} = task.image;
  for (const shape of record.shapes) {
    if (shape.confidence != null && (!Number.isFinite(shape.confidence) || shape.confidence < 0 || shape.confidence > 1)) throw Error('Invalid confidence.');
    if (VEHICLE_CLASSES.includes(shape.class)) {
      if (!Array.isArray(shape.box) || shape.box.length !== 4) throw Error('Invalid vehicle rectangle.');
      const [x,y,w,h] = shape.box;
      if (!shape.box.every(Number.isFinite) || x<0 || y<0 || w<=0 || h<=0 || x+w>width || y+h>height) throw Error('Vehicle rectangle outside image.');
    } else if (MASK_CLASSES.includes(shape.class)) {
      if (!Array.isArray(shape.points) || shape.points.length < 3 || shape.points.some(p => p.length!==2 || !p.every(Number.isFinite) || p[0]<0 || p[1]<0 || p[0]>width || p[1]>height)) throw Error('Invalid area polygon.');
    } else throw Error('Unknown annotation class.');
  }
  if (record.reviewed_by_human && !record.annotator?.trim()) throw Error('A reviewed annotation needs a reviewer.');
  if (record.annotation_complete && !record.shapes.some(s => s.class==='visible_curb')) throw Error('Complete review needs a visible curb mask.');
  return record;
}
