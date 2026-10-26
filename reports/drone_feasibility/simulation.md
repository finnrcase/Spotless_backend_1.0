# Offline drone feasibility — simulated only

All route/camera/coverage/revisit/productivity values below are **simulated assumptions, not observed flights, detections, legal approvals or forecast gains**.

10/16 planned development faces; 3 simulated sorties; cycle 45.94 min; assumed operator time 80.94 min.
Raw service frames: 161; unique face-visit units: 10. Frames are not independent labels.
Expected usable count units/operator hour under the unmeasured full-visibility assumption: 2.22.

This command never opens an aircraft transport. A separately configured PX4/Gazebo SITL lab is required for physics/MAVLink execution; a WSL launcher alone does not establish a usable Linux runtime. See verification.json for the local runtime audit.

MAVSDK mission data objects validated: True. No network connections, aircraft controls or real flights occurred. See docs/drone_feasibility.md for pins, assumptions, matched comparison and qualified-pilot approval questions.
