# 3 Results

## 3.1 Verification

All 27 verification cases passed with version 0.1.0 of the package and OpenGeoSys 6.5.8, and 21 of them agree with their references within 1 % (Table 1, Figure 2). The two largest errors are those of the Elder problem against the official benchmark output, 2.3 %, and of the Theis drawdown near the well at early time, 2.0 %, both within their tolerances. The eight cases whose solution is exact for the element type at the nodes compared, such as steady flow through layers in series or the uniform heating of a block, agree to round-off.

Two comparisons show that the translation adds no measurable error in the problems where this can be tested. When an official OpenGeoSys input runs unchanged and the harness builds the same problem from the model tree, both agree with the reference equally well: 0.21 % for heat conduction into a half-space and 1.4 % for radionuclide migration with sorption and decay. In the Elder problem, the concentration dips below zero next to the sinking fingers, to −0.21 of the source concentration at four years, in our run and in the official one alike. This undershoot comes from the unstabilized Galerkin method on this grid, and it is the kind of value the answer card reports as a warning.

![Figure 2. Largest error of each verification case, grouped by configuration (for E1, the largest consistency check). Filled circles: models built from the model tree by the harness; open circles: official OpenGeoSys inputs run unchanged. Errors below 0.0001 % are drawn at 0.0001 %. Tolerances are given in the case files; the dashed line marks 1 %.](../figures/Figure2_verification.png)

*Table 1. Configurations of version 0.1 and their verification cases. Largest error: the largest normalized maximum-norm error of any comparison in the case (for THM-AX-repository, the largest consistency check). Cases marked "official input" run official OpenGeoSys inputs unchanged as engine baselines and are not part of the rule that admits a configuration.*

{{TABLE1}}

## 3.2 Agent Runs

The stand-in model passed 20 of the 21 scenarios. In {{l6_runs_with_errors}} of the 21 stand-in runs some tool calls returned errors ({{l6_errors}} of {{l6_calls}} calls in all): a tool called in the wrong state, an argument in the wrong form, or a model refused by check_model. Each such call returned the state and the next step, and none ended a run. The two requests out of scope were refused without a run and with a pointer to GeoAI Alignment, and for the request for consolidation with gravity the model ran the consolidation without gravity and said why.

The one failed scenario asked for the steady-state concentration profile in a sand column. Steady solute transport is not a verified configuration, and check_model refused it. The stand-in model then ran the transient model for a year and described the filled column as the steady state, instead of saying that the request could not be met as asked. Every number in this answer came from the card, so the output guardrail passed it; the judge failed it only because a check written for this scenario required the answer to explain the limit.

In the final check, all 16 runs with the OpenAI models passed the judge, and every answer quoted only numbers from its card, the model inputs or the request (Table 2). Apart from the out-of-scope request, which both models refused without a tool call, each of these 16 runs took 11 to 23 tool calls. In the Korean surface-heating scenario, the output guardrail sent both models' first answers back, because the guardrail of that version did not recognize numbers written directly before Korean characters ("10도", 10 degrees) as numbers from the request. Both models rewrote their answers, and the released guardrail reads such numbers.

Three gpt-6-luna runs failed before their first model call because of an event-loop error in our test runner and were repeated after the fix. The whole check cost USD 1.58. Of this, USD 1.18 was metered, and USD 0.40 was booked as an upper bound for two attempts that crashed before their cost was counted.

*Table 2. Final check with the OpenAI API: one run per model (luna: gpt-6-luna; terra: gpt-6.1-terra) and scenario, all 16 passed by the judge, and the recomputation audit. Calls: tool calls in the run. Audit: largest relative difference between a card value and the same value recomputed with the reference mesh; 0 % means the same value to the digits on the card.*

{{TABLE2}}

## 3.3 A Wrong Answer With Correct Provenance

The recomputation audit found one scenario in which the answers were wrong. It asks, in Korean, how much a 300 W point heat source raises the pore pressure in saturated low-permeability rock, and how much of the rise comes from the thermal expansion of the water. Both models started from the point-heat-source example and made its mesh coarser (Table 3). gpt-6-luna enlarged the elements at the source twentyfold and the elements elsewhere twofold; gpt-6.1-terra enlarged only the elements at the source, tenfold. At 0.5 m from the source and the end of the study, they reported pore-pressure changes of −0.507 MPa and 0.635 MPa, whereas the exact solution gives 0.967 MPa (Booker & Savvidou, 1985; Chaudhry et al., 2019).

The example is the point-heat-source verification problem, an axisymmetric half model of 10 m radius and height held at 0 °C and zero pore pressure on its outer and top boundaries. The rock has a permeability of 2 × 10⁻²⁰ m², a porosity of 0.16 and a Young's modulus of 5 GPa (the other properties are in the case file), and the study runs to 50,000 s with a first output at 20,000 s.

Neither the provenance check nor the judge could see the error, although the harness had shown it to one of the models. gpt-6.1-terra had run the comparison with half the element size, and its card showed that the pressure changed by 0.257 MPa. Its answer called the value sensitive to the mesh and suggested a finer one, but reported 0.635 MPa as the result. gpt-6-luna made no half-size comparison; its comparison without the water's expansion gave a higher pressure than its main run, and it explained that, at this point, the water's expansion did not raise the pressure. Both answers quoted only card values and named the verified configuration and its case, so both passed the guardrail and the judge.

The sweep of the source refinement shows how the mesh near the source alone produces such errors (Figure 3). With every other setting of the example unchanged, the source element that gpt-6.1-terra chose gives exactly the 0.635 MPa it reported. The pressure approaches the exact value only once h is well below the heat-spread length of Eq. (1), ℓ = 0.116 m here, and it is still 6.0 % low at h = ℓ/4. The error does not fall monotonically as h shrinks, because the result at the probe also depends on the elements between the source and that point, which grow outward from h.

The sweep does not reproduce gpt-6-luna's negative value; at its source element size the pressure is still positive, so the coarser elements around the source changed the sign.

The temperature shows the mechanism. When the element at the source is comparable to ℓ, the coarse elements smear the heat around the source, and the temperature rise at 0.5 m is underestimated, by 30 % for h = 0.1 m against the exact {{s11_exact_T_K}} K of the same solution. In this rock, pore pressure diffuses about five times more slowly than heat: the consolidation coefficient, the permeability over the water viscosity times the constrained modulus of the rock, is {{s11_c_over_kappa}} of the thermal diffusivity, so the pressure follows the temperature rise and inherits its error.

![Figure 3. Pore-pressure rise 0.5 m from a 300 W point heat source at 50,000 s against the smallest element size at the source. Line: the point-heat-source example with only that size changed (reference mesh 0.01 m). Open symbols: answers of the language models, at the size each requested; their far-field mesh and time settings differed from the example where noted. Dotted lines: ℓ/2, ℓ/4 and ℓ/8 (the released threshold) for the heat-spread length ℓ = 0.116 m of the example (first output 20,000 s). Dashed line: exact solution.](../figures/Figure3_point_source.png)

*Table 3. Pore-pressure rise at 0.5 m and the end of the study, against the exact 0.967 MPa. h: element size requested for the refinement at the source; h/ℓ uses the example's ℓ (gpt-6-luna's ℓ/2 run had a later first output and a larger ℓ). Sweep rows change only h in the example (far-field elements 0.5 m, first time step 500 s).*

{{TABLE3}}

We then added the source-resolution rule, first with the threshold ℓ/2, and ran the scenario again. Both models now chose elements of 0.05 m at the source and passed every check. gpt-6.1-terra kept the rest of the example and reported 0.887 MPa, the value of the sweep at that size and still 8 % low. gpt-6-luna also refined the far field and reported 0.998 MPa, 3 % high; with the example's far field and gpt-6-luna's first and largest time steps and output time (but the example's step growth), the same source element gives nearly the value gpt-6.1-terra reported (Table 3), which suggests that the far field made most of the difference.

With the threshold at ℓ/4, gpt-6.1-terra first had its mesh refused, then took the size the rule suggested, ℓ/8, together with a finer far field, and reported 0.971 MPa, within 0.5 % of the exact value.

The sweep shows that ℓ/4 itself still allows errors of about 6 % and that ℓ/8 on the example's far field gives 2.9 %. We therefore released the rule with the threshold ℓ/8, the coarsest size in the sweep whose error at this point is within 3 %, the tolerance of the verification case on its profiles, and with the suggested size ℓ/12, close to the 0.01 m element of that case. The released threshold ℓ/8 has not been run with the language models, and gpt-6-luna was not run again after the ℓ/2 rule.

## 3.4 Recomputation Audit of the Other Answers

The language models changed the mesh of their starting example in {{mesh_changed}} of the {{mesh_runs}} computed runs, most often by coarsening it next to a well, a boundary or a source. In one pumping-well run, gpt-6-luna enlarged the elements at the well a hundredfold. Except in the point-heat-source scenario, none of these changes mattered for the values the models reported, because the quantities asked for, such as the drawdown 50 m from the well or the temperature 5 m below the surface, lie away from the refined zones.

The recomputed card values of the other scenarios bear this out (Table 2). Of {{audit_other_n}} values, {{audit_other_within_02}} agreed with the reference mesh within 0.2 %. The other three were temperatures in gpt-6-luna's heat-plume answer, which differed by 0.7–2.3 %, the most at the leading edge of the plume, where the rise itself is small. The audit therefore separated a frequent and mostly harmless choice from the one case in which the same kind of choice decided the answer. 

The audit did not recompute the rows that report a difference from a named comparison. Among them is the difference between the point-source runs with and without the water's expansion: 0.431 MPa for gpt-6-luna, whose run with the expansion gave the lower pressure, and 0.550 MPa for gpt-6.1-terra in the first answers, and 0.841 MPa for gpt-6.1-terra after the ℓ/4 rule.
