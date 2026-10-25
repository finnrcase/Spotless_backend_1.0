# Starter integration audit

Verified 96 packaged response hashes; no source downloads rerun.

| Asset layer | Complete features | Pages | Already in larger pilot | Invalid geometries | Outside exact box |
|---|---:|---:|---:|---:|---:|
| curbs | 6402 | 65 | 6390 | 0 | 84 |
| driveways | 1803 | 19 | 1798 | 0 | 19 |

Independent source ID lists, counts, page contents and combined exports reconcile. Capped sample files are not used as complete data. Near-boundary assets outside the exact requested box are retained with a mask; a projected-envelope query is a possible cause, not established.

Curb and driveway polygons are historic physical assets: 2017 inventory based on 2014 imagery. Metadata edits and retrieval dates do not refresh geometry. Invalid geometry is retained and excluded from spatial links. Parking capacity and current legal status remain unknown.

Existing citywide streets, block faces, model artifacts and larger pilot tables were preserved. Asset-to-face links are uncertain physical associations, not eligibility labels. Full schemas, coordinate bounds and provenance are in quality.json.
