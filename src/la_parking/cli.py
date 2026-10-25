import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description='Los Angeles parking data foundation')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('acquire'); a.add_argument('--months',nargs='*',default=['2025_09','2026_08']); a.add_argument('--refresh',action='store_true')
    sub.add_parser('build'); sub.add_parser('schemas')
    o=sub.add_parser('observations'); o.add_argument('jsonl')
    c=sub.add_parser('collector'); c.add_argument('--output',default='reports/collector.html')
    e=sub.add_parser('evaluate'); e.add_argument('--train',required=True); e.add_argument('--test',required=True)
    e.add_argument('--axis',choices=['future_time','unseen_block'],required=True); e.add_argument('--output',default='reports/evaluation.json'); e.add_argument('--embargo-minutes',type=int,default=60)
    sub.add_parser('prepare-models');sub.add_parser('train');sub.add_parser('survey-plan')
    z=sub.add_parser('integrate-starter');z.add_argument('--path',default='data/reference/parking_data_starter')
    z=sub.add_parser('imagery-prepare');z.add_argument('--download',action='store_true')
    z=sub.add_parser('imagery-evaluate');z.add_argument('--annotations',required=True);z.add_argument('--predictions');z.add_argument('--output',default='reports/imagery/evaluation.json')
    sub.add_parser('field-route')
    s=sub.add_parser('serve');s.add_argument('--port',type=int,default=8765)
    u=sub.add_parser('compare-unmetered');u.add_argument('--table');u.add_argument('--manifest');u.add_argument('--output',default='reports/unmetered')
    u=sub.add_parser('prepare-unmetered');u.add_argument('--reviews',required=True);u.add_argument('--features',required=True);u.add_argument('--output',default='data/modeling/unmetered_reviewed.parquet')
    f=sub.add_parser('forecast');f.add_argument('--face',required=True);f.add_argument('--issued',required=True);f.add_argument('--arrival',required=True);f.add_argument('--stay',type=int,default=60);f.add_argument('--permit',default=None);f.add_argument('--experimental-transfer',action='store_true');f.add_argument('--output',default=None)
    a=p.parse_args()
    if a.command=='acquire':
        from .acquire import run
        run(a.months,a.refresh)
    elif a.command=='build':
        from .build import run
        run()
    elif a.command=='schemas':
        from .contracts import MODELS
        from .forecasting import ForecastArtifact
        Path('schemas').mkdir(exist_ok=True)
        for cls in MODELS+[ForecastArtifact]: Path(f'schemas/{cls.__name__}.schema.json').write_text(json.dumps(cls.model_json_schema(),indent=2),encoding='utf8')
    elif a.command=='collector':
        from .collector import build_collector
        print(json.dumps(build_collector(a.output),indent=2))
    elif a.command=='evaluate':
        from .evaluation import run_evaluation
        print(json.dumps(run_evaluation(a.train,a.test,a.axis,a.output,a.embargo_minutes),indent=2))
    elif a.command=='prepare-models':
        from .labels import build_labels
        from .model_features import build_design
        build_labels();build_design()
    elif a.command=='train':
        from .modeling import train_models
        train_models()
    elif a.command=='survey-plan':
        from .survey_design import make_survey_plan
        print(json.dumps(make_survey_plan(),indent=2))
    elif a.command=='forecast':
        from .forecasting import request_forecast
        r=request_forecast(a.face,a.issued,a.arrival,a.stay,{'permit_class':a.permit,'vehicle_class':'standard_passenger'},a.experimental_transfer)
        text=r.model_dump_json(indent=2)
        if a.output: Path(a.output).write_text(text,encoding='utf8')
        print(text)
    elif a.command=='serve':
        import uvicorn
        uvicorn.run('la_parking.service.api:app',host='127.0.0.1',port=a.port,workers=1)
    elif a.command=='compare-unmetered':
        from .unmetered import run
        print(json.dumps(run(a.table,a.manifest,a.output),indent=2))
    elif a.command=='integrate-starter':
        from .starter import integrate
        r=integrate(a.path);print(json.dumps({'files_hash_verified':r['files_hash_verified'],'downloads_rerun':r['downloads_rerun'],'quality_report':'reports/starter/quality.json'},indent=2))
    elif a.command=='imagery-prepare':
        from .imagery import prepare
        r=prepare(a.download);print(json.dumps({'tasks':len(r['tasks']),'status':r['status'],'count_mae':r['count_mae']},indent=2))
    elif a.command=='imagery-evaluate':
        from .imagery import evaluate_files
        print(json.dumps(evaluate_files(a.annotations,a.predictions,a.output),indent=2))
    elif a.command=='field-route':
        from .field_route import build
        r=build();print(json.dumps({'faces':r['face_count'],'planned_visits':r['total_observations_planned'],'collected':r['observations_actually_collected']},indent=2))
    elif a.command=='prepare-unmetered':
        from .unmetered import prepare
        print(json.dumps(prepare(a.reviews,a.features,a.output),indent=2))
    else:
        from .observations import ingest
        print(json.dumps(ingest(a.jsonl),indent=2))
