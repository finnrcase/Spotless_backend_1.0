"""Verified service roots; discovery metadata remains the schema authority."""
NAV = 'https://maps.lacity.org/arcgis/rest/services/Mapping/NavigateLA/MapServer'
STREETS = 'https://portald1.lalightsaws.lacity.org/server/rest/services/LABureauOfStreetLighting032923/FeatureServer/0'
SODA = 'https://data.lacity.org'
DATASETS = {'meters':'s49e-q6j2', 'occupancy':'e7h6-4a3e', 'history':'cj8s-ivry',
            'sweeping':'krk7-ayq2', 'permits':'s3st-6nwi', 'signs':'jp2s-nfz4', 'business':'6rrh-rzua'}
# Explicit configurable pilot, not a neighborhood/jurisdiction polygon.
PILOT = (-118.465, 34.045, -118.425, 34.080)
