"""Versioned performance experiments; legacy application artifacts stay intact."""
import argparse

p=argparse.ArgumentParser()
p.add_argument('stage',choices=['audit','features','acquire','predictors','run','check'])
p.add_argument('--horizons',type=int,nargs='+',choices=[0,15,30,60,120])
p.add_argument('--resume',action='store_true')
p.add_argument('--report-directory')
a=p.parse_args()
if a.stage=='audit':
    from la_parking.sensor_audit import audit
    audit()
elif a.stage=='features':
    from la_parking.temporal_features import build_legacy_features
    build_legacy_features()
elif a.stage=='acquire':
    from la_parking.temporal_acquisition import acquire
    acquire()
elif a.stage=='predictors':
    from la_parking.temporal_predictors import acquire_predictors
    acquire_predictors()
elif a.stage=='run':
    from la_parking.temporal_experiment import run
    run(horizons=a.horizons,resume=a.resume,report_directory=a.report_directory)
elif a.stage=='check':
    import runpy
    from pathlib import Path
    runpy.run_path(str(Path(__file__).with_name('check_temporal_results.py')))
else:
    raise SystemExit('Stage implementation is not yet available')
