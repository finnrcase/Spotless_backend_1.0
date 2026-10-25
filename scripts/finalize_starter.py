"""Merge audited supplemental sources without rebuilding prior models/downloads."""
import json
from pathlib import Path
from datetime import datetime,timezone
from la_parking.http import utcnow
from la_parking.imagery import evaluate_annotations
from la_parking.service.api import app

checks=json.loads(Path('reports/starter/source_checks.json').read_text())
quality=json.loads(Path('reports/starter/quality.json').read_text())
survey=json.loads(Path('reports/starter/survey_audit.json').read_text())
registry_path=Path('config/source_registry.json');registry=json.loads(registry_path.read_text())
extra=[]
request_log=[json.loads(line) for line in Path('data/manifest.jsonl').read_text().splitlines()]
def entry(ident,url,status,notes,**fields):
    times=[r['retrieved_at_utc'] for r in request_log if r.get('url','').startswith(url) and r.get('retrieved_at_utc')]
    extra.append({'id':ident,'owner':fields.pop('owner','City of Los Angeles / source agency'),'verified_url':url,
        'status':status,'category':fields.pop('category','B supply/rules'),'priority':fields.pop('priority',1),
        'retrieved_at_utc':fields.pop('retrieved_at_utc',max(times) if times else None),'notes':notes,'access_requirements':'Anonymous public requests tested; no purchases',
        'cost':'Free requests used','current_legal_coverage_verified':False,**fields})

assetbase='https://services5.arcgis.com/7nsPwEMP38bSkCjy/arcgis/rest/services/Sidewalks_Mapped_Areas/FeatureServer'
for name,number in [('curbs',3),('driveways',4)]:
    d=quality['layers'][name]
    entry('starter_'+name,assetbase+'/'+str(number),'verified/imported historic prior',
        f"{d['features']} source assets, exact ID/page reconciliation; {d['outside_exact_requested_bbox']} outside exact requested box retained with a mask. Historic geometry, never stalls or current legal capacity.",
        useful_fields=d['schema_fields'],geographic_coverage=list(__import__('la_parking.starter',fromlist=['BBOX']).BBOX),
        source_imagery_year=2014,inventory_created_year=2017,retrieved_at_utc=d['retrieval_range_utc'][1],
        license_terms='Public query access; package is not a license grant. Verify City terms before redistribution.')
entry('naip_pinned_2022','https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/17317/info',
    'verified/bounded imagery acquired','Native source pixelSizeX/Y = 0.6 in EPSG:26911 metres, confirmed from raster info. Category 1 primary raster. Date 2022-05-11; time of day unknown. 12 small 360 m tiles for 24-face review, plus included JPEG. No detector metrics measured.',
    owner='USGS / USDA',category='Imagery feasibility',capture_date='2022-05-11',capture_time_utc=None,capture_time_precision='date_only',
    native_pixel_size_m=[.6,.6],license_terms='Public domain NAIP; official USDA catalog rights link verified',
    rights_url='https://catalog.data.gov/dataset/national-agriculture-imagery-program-naip-imagery',time_specific_occupancy_truth=False)
entry('code_the_curb_cds','https://gisserver.dot4la.org/server/rest/services/Sandbox_Environment/Curb_Data_Specification/FeatureServer',
    'public item verified; API unavailable','Public ArcGIS item owned by zackary.d.campos_ladot; LADOT association inferred from its public metadata. Actual endpoint returns API error 500: No Layers. A program page and catalog item do not establish a functioning current public feed.',
    actual_check=checks['code_the_curb_cds_service'],geographic_coverage='Not established from usable records',owner='ArcGIS account zackary.d.campos_ladot; agency association inferred')
entry('code_the_curb_corridor','https://services1.arcgis.com/tp9wqSVX1AitKgjd/arcgis/rest/services/Code_the_Curb_Corridor_Analysis/FeatureServer',
    'verified API; limited DTLA geometry','Query/schema verified. Two records intentionally sampled (exceededTransferLimit=true); not a complete export. Westwood spatial count is zero. April 2024 layer edit, curb lines/BOE links, no complete current sign/permit/time rules or occupancy.',
    sample_complete=False,westwood_query_count=checks['code_the_curb_westwood_count']['data']['count'],
    source_layer_edit_utc=datetime.fromtimestamp(checks['code_the_curb_corridor_layer_schema']['data']['editingInfo']['dataLastEditDate']/1000,timezone.utc).isoformat(),
    geographic_coverage='DTLA SMART corridor study; not citywide or Westwood',license_terms='Public query; redistribution/production rights not independently established')
entry('venice_2021_survey',survey['source_url'],'verified/historic aggregates recovered',
    'Downloaded 206-page November 2021 report. Extracted 48 zone/time-band occupancy cells from PDF page 34, attributed to Fehr & Peers 2019. Values 49–106% preserved. No independent raw repeated block-face table or exact survey timestamps recovered; mixed parking types cannot validate unmetered forecasts.',
    category='A direct parking (historic aggregate)',publication_date='2021-11',table_source_attribution_year=2019,
    source_sha256=survey['pdf_sha256'],exact_observation_timestamps_available=False,full_face_training_ready=False,
    license_terms='Official report accessed for research; source attribution retained. No report redistribution license asserted.',owner='Los Angeles City Planning / Fehr & Peers')
entry('permit_legacy_blank','https://data.lacity.org/d/2ckn-xmjp','unusable legacy export',
    'Metadata has no data columns. Count reports 155, but JSON rows are empty objects and GeoJSON contains 155 null geometries. This is not usable district coverage. Old ladotparking.org permit paths return 404; official LADOT online services/FAQ remain readable.',
    reported_rows=155,usable_geometries=0)
permit=checks['pilot_permit_geometry']
entry('permit_district_geometry',permit['source_url'],'verified/bounded geometry; rules unknown',
    'Six district polygons acquired with exact ID reconciliation in the starter box. PPDNAME and linked plan PDFs are leads; source effective date/currentness and complete curb/stay/vehicle eligibility remain unverified. Nonintersection does not prove unrestricted parking.',
    useful_fields=permit['schema_fields'],features=permit['features'],geographic_coverage='Starter Westwood spatial query',source_geometry_vintage='unverified')
work=checks['pilot_workplace_geography']
entry('pilot_workplace_geography',work['source_url'],'verified/joined predictor context',
    '187 Census 2020 block geometries acquired by bounded query; 148 join to the acquired 2023 LODES workplace records. The remaining 39 stay missing, not zero. Publication/availability date still needs verification before historical as-of use; no backtest features or labels overwritten.',
    category='C demand predictor',geometry_vintage=2020,workplace_vintage=2023,geometry_rows=187,matched_rows=148,occupancy_labels=False,owner='US Census Bureau / LEHD')
Path('config/source_registry_supplement.json').write_text(json.dumps(extra,indent=2),encoding='utf8')
byid={r['id']:r for r in registry['sources']}
for name in ['curbs','driveways']:
    if name in byid:
        byid[name]['source_imagery_year']=2014;byid[name]['inventory_created_year']=2017
        byid[name]['temporal_coverage']='Historic 2017 asset inventory based on 2014 imagery; current maintenance not verified'
        suffix=' Historic supply prior; polygons are not stalls and metadata edits do not prove newer geometry.'
        if suffix not in byid[name]['notes']:byid[name]['notes']+=suffix
for row in extra:byid[row['id']]=row
registry['sources']=list(byid.values());registry['generated_at_utc']=utcnow();registry_path.write_text(json.dumps(registry,indent=2),encoding='utf8')
table=['# Source registry','', 'Machine-readable source details: `config/source_registry.json`. Supplemental checks and their exact request evidence: `reports/starter/source_checks.json`. Original and new raw responses remain in the acquisition manifest.','', '| Source | Status | Priority | Coverage / limitation |','|---|---|---:|---|']
for row in registry['sources']:table.append(f"| [{row['id']}]({row['verified_url']}) | {row['status']} | {row['priority']} | {row.get('notes','').replace('|','/')} |")
Path('docs/source_registry.md').write_text('\n'.join(table)+'\n',encoding='utf8')
manifest=json.loads(Path('reports/imagery/tasks.json').read_text())
Path('reports/imagery/evaluation.json').write_text(json.dumps(evaluate_annotations(manifest,[]),indent=2),encoding='utf8')
Path('reports/service/openapi.json').write_text(json.dumps(app.openapi(),indent=2),encoding='utf8')
lines=['# Supplemental source findings','', '| Source | Verified outcome |','|---|---|']
for row in extra:lines.append(f"| [{row['id']}]({row['verified_url']}) | {row['notes']} |")
lines+=['','Official permit information remains distinct from rule coverage. No district polygon, sign location, roadway patch, model confidence or missing row establishes whole-stay eligibility. Public program descriptions are discovery leads; actual API/schema/sample results are logged separately.','',
    'Acquisition priority remains complete curb rules and independently reviewed occupancy labels, then supported demand predictors. Existing businesses, events, transit and weather snapshots were preserved; ACS remains blocked, historical forecast weather and effective closures are incomplete, and private off-street capacity is unverified. New predictor families require as-of audits and later ablations.','',
    'No paid services, accounts, outreach or public deployment. Additional production imagery, vendor parking estimates and model-training/redistribution rights remain future investigations. Vendor predictions are not independent labels.']
Path('reports/starter/source_findings.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
print('Merged',len(extra),'supplemental sources; wrote unavailable imagery scores and current OpenAPI')
