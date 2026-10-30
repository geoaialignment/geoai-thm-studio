# Third-party notices

GeoAI-THM Studio uses the following software. Each keeps its own licence; nothing in the GeoAI-THM Studio
licences restricts the rights those licences grant.

| Component | Use | Licence |
|---|---|---|
| OpenGeoSys 6.5.8 (`ogs` Python wheel), https://www.opengeosys.org | the simulation engine, run as a separate process | BSD 3-Clause (OpenGeoSys Community) |
| gmsh 4.15.2 (optional extra `mesh-gmsh`), https://gmsh.info | meshing of the circular-inclusion shape and triangle meshes; called only as a separate command-line process, never imported | GNU GPL v2 or later |
| OpenAI Agents SDK (`openai-agents`) | agent runtime | MIT |
| Model Context Protocol Python SDK (`mcp`) | MCP server | MIT |
| NumPy | arrays | BSD 3-Clause |
| PyVista, VTK | mesh data and output reading | MIT; BSD 3-Clause |
| meshio | reading gmsh meshes | MIT |
| pydantic | model tree and tool schemas | MIT |
| lxml | XML | BSD 3-Clause |
| Matplotlib | figures | Matplotlib licence (PSF-based) |

Verification inputs: `references/ogs-6.5.8/` (not part of the distributed package) holds unchanged benchmark inputs
and reference outputs from the OpenGeoSys test data (BSD 3-Clause). V2a-official, V3-official and V6b-official run
published inputs; E2 compares with the published Elder reference outputs. `thmstudio verify` skips these four cases unless
the environment variable `THMSTUDIO_OGS_TESTDATA` points at a copy of the OpenGeoSys 6.5.8 test data; the release
record shipped with the package holds their results.

The analytical point-heat-source solution in `src/thmstudio/analytic.py` follows Booker and Savvidou (1985) with
the stress correction of Chaudhry et al. (2019), as implemented in the OpenGeoSys benchmark notebook
`ThermoHydroMechanics/Linear/Point_injection/SaturatedPointheatsource.py`.

Material values in `src/thmstudio/agent/kb/materials.json` are representative values with the sources listed in
that file.
