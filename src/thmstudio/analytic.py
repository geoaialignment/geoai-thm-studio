"""Reference solutions for the verification cases (pure Python, no SciPy)."""
from __future__ import annotations

import math

import numpy as np

EULER_GAMMA = 0.5772156649015329


def exp1(u: float) -> float:
    """Exponential integral E1(u), u > 0 (Theis well function W(u))."""
    if u <= 0:
        raise ValueError("u must be positive")
    if u < 1.0:
        s, term, k = 0.0, 1.0, 1
        while True:
            term *= -u / k
            add = -term / k
            s += add
            if abs(add) < 1e-17 * abs(s) or k > 200:
                break
            k += 1
        return -EULER_GAMMA - math.log(u) + s
    # continued fraction (modified Lentz)
    b = u + 1.0
    c = 1.0 / 1e-300
    d = 1.0 / b
    h = d
    for i in range(1, 300):
        a = -i * i
        b += 2.0
        d = 1.0 / (a * d + b)
        c = b + a / c
        de = c * d
        h *= de
        if abs(de - 1.0) < 1e-16:
            break
    return h * math.exp(-u)


def exp_erfc(a: float, b: float) -> float:
    """exp(a) * erfc(b) without overflow (a may be large when b is large)."""
    if b < 5.0:
        return math.exp(a) * math.erfc(b) if a < 700 else math.exp(a - b * b) * _erfcx(b)
    return math.exp(a - b * b) * _erfcx(b)


def _erfcx(b: float) -> float:
    """Scaled complementary error function exp(b^2) erfc(b), b >= 5 (asymptotic series)."""
    if b < 5.0:
        return math.exp(b * b) * math.erfc(b)
    s, term = 1.0, 1.0
    for n in range(1, 12):
        term *= -(2 * n - 1) / (2.0 * b * b)
        s += term
    return s / (b * math.sqrt(math.pi))


# ---------------------------------------------------------------- heat

def erfc_step(x, t, diffusivity, dT=1.0):
    """Semi-infinite solid, surface raised by dT at t = 0: dT erfc(x / (2 sqrt(kappa t)))."""
    return np.array([dT * math.erfc(xi / (2 * math.sqrt(diffusivity * t))) for xi in np.atleast_1d(x)])


def slab_with_source(x, length, q, conductivity):
    """Steady 1D slab, T = 0 at both ends, uniform source q (W/m3): q x (L - x) / (2 lambda)."""
    x = np.asarray(x, float)
    return q * x * (length - x) / (2 * conductivity)


def series_layers(x, bounds, conductivities, t0, t1):
    """Steady 1D conduction (or flow) through layers in series, value t0 at bounds[0], t1 at bounds[-1]."""
    x = np.asarray(x, float)
    res = np.diff(bounds) / np.asarray(conductivities, float)
    flux = (t0 - t1) / res.sum()
    out = np.empty_like(x)
    for i, xi in enumerate(x):
        v, xb = t0, bounds[0]
        for j in range(len(res)):
            if xi <= bounds[j + 1] + 1e-12:
                v -= flux * (xi - bounds[j]) / conductivities[j]
                break
            v -= flux * res[j]
        out[i] = v
    return out


def radial_inclusion(r, a, q, k_in, k_out, r_ref, t_ref):
    """Steady radial conduction: source q (W/m3) inside r < a, value t_ref at r_ref (> a)."""
    r = np.asarray(r, float)
    outside = t_ref - q * a * a / (2 * k_out) * np.log(np.maximum(r, 1e-300) / r_ref)
    t_a = t_ref - q * a * a / (2 * k_out) * math.log(a / r_ref)
    inside = t_a + q * (a * a - r * r) / (4 * k_in)
    return np.where(r <= a, inside, outside)


def radial_inclusion_expression(xc, yc, a, q, k_out, r_ref, t_ref) -> str:
    """OGS parameter expression of the outer branch (used as boundary values)."""
    c = q * a * a / (2 * k_out)
    return f"{t_ref!r} - {c!r}*log(sqrt((x-{xc!r})^2+(y-{yc!r})^2)/{r_ref!r})"


# ---------------------------------------------------------------- flow

def theis_drawdown(r, t, rate, transmissivity, storativity):
    """Drawdown s = Q / (4 pi T) W(r^2 S / (4 T t)) for pumping rate Q > 0."""
    return np.array([rate / (4 * math.pi * transmissivity) * exp1(ri * ri * storativity / (4 * transmissivity * t))
                     for ri in np.atleast_1d(r)])


# ---------------------------------------------------------------- transport

def advection_dispersion(x, t, v, D, R=1.0, decay=0.0, c0=1.0):
    """1D semi-infinite column, c = c0 at x = 0 from t = 0, zero initial concentration.

    R dc/dt = D c'' - v c' - decay R c (decay is the rate constant, mu = decay R). With
    decay = 0 and R = 1 this is the Ogata-Banks solution.
    """
    mu = decay * R
    u = v * math.sqrt(1.0 + 4.0 * mu * D / (v * v)) if v > 0 else 2.0 * math.sqrt(mu * D)
    out = []
    for xi in np.atleast_1d(x):
        den = 2.0 * math.sqrt(D * R * t)
        a1, b1 = (v - u) * xi / (2 * D), (R * xi - u * t) / den
        a2, b2 = (v + u) * xi / (2 * D), (R * xi + u * t) / den
        out.append(0.5 * c0 * (exp_erfc(a1, b1) + exp_erfc(a2, b2)))
    return np.array(out)


def heat_advection(x, t, darcy_velocity, rho_c_eff, rho_c_water, conductivity, dT=1.0):
    """Heat carried by steady flow through a porous column (no thermal dispersion), inlet raised by dT."""
    v = rho_c_water * darcy_velocity / rho_c_eff
    D = conductivity / rho_c_eff
    return advection_dispersion(x, t, v, D, 1.0, 0.0, dT)


# ---------------------------------------------------------------- consolidation (HM)

def terzaghi_pressure(depth, t, load, cv, H, terms=200):
    """Excess pore pressure in a column drained at the top (depth 0) and closed at depth H,
    after a load applied at t = 0 (incompressible grains and water: initial pressure = load)."""
    out = []
    for z in np.atleast_1d(depth):
        s = 0.0
        for m in range(terms):
            M = (2 * m + 1) * math.pi / 2
            s += 2.0 / M * math.sin(M * z / H) * math.exp(-M * M * cv * t / (H * H))
        out.append(load * s)
    return np.array(out)


def terzaghi_settlement(t, load, cv, H, constrained_modulus, terms=200):
    """Settlement of the loaded top: (load H / M) U(t), U the average degree of consolidation."""
    s = 0.0
    for m in range(terms):
        M = (2 * m + 1) * math.pi / 2
        s += 2.0 / (M * M) * math.exp(-M * M * cv * t / (H * H))
    return load * H / constrained_modulus * (1.0 - s)


def biot_column(load, alpha, porosity, E, nu, permeability, viscosity, H):
    """Biot consolidation of a laterally confined column with incompressible water: a Biot coefficient alpha < 1
    implies compressible grains (K_s = K / (1 - alpha)), hence storage S = (alpha - phi)(1 - alpha) / K.
    Returns (initial pressure, consolidation coefficient, constrained modulus, storage)."""
    M = E * (1 - nu) / ((1 + nu) * (1 - 2 * nu))
    K = E / (3 * (1 - 2 * nu))
    S = (alpha - porosity) * (1 - alpha) / K
    p0 = alpha * load / (alpha * alpha + S * M)
    cv = permeability * M / (viscosity * (alpha * alpha + S * M))
    return p0, cv, M, S


def biot_settlement(t, load, alpha, p0, cv, H, constrained_modulus, terms=200):
    """Displacement of the loaded top (negative = down): -(load - alpha * mean pressure) H / M."""
    s = 0.0
    for m in range(terms):
        Mm = (2 * m + 1) * math.pi / 2
        s += 2.0 / (Mm * Mm) * math.exp(-Mm * Mm * cv * t / (H * H))
    return -(load - alpha * p0 * s) * H / constrained_modulus


# ---------------------------------------------------------------- point heat source (THM)

class PointHeatSource:
    """Booker and Savvidou (1985) with the stress correction of Chaudhry et al. (2019):
    point source Q (W) in an infinite saturated porous medium, incompressible constituents.
    Ported from the OGS benchmark notebook (ThermoHydroMechanics/Linear/Point_injection)."""

    def __init__(self, Q, porosity, permeability, viscosity, E, nu, rho_w, c_w, lambda_w, rho_s, c_s,
                 lambda_s, alpha_s_linear, beta_w, T0):
        self.Q, self.T0 = Q, T0
        lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        G = E / (2 * (1 + nu))
        self.K = porosity * lambda_w + (1 - porosity) * lambda_s
        m = porosity * rho_w * c_w + (1 - porosity) * rho_s * c_s
        self.kappa = self.K / m
        self.c = permeability / viscosity * (lam + 2 * G)
        a_s = 3 * alpha_s_linear
        self.a_u = a_s * (1 - porosity) + beta_w * porosity
        bprime = (lam + 2 * G / 3) * a_s
        self.X = self.a_u * (lam + 2 * G) - bprime
        self.Y = 1 / (lam + 2 * G) * (self.X / ((1 - self.c / self.kappa) * self.a_u) + bprime / self.a_u)
        self.Z = 1 / (lam + 2 * G) * (self.X / ((1 - self.c / self.kappa) * self.a_u))

    @staticmethod
    def _f(k, R, t):
        return math.erfc(R / (2 * math.sqrt(k * t)))

    def _g(self, k, R, t):
        a = k * t / R ** 2
        return a + (0.5 - a) * self._f(k, R, t) - math.sqrt(a / math.pi) * math.exp(-R * R / (4 * k * t))

    def temperature(self, R, t):
        return np.array([self.T0 + self.Q / (4 * math.pi * self.K * r) * self._f(self.kappa, r, t)
                         for r in np.atleast_1d(R)])

    def pressure(self, R, t):
        return np.array([self.X / (1 - self.c / self.kappa) * self.Q / (4 * math.pi * self.K * r)
                         * (self._f(self.kappa, r, t) - self._f(self.c, r, t)) for r in np.atleast_1d(R)])

    def radial_displacement(self, R, t):
        """Displacement along the radius vector (u_i = x_i / R times this)."""
        return np.array([self.a_u * self.Q / (4 * math.pi * self.K) *
                         (self.Y * self._g(self.kappa, r, t) - self.Z * self._g(self.c, r, t)) for r in np.atleast_1d(R)])
