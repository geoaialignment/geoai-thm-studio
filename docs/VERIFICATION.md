# Verification

Every configuration the agent computes is backed by the cases below. Each case builds its model from the same model tree the agent uses, runs OpenGeoSys 6.5.8, and compares the result with an exact solution or an official OpenGeoSys input. Errors are normalised as stated in each case file (`src/thmstudio/cases/`); tolerances were fixed before the comparison and checked by halving element size and time step together. Each result is recorded with the package and OpenGeoSys versions it was computed with; the agent computes a configuration only when all its cases have passed with the installed versions (here 0.1.0 and 6.5.8).

## H-2D: groundwater flow in a 2D section or plan

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V1a | Steady upward flow through two layers in series | Darcy's law, layers in series (exact for linear elements) | max norm < 0.01 % | < 0.01 % | passed |

## H-AX-well: radial flow to a well (axisymmetric)

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V1b | Theis drawdown around a pumping well | Theis (1935); OGS benchmark Parabolic/LiquidFlow/AxiSymTheis | max norm 3 %, l2 rel 2 % | 2 % | passed |

## H-3D: groundwater flow in a 3D box

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V1c | Hydrostatic pressure in a layered 3D box | hydrostatics; OGS benchmark Parabolic/LiquidFlow/Verification/h1_3Dhydstat | max norm < 0.01 % | < 0.01 % | passed |
| V1c-flow | Steady horizontal flow through a layered 3D box | Darcy's law (head linear along the flow direction) | max norm < 0.01 % | < 0.01 % | passed |

## T-2D: heat conduction in 2D

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V2a | Heat conduction into a half-space after a step in surface temperature | Carslaw and Jaeger (1959) erfc solution; OGS benchmark Parabolic/T/1D_dirichlet (line_60_heat) | max norm 1 %, l2 rel 2 % | 0.21 % | passed |
| V2a-tri | Heat conduction into a half-space after a step in surface temperature (triangle mesh, gmsh) | Carslaw and Jaeger (1959) erfc solution; OGS benchmark Parabolic/T/1D_dirichlet (line_60_heat) | max norm 1 %, l2 rel 2 % | 0.11 % | passed |
| V2b | Steady slab with a uniform heat source | steady conduction with uniform source, T(x) = q x (L - x) / (2 lambda) | max norm < 0.01 %; temperature between the nodes: max norm 0.1 % | 0.063 % | passed |
| V2b-power | Steady slab with a heat source given as total power | as V2b; total power 100 W over 10 m x 1 m x 1 m equals 10 W/m3 | max norm < 0.01 % | < 0.01 % | passed |
| V2d | Steady radial conduction around a heated circular inclusion | steady radial conduction with an internal source; the exact solution is imposed on the outer rectangle | max norm 1 %, l2 rel 1 % | 0.22 % | passed |
| V2a-official | Official line_60_heat input against the erfc solution | official OpenGeoSys input Parabolic/T/1D_dirichlet/line_60_heat.prj | max norm 1 %, l2 rel 2 % | 0.21 % | passed |

## T-3D: heat conduction in a 3D box

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V2c | 3D box heated from the top surface (1D erfc in depth) | Carslaw and Jaeger (1959) erfc solution in a 3D box with insulated sides | max norm 1 %, l2 rel 2 % | 0.64 % | passed |
| V2c-steady | Steady conduction through two layers in a 3D box | steady conduction through layers in series | max norm < 0.01 % | < 0.01 % | passed |

## TH-2D: heat transport by groundwater flow in 2D

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V3 | Heat carried by steady flow through a porous column | advection-conduction (Ogata and Banks 1961 form); OGS benchmark Parabolic/HT/HeatTransportInStationaryFlow | max norm 2 %, l2 rel 2 %; Darcy flux: max norm < 0.01 % | 0.97 % | passed |
| V3-water | Heat carried by steady flow, pure water (official setting: porosity 1) | advection-conduction (Ogata and Banks 1961 form); OGS benchmark Parabolic/HT/HeatTransportInStationaryFlow | max norm 2 %, l2 rel 2 %; Darcy flux: max norm < 0.01 % | 0.45 % | passed |
| V3-official | Official HeatTransportInStationaryFlow input against its published output | OpenGeoSys benchmark Parabolic/HT/HeatTransportInStationaryFlow, run unchanged; compared with the published output at t = 50000 s | max norm 0.1 % | < 0.01 % | passed |

- V3-official: an engine baseline like V2a-official and V6b-official: it does not exercise the translator; V3 and V3-water do.

## HC-2D: solute transport (advection, dispersion, sorption, decay) in 2D

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V6a | Solute front in steady flow (advection and dispersion) | Ogata and Banks (1961) | max norm 2 %, l2 rel 2 %; Darcy flux from the flux condition: max norm < 0.01 % | 0.68 % | passed |
| V6b | Radionuclide migration with sorption and decay (135Cs in clay) | analytical solution after van Genuchten and Alves (1982); OGS benchmark Parabolic/ComponentTransport/AdvectionDiffusionSorptionDecay | max norm 2 %, l2 rel 3 % | 1.4 % | passed |
| V6b-official | Official AdvectionDiffusionSorptionDecay input against the analytical solution | official OpenGeoSys input Parabolic/ComponentTransport/AdvectionDiffusionSorptionDecay/1D_AdvectionDiffusionSorptionDecay.prj | max norm 2 %, l2 rel 3 % | 1.4 % | passed |

## HC-2D-density: density-driven (buoyant) solute transport in a vertical section

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| E2 | Elder problem: salt fingers sinking under their own weight | Elder (1967), Voss and Souza (1987); compared with the official OGS benchmark output (Parabolic/ComponentTransport/elder) on the same 128 x 64 grid | max norm 5 %, l2 rel 5 % | 2.3 % | passed |

- E2: half domain: the right side (x = 300 m) is the symmetry line of the classic 600 m model. The official input is a one-element-thick 3D slab; this case builds a 2D model from the model tree. The fields agree within 2.5 % at 1, 2 and 4 years (largest point difference 2.3 %). On this grid both runs, ours and the official one, dip below zero next to the fingers (to -0.21 at 4 years), an undershoot of the unstabilised Galerkin method; the answer card reports such values as a warning.

## HM-2D: consolidation of saturated ground under load (plane strain; verified with a 1D column)

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V4 | One-dimensional consolidation of a loaded column (Terzaghi) | Terzaghi (1925); OGS benchmarks HydroMechanics/Verification/hm2_1D1bt and Linear/Confined_Compression | max norm 2 %, l2 rel 2 %; other tolerances for some checks (see the case file) | 0.81 % | passed |
| V4b | Consolidation with a Biot coefficient of 0.6 | Biot consolidation, laterally confined column: alpha < 1 implies compressible grains, storage S = (alpha - phi)(1 - alpha) / K; initial pressure alpha load / (alpha^2 + S M), cv = k M / (mu (alpha^2 + S M)) | max norm 2 %, l2 rel 2 %; other tolerances for some checks (see the case file) | 0.81 % | passed |

- V4b: A first reference that ignored the grain storage implied by alpha < 1 was physically inconsistent and did not match; OGS uses the consistent storage.

## TM-2D: thermal expansion and thermal stress in rock (plane strain)

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V7a | Free thermal expansion of a heated block (plane strain) | linear thermoelasticity, uniform temperature change (exact for the element type) | max norm < 0.01 % | < 0.01 % | passed |
| V7b | Fully constrained heated block (plane strain) | linear thermoelasticity, uniform temperature change (exact for the element type) | max norm < 0.01 % | < 0.01 % | passed |
| V7c | Heated column confined at its sides, free at the top (plane strain) | linear thermoelasticity, uniform temperature change (exact for the element type) | max norm < 0.01 % | < 0.01 % | passed |

## THM-AX: point heat source in saturated rock (axisymmetric)

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| V5 | Point heat source in saturated porous rock (thermal pressurisation) | Booker and Savvidou (1985), stress correction by Chaudhry et al. (2019); OGS benchmark ThermoHydroMechanics/Linear/Point_injection | max norm 3 %, l2 rel 3 % | 1.1 % | passed |

- V5: ten steps of 5000 s (the official setting) give 5-6 % errors near the front; 500 s steps with a 0.01 m source refinement give about 1 %. Integration order 4 (official) and 3 give the same result.

## THM-AX-repository: heated canister in a buffer-filled hole in rock (axisymmetric; demonstration)

| case | what is compared | source | tolerance | largest error | result |
|---|---|---|---|---|---|
| E1 | Heated canister in a bentonite-filled deposition hole in granite (demonstration) | consistency checks: energy balance, mesh and time-step convergence, region areas (no exact solution exists) | heat stored = power x time within 1 %; change between element size 2h and h at temperature points within 2 %; change between element size 2h and h at pressure points within 5 %; region areas checked against the geometry when the mesh is built | 0.75 % (largest check value) | passed |
| E1a | Small canister in homogeneous rock behaves as a point source | homogeneous limit of the repository configuration compared with the point-source solution (V5) away from the canister | max norm 3 %, l2 rel 3 % | 1.7 % | passed |

This configuration is a demonstration: no exact solution exists, so it is checked for energy balance, mesh and time-step convergence, region areas, and a homogeneous limit equal to THM-AX.

Run `thmstudio verify` to repeat all cases on your machine; the agent reports your results instead of the release record once they exist.
