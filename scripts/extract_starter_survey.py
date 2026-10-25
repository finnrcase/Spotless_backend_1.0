"""Recover auditable historic aggregate tables, never full-face training labels."""
import json
from pathlib import Path
import re
import pandas as pd
from pypdf import PdfReader

source=json.loads(Path('reports/starter/source_checks.json').read_text())['venice_parking_survey']
reader=PdfReader(Path('data')/source['request']['path'])
stage=Path('data/staged/starter/survey_text');stage.mkdir(parents=True,exist_ok=True)
for i,page in enumerate(reader.pages):(stage/f'page_{i+1:03d}.txt').write_text(page.extract_text() or '',encoding='utf8')
text=(stage/'page_034.txt').read_text(encoding='utf8');rows=[]
bands=['08:00-10:00','10:00-12:00','12:00-14:00','14:00-16:00','16:00-18:00','18:00-20:00']
for line in text.splitlines():
    match=re.match(r'^(\d)\s+(.+?)\s+((?:\d+%\s*){6})$',line.strip())
    if not match:continue
    for band,value in zip(bands,re.findall(r'(\d+)%',match[3])):
        rows.append({'source_table':9,'pdf_page':34,'zone_number':int(match[1]),'zone_name':match[2],
            'reported_local_time_band':band,'reported_occupancy_percent':int(value),'reported_season_daytype':'non-summer weekend',
            'publication_date':'2021-11','table_source_attribution_year':2019,'exact_survey_datetime_utc':None,'block_face_id':None,
            'parking_type':'mixed_or_not_separately_identified','evidence_class':'historic_report_zone_aggregate',
            'capacity_basis':'Estimated unmarked supply uses 20 feet per position; report permits occupancy above 100 percent',
            'eligible_for_full_face_time_specific_training':False,'source_url':source['url'],'source_sha256':source['request']['sha256']})
if len(rows)!=48:raise ValueError(f'Table 9 extraction expected 48 numeric zone/time cells, got {len(rows)}; inspect layout')
out=Path('data/staged/starter/venice_table9_aggregates.csv');pd.DataFrame(rows).to_csv(out,index=False)
report={'pdf_pages':len(reader.pages),'pdf_sha256':source['request']['sha256'],'publication_date':'2021-11','table9_rows_extracted':len(rows),
    'source_pdf_page':34,'occupancy_percent_range':[min(r['reported_occupancy_percent'] for r in rows),max(r['reported_occupancy_percent'] for r in rows)],
    'embedded_attachment_names':list(reader.attachments),
    'full_face_observations_recovered':0,'exact_survey_timestamps_recovered':False,
    'status':'historic_aggregate_evidence_recovered_not_training_ready',
    'limitations':['Zone aggregates mix metered and unmetered supply; they cannot validate separate unmetered forecasts.',
        'Unmarked capacity uses an assumed 20-foot position; values above 100 percent are preserved, not clipped.',
        'Maps/aggregate tables are not machine-readable repeated block-face counts. No raw independently timestamped block-face table recovered.',
        'November 2021 publication and source-attribution year 2019 do not establish exact observation times or current conditions.'],
    'source_url':source['url'],'csv_path':str(out)}
Path('reports/starter/survey_audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report,indent=2))
