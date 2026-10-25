"""Complete bounded pipeline. Network sources may be blocked; inspect reports."""
import subprocess
import sys
from la_parking.acquire import run
from la_parking.build import run as build
from la_parking.cli import main

run(['2025_09','2026_08'])
for script in ['supplement.py','activity.py','registry.py']:
    subprocess.run([sys.executable,'scripts/'+script],check=True)
build()
subprocess.run([sys.executable,'scripts/finalize.py'],check=True)
from la_parking.collector import build_collector
from la_parking.evaluation import write_readiness
build_collector()
write_readiness()
