# Coupled phenomena (what the comparisons show)

## Thermal pressurisation (THM)
Heating expands pore water more than the grains. In low-permeability rock the water cannot leave quickly, so pore
pressure rises, then falls as it diffuses. Compare `no_water_thermal_expansion` to see its size. It scales with the
water expansion coefficient and inversely with permeability.

## Thermal stress (TM, THM)
Where expansion is held back, compressive stress builds: fully confined, sigma = -E alpha dT / (1 - 2 nu).
Compare `no_solid_thermal_expansion`.

## Consolidation (HM)
A load is first carried by the pore water; as it drains, the solid skeleton takes the load and the ground settles.
Compare `no_hydro_mechanical_coupling` (the settlement then happens at once and pressure does not rise).
Water is incompressible in v0.1. A Biot coefficient alpha below 1 means compressible grains; the model then has the
storage (alpha - phi)(1 - alpha)/K (K the drained bulk modulus), so part of the settlement happens at once and the
initial pore pressure is alpha load / (alpha^2 + S M) instead of the load (verified by V4b).
Thermal stress uses the change from the initial temperature (the initial state is stress free).

## Heat carried by flow (TH)
Flowing water carries heat; the thermal front moves slower than the water by (rho c)_water / (rho c)_bulk times porosity
effects. A plan-view model without flow in the comparison would need a different process; v0.1 compares within TH only.

## Sorption and decay (HC)
Sorption delays a solute by the retardation factor R; decay removes it with its half-life. Compare `no_sorption`,
`no_decay`.

## Repository near field (THM-AX-repository)
A heated canister raises temperature in the buffer and rock; bentonite conducts heat less well than rock, so the
temperature drop across the buffer is large. Pore pressure rises in the buffer and rock by thermal pressurisation.
v0.1 treats bentonite as saturated linear poroelastic: swelling and drying are not represented.
