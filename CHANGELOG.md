# Changelog

## 0.1.1 (2026-10-31)

- Technical notes (English, Korean) now show a mesh built from a plain-language request: a recorded conversation with
  gpt-6.1-terra (`tests/final_api/nl_mesh_ledger.json`, mesh files in `runs/nl_mesh/`), new Figure 2; later figures
  renumbered.
- One figure style for result maps, profiles, time series and mesh previews (`src/thmstudio/plotstyle.py`): larger
  text, 200 dpi, a one-hue colour scale per quantity, constrained layout so that titles, legends and colour bars do not
  overlap the plot, visible boundary and interface lines, non-negative quantities scaled from zero.
- README: Elder figure, showcase of two demonstrations outside the verified configurations (CO2 dissolution fingering,
  heat from a repository panel changing groundwater flow).
- No change to the computation, the verification cases or the checks; all 177 tests pass. The preprint is the v0.1.0
  text submitted to the ESS Open Archive.

## 0.1.0 (2026-10-31)

First public release.
