"""One real tract request; output never contains a credential or response body."""
import json
from la_parking.census_auth import verify
print(json.dumps(verify(),indent=2))
