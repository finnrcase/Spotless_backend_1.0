import argparse
p=argparse.ArgumentParser();p.add_argument('stage',choices=['census','occupancy','locations','evaluate','check']);a=p.parse_args()
if a.stage=='census':
    from la_parking.census_coverage import acquire
    acquire()
elif a.stage=='occupancy':
    from la_parking.regional_coverage import acquire
    acquire()
elif a.stage=='evaluate':
    from la_parking.coverage_experiment import run
    run()
elif a.stage=='locations':
    from la_parking.regional_coverage import audit_existing
    audit_existing()
elif a.stage=='check':
    from la_parking.coverage_report import check
    check()
else:raise SystemExit('Stage not yet implemented')
