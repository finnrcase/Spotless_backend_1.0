"""Reproduce analytical image overlays; no inferred detections or scored labels."""
import base64
import json
import os
from pathlib import Path
os.environ['MPLCONFIGDIR']=str(Path('.matplotlib').resolve())
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image

manifest=json.loads(Path('reports/imagery/tasks.json').read_text())
fig,axes=plt.subplots(3,4,figsize=(16,12))
for ax,tile in zip(axes.flat,manifest['tiles']):
    ax.imshow(Image.open(tile['path']));tasks=[t for t in manifest['tasks'] if t['image']['tile_id']==tile['tile_id']]
    for task in tasks:
        for points in task['corridor']:
            xs,ys=zip(*points);ax.plot(xs,ys,lw=.9,color='#ffdf67')
    ax.set_title(tasks[0]['street_name']+'\n'+tasks[0]['context_stratum'],fontsize=8);ax.axis('off')
fig.suptitle('Real NAIP | 2022-05-11, date only | native 0.6 m\n24 faces / 12 blocks. Yellow: approximate curb corridors, not detections or legal parking.',fontsize=13)
fig.tight_layout(rect=[0,0,1,.94]);fig.savefig('reports/imagery/contact_sheet.png',dpi=130);plt.close(fig)
image=manifest['included_image'];uri='data:image/jpeg;base64,'+base64.b64encode(Path(image['path']).read_bytes()).decode()
examples=[{'class':'tree_occlusion_example','points':[[185,175],[250,175],[270,205],[255,235],[190,225]],'note':'Tree canopy obscures potential curb/road evidence; visibility is unknown.'},
    {'class':'shadow_occlusion_example','points':[[350,250],[425,250],[400,375],[345,375]],'note':'Canopy/shadow region: do not interpret dark pixels as zero vehicles.'},
    {'class':'visible_road_patch_example','points':[[375,100],[415,105],[407,160],[372,170]],'note':'Visible road patch: travel-lane location and parking eligibility remain unverified.'}]
review={'review_status':'assistant_visual_review_unverified','image_sha256':image['sha256'],'reference_ground_truth':False,
    'annotations':examples,'curbside_vehicle_count':None,'capture_time_utc':None}
Path('reports/imagery/unverified_visual_examples.json').write_text(json.dumps(review,indent=2),encoding='utf8')
parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Historic image failures</title><body style="font:16px system-ui;max-width:800px;margin:20px auto;padding:12px"><h1>Unverified visual failure examples</h1><p>Assistant visual review, not independent human ground truth. May 11, 2022, date only. These polygons are excluded from scored labels. No vehicle detections or legal vacancies are asserted.</p>',f'<svg viewBox="0 0 500 560" style="width:100%;max-width:500px"><image href="{uri}" width="500" height="560"/>']
for i,entry in enumerate(examples):
    color=['#c5ff51','#ff69d1','#29d9ff'][i];points=' '.join(f'{x},{y}' for x,y in entry['points'])
    parts.append(f'<polygon points="{points}" fill="{color}" fill-opacity=".18" stroke="{color}" stroke-width="2"/>')
parts+=['</svg><ol>']+['<li>'+e['note']+'</li>' for e in examples]+['</ol><p>Single-frame vehicle position does not establish motion or legal parking. Approximate curb alignment and native resolution add uncertainty. Review actual images before drawing reference boxes.</p></body></html>']
Path('reports/imagery/failure_examples.html').write_text(''.join(parts),encoding='utf8')
print('Saved contact sheet and explicitly unverified failure overlays')
