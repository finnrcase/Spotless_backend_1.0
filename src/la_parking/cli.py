import argparse
import json
from pathlib import Path


def main():
    from .environment import load_local_env
    load_local_env()
    p=argparse.ArgumentParser(description='Los Angeles parking data foundation')
    sub=p.add_subparsers(dest='command',required=True)
    sig=sub.add_parser('acquire-signals');sig.add_argument('--refresh',action='store_true')
    sig=sub.add_parser('signal-features');sig.add_argument('--requests',required=True);sig.add_argument('--output',default='data/signals/features.jsonl')
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
    sub.add_parser('product-readiness')
    q=sub.add_parser('evaluate-product');q.add_argument('--manifest',required=True);q.add_argument('--observations',required=True);q.add_argument('--reviews',required=True);q.add_argument('--forecasts',required=True);q.add_argument('--decisions');q.add_argument('--output',default='reports/product/evaluation.json')
    q=sub.add_parser('product-pilot');q.add_argument('action',choices=['prepare','freeze','intake','evaluate']);q.add_argument('--input');q.add_argument('--artifacts',nargs='*');q.add_argument('--freeze-file',default='data/product/pilot_freeze.json');q.add_argument('--output');q.add_argument('--observations');q.add_argument('--reviews')
    s=sub.add_parser('serve');s.add_argument('--port',type=int,default=8765)
    u=sub.add_parser('compare-unmetered');u.add_argument('--table');u.add_argument('--manifest');u.add_argument('--output',default='reports/unmetered')
    u=sub.add_parser('prepare-unmetered');u.add_argument('--reviews',required=True);u.add_argument('--features',required=True);u.add_argument('--output',default='data/modeling/unmetered_reviewed.parquet')
    f=sub.add_parser('forecast');f.add_argument('--face',required=True);f.add_argument('--issued',required=True);f.add_argument('--arrival',required=True);f.add_argument('--stay',type=int,default=60);f.add_argument('--permit',default=None);f.add_argument('--experimental-transfer',action='store_true');f.add_argument('--output',default=None)
    a=p.parse_args()
    if a.command=='acquire-signals':
        from .signals import acquire_signals
        print(json.dumps(acquire_signals(refresh=a.refresh),indent=2))
    elif a.command=='signal-features':
        from .signals import build_signal_features
        print(json.dumps(build_signal_features(a.requests,a.output),indent=2))
    elif a.command=='acquire':
        from .acquire import run
        run(a.months,a.refresh)
    elif a.command=='build':
        from .build import run
        run()
    elif a.command=='schemas':
        from .contracts import MODELS
        from .forecasting import ForecastArtifact
        Path('schemas').mkdir(exist_ok=True)
        from .product_contracts import PRODUCT_MODELS
        for cls in MODELS+[ForecastArtifact]+PRODUCT_MODELS: Path(f'schemas/{cls.__name__}.schema.json').write_text(json.dumps(cls.model_json_schema(),indent=2),encoding='utf8')
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
    elif a.command=='product-readiness':
        from .product_pilot import readiness
        print(json.dumps(readiness(),indent=2))
    elif a.command=='evaluate-product':
        from .product_evaluation import run
        print(json.dumps(run(a.manifest,a.observations,a.reviews,a.forecasts,a.decisions,a.output),indent=2))
    elif a.command=='product-pilot':
        from .product_pilot import prepare,freeze,intake,evaluate_trials
        if a.action=='prepare':r=prepare(a.output or 'reports/product')
        elif a.action=='freeze':r=freeze(a.artifacts,a.freeze_file)
        elif not a.input:raise ValueError('--input is required for trial intake/evaluation')
        elif a.action=='intake':r=intake(a.input,a.output or 'data/product/trials.jsonl')
        else:r=evaluate_trials(a.input,a.freeze_file,a.output or 'reports/product/trials_evaluation.json',a.observations,a.reviews)
        print(json.dumps(r,indent=2))
    elif a.command=='prepare-unmetered':
        from .unmetered import prepare
        print(json.dumps(prepare(a.reviews,a.features,a.output),indent=2))
    else:
        from .observations import ingest
        print(json.dumps(ingest(a.jsonl),indent=2))
