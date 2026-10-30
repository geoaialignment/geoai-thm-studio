---
title: "Language-Model Agents Running Verified Subsurface Multiphysics Simulations: Traced Numbers and the Modeling Choices That Still Need Checks"
author:
  - "Eungyu Park¹, Taeyu Kim¹, and Jangwon Park¹"
  - "¹GeoAI Alignment, Inc., Daegu, Republic of Korea"
  - "Corresponding author: Eungyu Park (egpark@knu.ac.kr)"
date: "Preprint, October 2026"
---

# Key Points

- An agent harness for OpenGeoSys computes only verified configurations and rejects answers with numbers not traced to the run or the inputs
- In 16 runs with two small OpenAI models every checked number was traced, yet both models answered a heat-source question wrongly after coarsening the mesh
- Recomputing answers on the meshes of their starting examples exposed the error, and a rule tied to how far heat has spread now refuses such meshes

# Abstract

Language-model agents can now set up and run numerical simulations from a sentence, but a reported number can be wrong in two ways: the simulator never produced it, or it came from a model that was set up badly. We built GeoAI-THM Studio, an agent harness for OpenGeoSys 6.5.8 in which the language model edits only a typed model tree through 21 tools, a configuration is computed only after its verification cases pass (27 cases; 21 within 1 % of their exact solutions, official benchmarks or consistency checks, all within 2.5 %), and an output guardrail rejects answers whose checked numbers cannot be traced to the run, the model inputs or the request. In 16 runs with gpt-6-luna and gpt-6.1-terra on eight requests in heat, groundwater flow, deformation and solute transport, every number the guardrail checks in every answer was traced in this way, and Claude Haiku 5.5, standing in for a small model during development, passed 20 of 21 test scenarios, from which the eight requests were drawn. Yet both OpenAI models answered how much a 300 W point heat source raises pore pressure wrongly, −0.507 and 0.635 MPa against 0.967 MPa from the exact solution, because both had coarsened the mesh at the source, and gpt-6-luna also around it. gpt-6.1-terra had itself found that halving the elements changed its value by 0.257 MPa and called the result mesh-sensitive, but still reported it, and the scoring script, which checks procedure and provenance, passed both answers. Recomputing every answer on the mesh of its starting example exposed the errors. A sweep of the element size at the source showed the pressure within 3 % of the exact value only when the elements there are no larger than one eighth of the distance heat has spread by the first output, and the released harness refuses coarser meshes. We propose, as a hypothesis for further tests, that each modeling choice left to the language model needs a physics-based check of this kind.

# Plain Language Summary

Computer models of heat, groundwater and rock deformation underground are hard to set up, and AI assistants that build them from a plain request are now possible. We built such an assistant around the open simulator OpenGeoSys. The assistant may only fill in a structured description of the model. The program checks that description, runs only kinds of problems it has checked against known solutions or consistency tests, and lets the assistant quote only numbers it can trace to the simulator results, the model settings or the request. With two inexpensive AI models behind it, the assistant handled eight test requests this way, and every number it reported, apart from small counts and years that are not checked, came from the simulator, the model settings or the request itself. Still, both models gave a wrong answer to one question, how much a small heat source raises the water pressure in rock, because each had made the computer mesh too coarse around the heat source. Checks of where the numbers came from could not notice this. Repeating the calculation with the finer mesh of the original example revealed the problem, and a new rule now refuses meshes that are too coarse for how far the heat has spread. This suggests that an assistant of this kind should be checked not only on where its numbers come from but also on the modeling decisions it is allowed to make.
