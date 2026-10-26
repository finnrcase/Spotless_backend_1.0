"""Bounded spatial-transfer development; reserved outcomes stay unopened."""
import argparse
p=argparse.ArgumentParser();p.add_argument('stage',choices=['acquire','run','check']);a=p.parse_args()
if a.stage=='acquire':
    from la_parking.transfer_context import acquire
    acquire()
elif a.stage=='run':
    from la_parking.spatial_experiment import run
    run()
elif a.stage=='check':
    from la_parking.spatial_experiment import check
    check()
else:
    raise SystemExit('Stage not yet implemented')
