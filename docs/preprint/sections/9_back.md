# Appendix A: Settings and Checks

*Table A1. Settings and checks of version 0.1.0. ℓ is the heat-spread length of Eq. (1).*

| Item | Setting |
|---------------------|----------------------------------------------------------------|
| Software | OpenGeoSys 6.5.8 (Python wheel); Gmsh 4.15.2, run as a separate program; OpenAI Agents SDK 0.24.0; Model Context Protocol SDK 2.3.0; Python 3.12 |
| Verification tolerances | per case, written before the comparison: typically maximum-norm and relative l2 errors of 1–3 % for transient solutions and 10⁻⁶ where the solution is exact for the element; every case is listed with its tolerance in docs/VERIFICATION.md |
| Mesh checks | inverted elements refused; angles below 30° (quadrilaterals) or 15° (triangles) and aspect ratios above 20:1 give warnings; region areas compared with the geometry; at most 15,000 elements for coupled mechanics, 60,000 in 2D and 120,000 in 3D otherwise |
| Resolution rules | cell Péclet number vh/(2D) above 1 (v pore velocity, h largest element size, D dispersion coefficient), or its thermal equivalent: warning; front moving more than one element per time step (vΔt/h > 1, with Δt the largest time step): warning; in transient heat conduction and heat transport (T, TH), element at a fixed-temperature boundary larger than ℓ/2 and (for materials given with density and specific heat) heat spreading beyond half the model size by the end time: warnings; element at a point heat source larger than ℓ/8: refused, ℓ/12 suggested |
| Named comparisons | no thermal expansion of the solid; no thermal expansion of the water; no Biot coupling; no sorption (retardation 1); no decay; half element size (sizes halved, divisions doubled) |
| Card values | value at a point or probe (interpolated within the element); change since the start; maximum, minimum or mean of the nodal values over the model or of 201 samples along a line; largest absolute difference from a named comparison |
| Engine self-test | steady conduction across a 2 m strip from 300 K to 290 K on a triangulated mesh; passes if the largest error is below 10⁻⁶ K; repeated once per OpenGeoSys version and platform |
| Default materials | representative values with sources in src/thmstudio/agent/kb/materials.json |
| Scenarios and scoring | tests/l6/scenarios.json (requests and expected outcomes), tests/l6/run_l6.py (judge), tests/final_api/run_final.py (API check), results/ and runs/ (records) |

# Open Research

GeoAI-THM Studio 0.1.0, with its verification cases and record, the scenarios, the scripts that rescore the stand-in runs, recompute the answers and run the source-element sweep, and the result files and run records behind every number in this paper (`results/`, `runs/` and `tests/final_api/ledger.json`, with local paths removed), is archived at Zenodo (Park et al., 2026; https://doi.org/{{doi}}) and available at https://github.com/geoaialignment/geoai-thm-studio. The code is licensed under the PolyForm Noncommercial License 1.0.0 and the documentation under CC BY-NC 4.0; commercial use is not permitted. OpenGeoSys 6.5.8 is available under the BSD 3-Clause license (Bilke et al., 2026), and the official inputs and outputs used by four verification cases (the three official-input baselines and the Elder comparison) are part of its test data.

# Acknowledgments

This work was funded by GeoAI Alignment, Inc. The authors declare there are no conflicts of interest for this manuscript; GeoAI Alignment, Inc. offers commercial modeling services outside the scope of the free release. Claude (Anthropic) was used to write and test the code and to draft this text, and gpt-6-astra (OpenAI), Grok 4.7 (xAI) and gemini-4-argon (Google) reviewed the code and the manuscript; the authors checked the results and are responsible for the content.
