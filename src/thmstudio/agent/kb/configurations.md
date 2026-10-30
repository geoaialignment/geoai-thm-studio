# What v0.1 computes and how it was checked

Each configuration below is backed by verification cases that compare OpenGeoSys results with exact solutions or
official inputs (see verification/results.json). Other combinations are refused.

- H-2D, H-AX-well, H-3D: groundwater flow (steady and transient). Theis well test within 2 %.
- T-2D, T-3D: heat conduction with sources. Errors below 1 %.
- TH-2D: heat carried by steady groundwater flow. Errors below 1 %.
- HC-2D: solute transport with dispersion, sorption (retardation factor) and decay.
- HC-2D-density: density-driven (buoyant) solute transport in a vertical section, e.g. salt water sinking in
  fingers (the Elder problem); agrees with the official OpenGeoSys benchmark within 2.3 % at 1, 2 and 4 years. On
  that grid both runs dip below zero next to the fingers (to -0.21); the card warns about such values. Use time steps
  of about 3 days (262980 s, as in the verified case); much larger steps may stop the iteration from converging.
- HM-2D: consolidation (plane strain), verified with Terzaghi's column and a Biot coefficient below 1.
- TM-2D: thermal expansion and stress (plane strain), exact for uniform heating.
- THM-AX: point heat source in saturated rock (Booker and Savvidou), errors near 1 %.
- THM-AX-repository: canister, bentonite buffer and rock (demonstration): energy balance and mesh convergence checked,
  homogeneous limit equal to THM-AX.

Not included: reactive chemistry, two-phase or unsaturated flow, swelling, fractures, freezing, plasticity, gravity
with mechanics, 3D mechanics, large or site-specific models. These are commercial services of GeoAI Alignment, Inc.
Inside the configurations, inputs no case covers are refused: solute inflow conditions, hydraulic storage with heat
or solute transport, water inflow with heat transport or with mechanics.
