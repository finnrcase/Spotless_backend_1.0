# Historic imagery feasibility

24 faces, 12 physical blocks, 12 bounded 360 m tiles; historic visible-vehicle feasibility only, not legal vacancy or time-specific forecasting

Status: **annotation_workflow_ready_detection_blocked**.

No configured overhead-vehicle detector, weights or compatible runtime; no independently reviewed annotations. No detections fabricated.

Native resolution is confirmed from raster 17317/info: pixelSizeX=0.6, pixelSizeY=0.6, NAD83 / UTM 11N (metres). The service-wide 0.3 value is not used. The source is a four-band primary raster named m_3411861_nw_11_060_20220511. Capture metadata is date-only; midnight is not a flight time.

The supplied 500×560 JPEG was inspected and retained. Its actual repeat-export extent differs from the requested box because the server adjusted aspect ratio. That registration remains an inference for the original JPEG. New 600×600 exports save the returned projected extent; rendering at 0.6 m does not improve source information.

Open annotator.html for real images, approximate curb overlays, explicit visible/occluded masks, traffic-lane/curbside/uncertain vehicle boxes, local saving and JSON export/import. No unannotated area is marked visible or empty. Single-image curbside position cannot prove a vehicle is parked or legally eligible.

Count MAE, precision and recall are unavailable. Run imagery-evaluate after independent human review and actual detector predictions. Evaluation is limited to reviewed visible curb area, excludes occlusion, and never turns these old images into arrival-time or legally suitable-space labels. The included failure-example overlay is explicitly an unverified visual review.
