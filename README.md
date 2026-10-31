# GeoAI-THM Studio

**Subsurface heat, groundwater flow, deformation and solute transport, modelled from a plain-language request and
computed with OpenGeoSys.**

GeoAI-THM Studio is an agent that builds a model the way an engineer does in a multiphysics GUI: geometry, physics,
materials, boundary conditions, mesh, study, computation, results. You describe the problem in English or Korean; the
agent asks at most a few questions, assembles the model through its tools, checks it, runs
[OpenGeoSys](https://www.opengeosys.org) 6.5.8, and reports numbers that the program computed, with the verification
behind them.

Version 0.1 (preview). Free for noncommercial use. Built on OpenGeoSys. By Eungyu Park, Taeyu Kim and Jangwon Park,
GeoAI Alignment, Inc. [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23806977.svg)](https://doi.org/10.5281/zenodo.23806977)

## What it computes

Only configurations that have been verified are computed. Anything else is refused with a pointer to GeoAI Alignment.

| Configuration | Physics | Shape | Verified by |
|---|---|---|---|
| H-2D, H-AX-well, H-3D | groundwater flow (steady, transient) | 2D section or plan, radial well, 3D box | layered flow, Theis well test, hydrostatics |
| T-2D, T-3D | heat conduction with sources | 2D, circular body, 3D box | erfc solution, heated slab, radial conduction |
| TH-2D | heat carried by groundwater flow | 2D | advection–conduction solution |
| HC-2D | solute transport: advection, dispersion, sorption, decay | 2D | Ogata–Banks, radionuclide migration in clay |
| HC-2D-density | density-driven (buoyant) transport, e.g. salt water sinking in fingers | 2D vertical section | official OpenGeoSys Elder benchmark |
| HM-2D | consolidation (plane strain) | 2D | Terzaghi; Biot coefficient below 1 |
| TM-2D | thermal expansion and stress (plane strain) | 2D | exact thermoelastic solutions |
| THM-AX | point heat source in saturated rock | axisymmetric | Booker and Savvidou (1985) |
| THM-AX-repository | heated canister in a bentonite-filled hole in rock (demonstration) | axisymmetric | energy balance, mesh convergence, homogeneous limit |

Each case compares OpenGeoSys results with an exact solution or an official OpenGeoSys input, with tolerances fixed in
advance; see [docs/VERIFICATION.md](docs/VERIFICATION.md). A configuration is computed only when all its cases have
passed with the installed version of GeoAI-THM Studio and OpenGeoSys. Of the 27 cases, 21 agree within 1 % and all within
2.5 %; halving element size and time step together reduced the transient errors to 0.27–0.63 of their values (median
0.50; `results/verification_halving.json`), as first-order time stepping should.

**Not included:** reactive chemistry, two-phase or unsaturated flow, bentonite swelling, fractures, freezing,
plasticity, gravity with mechanics, 3D mechanics, and large or site-specific models. Within the configurations, inputs
no case covers are refused: prescribed solute flux or rate conditions, hydraulic storage with heat or solute
transport, prescribed water inflow with heat transport or with mechanics (transverse dispersion runs with a warning). These are commercial services of
GeoAI Alignment, Inc. (https://geoaialign.ai).

## How it works

The language model never writes OpenGeoSys input and never computes numbers. It changes a typed model tree through
about twenty tools; a translator turns the tree into OpenGeoSys input.

- **A state machine orders the work.** Only the tools that fit the current step are offered (four to six at a time).
  A call that does not fit returns the state and the next step instead of failing. `run` requires a passed
  `check_model` for the current version of the model; any edit invalidates the check.
- **The mesh is a full step.** Element size, grading towards boundaries and interfaces, local refinement, element
  shape, quality checks (angles, aspect ratio, Jacobians, region areas against the geometry, OpenGeoSys checkMesh),
  resolution advice (cell Péclet number, diffusion length) and a mesh-convergence comparison.
- **Comparisons are named.** `compare` runs the same model with one coupling switched off (thermal expansion of the
  solid or the water, Biot coupling, sorption, decay) or with half the element size, and reports the difference.
- **Numbers come from an answer card.** `answer_card` computes the values to report, with run ID, model name,
  location, time and the verification status. An output guardrail blocks any number in the answer that is not on the
  card, in the model inputs or in the user's own words (rounded as written; the sign is not compared, so "drops
  3.06 m" matches a change of −3.06 m). A number written with a unit must come from a source of that kind: a
  temperature from a temperature, not from a density. Numbers that tools report in passing may back counts, times,
  lengths and percentages, never a temperature, pressure, velocity or flow rate. The model is then asked to rewrite its answer. The card also warns when a
  temperature or concentration leaves the range set by its initial and fixed values, a sign of a mesh too coarse for
  the flow.
- **Results page.** Each answer comes with an HTML page: the card, figures, an offline 3D view, the verification
  status and every unit conversion the translator made.

## Install

Supported: macOS 15 or later on Apple Silicon, Python 3.12. Experimental: Linux x86_64, tested so far only under
emulation (see below). Windows is not supported.

The software is free for noncommercial use, but the chat agent calls the OpenAI API with your own key, and OpenAI
bills those calls to your account; when the tools are used from another MCP client, that client's own model terms apply.

```bash
pip install "geoai-thm-studio[mesh-gmsh] @ git+https://github.com/geoaialignment/geoai-thm-studio@v0.1.0"
```

The `mesh-gmsh` extra installs gmsh for circular inclusions and triangle meshes; gmsh runs as a separate program.
On Linux, gmsh needs a few system libraries that minimal images lack (Debian or Ubuntu):

```bash
sudo apt-get install libgl1 libglu1-mesa libgomp1 libxcursor1 libxft2 libxinerama1
```

Before the first triangle mesh is computed, the installed engine solves a small test problem with a known answer.
OpenGeoSys 6.5.8 for Linux x86_64 failed this test when we ran it under emulation on Apple Silicon, while the same
input was exact on macOS and on rectangular meshes; native Linux has not been tested yet. Where the test fails,
triangle meshes are refused and rectangular meshes still work.

## Use

Chat (needs an OpenAI API key in the environment, `OPENAI_API_KEY`):

```bash
thmstudio chat --model gpt-6.1-terra
```

From an MCP client such as Claude Desktop, add the server:

```json
{"mcpServers": {"thm-studio": {"command": "thmstudio", "args": ["mcp"]}}}
```

Other commands: `thmstudio examples` lists the thirteen starting examples; `thmstudio verify` repeats the verification
on your machine.

## Tested with small models

The claim behind the project is that a careful harness lets a small model carry a modelling task through. Development
and testing used no OpenAI API.

- **Stand-in runs.** Claude Haiku 5.5, standing in for a small model, worked 21 scenarios through the MCP server.
  Scored with the released guardrail and judge, 20 passed (the last of five development rounds; the harness was
  improved between rounds on these scenarios). In s20, asked for steady solute transport, which is not
  supported, the model ran the transient model for a year and called the filled column steady instead of saying the
  request could not be met. Rescoring for this release also found two faults of the guardrail, now fixed: numbers
  written directly before Korean characters in the request ("10도") were not read as the user's numbers, and step
  counts on the card could not be quoted.
- **Final check with the OpenAI API**, run once with a USD 10 cap. Eight scenarios ran on gpt-6-luna and on
  gpt-6.1-terra, and all 16 runs produced a card and quoted only card numbers. The check cost USD 1.18 as metered,
  plus USD 0.40 booked for two attempts that crashed before their cost was counted, USD 1.58 in all. In s01 both
  models' first answers were sent back by the guardrail fault described above, and both rewrote them.
- **What the check found.** Rerunning each answer on the example's own mesh showed that s11 was wrong for both models:
  each had coarsened the mesh at (and, for gpt-6-luna, around) a point heat source, and the pore-pressure rise came out
  at -0.507 MPa (gpt-6-luna) and 0.635 MPa (gpt-6.1-terra), against 0.967 MPa from the exact solution. gpt-6.1-terra had
  run the half-element-size comparison, seen a change of 0.257 MPa and called the value mesh-sensitive, but still
  reported it. A first rule refused point-source elements larger than a quarter of the distance heat spreads by the
  first output; rerun with it, gpt-6.1-terra had its mesh refused, refined it and reported 0.971 MPa. A sweep of the
  source element size (`results/point_source_sweep.json`) then showed that a quarter still leaves errors of about 6 %,
  so the released `check_model` refuses elements larger than an eighth, which keeps the example within the 3 %
  tolerance of its verification case. The models changed the example mesh in 9 of 14 computed runs; in the other
  scenarios this did not matter, and the recomputed values agree within 2.3 % (20 of 23 within 0.2 %). The check
  also found that `thmstudio chat` failed on every second turn (an event-loop error), which is fixed.
- **Linux** was tested only under emulation (Docker on Apple Silicon): installation, the quadrilateral examples and
  the verification cases pass there; triangle meshes did not (see Install).

The conversations are in [docs/EXAMPLE_CONVERSATION.md](docs/EXAMPLE_CONVERSATION.md).

## Documents and citation

- Technical note: [English](docs/technical_note/GeoAI-THM-Studio-v0.1.0_technical_note_en.pdf),
  [Korean](docs/technical_note/GeoAI-THM-Studio-v0.1.0_technical_note_ko.pdf)
- Preprint (prepared for the ESS Open Archive): [PDF](docs/preprint/GeoAI-THM-Studio_preprint.pdf)
- Verification tables: [docs/VERIFICATION.md](docs/VERIFICATION.md)

Cite as: Park, E., Kim, T., & Park, J. (2026). *GeoAI-THM Studio* (Version 0.1.0) [Software]. GeoAI Alignment, Inc.
Zenodo. https://doi.org/10.5281/zenodo.23806977

## Licence

Code: PolyForm Noncommercial License 1.0.0 ([LICENSE](LICENSE)). Documentation, examples and verification reports:
CC BY-NC 4.0 ([LICENSE-docs.md](LICENSE-docs.md)). Commercial use is not permitted. Third-party components keep their
own licences ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).

Results are for learning and first estimates, not for design, licensing or safety cases.

Contact: GeoAI Alignment, Inc., https://geoaialign.ai
