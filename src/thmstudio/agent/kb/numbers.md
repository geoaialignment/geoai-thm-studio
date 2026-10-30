# Dimensionless numbers and resolution rules

- Heat diffusivity kappa = lambda / (rho c). After time t, heat has spread about sqrt(kappa t).
  Granite: kappa ≈ 1.4e-6 m2/s, so about 7 m after 1 year and 22 m after 10 years.
- Hydraulic diffusivity D = K / Ss (m2/s). Pressure spreads about sqrt(D t).
- Consolidation coefficient cv = k M / mu with M = E (1 - nu) / ((1 + nu)(1 - 2 nu)); time to consolidate a layer of
  drainage length H is about H^2 / cv.
- Cell Peclet number Pe = v h / (2 D) for transport (v pore velocity, h element size, D dispersion): keep below 1,
  otherwise fronts smear or oscillate. check_model reports it.
- Courant number v dt / h: keep below 1 for sharp fronts.
- Near a point source temperatures follow Q / (4 pi lambda r) and grow without bound; read results at least two
  elements away from the point.
- Boundaries: a model boundary should be farther than the spreading distance of the studied time, unless the boundary
  is physical.
