# -*- coding: utf-8 -*-
"""
Raymer (Aircraft Design: A Conceptual Approach) mission-fuel-fraction
feasibility check for this project's FIXED, already-known aircraft
(gross mass, empty mass, fuel capacity, aero, and engine are all
established elsewhere in this project already - nothing here is being
sized or iterated, unlike Raymer's own Chapter 3/6 TOGW sizing loop).

WHY RAYMER, WHY THIS CHAPTER: this project's mission-analysis approach
was originally NASA Aviary (Dymos/SLSQP trajectory optimization), which
was retired after a documented, provable numerical/structural limitation
(see scripts/classical_mission.py's module docstring) and replaced with
a from-scratch direct-integration tool. That tool is physically sound,
but has no textbook citation behind its specific method - reasonable for
an engineering deliverable, not ideal for a course project where the
sizing methodology itself needs to be justified. Raymer's book is the
cited, standard reference for this kind of conceptual-design mission
analysis, so this module implements the SAME question (does this
aircraft complete its mission, and how much fuel does that take) using
Raymer's own method instead, fully traceable to specific equations.

WHICH RAYMER METHOD: Chapter 19, "Sizing and Trade Studies" -> "Improved
Conceptual Sizing Methods". This is deliberately NOT the earlier Chapter
3/6 method (statistical mission-segment fractions like 0.985 for climb,
a guessed L/D_max from an aspect-ratio correlation, a guessed constant
TSFC) - that method is for a blank-sheet design with no real aero/engine
data yet. Chapter 19 is Raymer's OWN refinement of that method for
exactly this project's situation: "Now that we have a design layout...
we can calculate better estimates for the fuel used during each mission
segment" using the actual as-drawn aircraft's real aerodynamic and
propulsion data instead of early guesses (Raymer, Ch 19, "Review of
Sizing Method"). Concretely, this project already HAS that real data:
build_aero_polar.py's VSPAero-derived drag polar (used here for real
CL/CD instead of Raymer's own L/D_max statistical correlation) and
build_engine_deck.py's Mattingly & Heiser engine deck (used here for
real thrust/TSFC instead of a guessed constant C) - using them here is
exactly what this chapter's own logic calls for, not a deviation from it.

METHOD, PER SEGMENT (equation numbers are Raymer, Chapter 19):
  General (fixed-engine) form, Eq. 19.6/19.7: fuel burned in a segment
  of duration d at average thrust T and specific fuel consumption C is
  Wfuel = C*T*d; the segment weight fraction is Wi/Wi-1 = 1 - C*d*(T/W)i.
  This project uses FIXED-engine sizing throughout (a real, already-known
  aircraft, not a "rubber engine" being scaled) - per Raymer: "For
  fixed-engine sizing, Eq. (19.7) would have to be recalculated for each
  iteration... Alternatively, Eq. (19.6) can be used to calculate the
  actual weight of the fuel burned by that fixed-size engine" - exactly
  what every segment function below does (works in actual fuel weight,
  not an assumed-constant weight fraction).

  Climb, Eq. 19.8/19.9 (energy-height method):
    Wi/Wi-1 = exp[-C*delta_he / (V*(1 - D/T))],  delta_he = delta(h + V^2/2g)
  Applied in small altitude steps (Raymer: "A long climb... should be
  broken into segments such that the quantity C/[V(1-D/T)] is
  approximately constant" - exactly why this integrates in small steps
  rather than one whole-climb average). If T does not exceed D at some
  altitude, (1 - D/T) <= 0 and Eq. 19.8 is undefined/nonphysical - Raymer
  never has to confront this because his worked examples don't hit it,
  but this project's aircraft has a DOCUMENTED, real thrust-margin
  problem (see classical_mission.py's development history), so this is
  treated as a real, reportable "cannot sustain climb past this altitude"
  finding, not silently divided through.

  Cruise, Eq. 19.10 (Breguet range equation):
    Wi/Wi-1 = exp[-R*C / (V*(L/D))]
  Applied in small distance steps with throttle solved each step so
  thrust equals drag (per Raymer: "For a constant-airspeed, constant-
  altitude cruise, the cruise must be broken into shorter segments and
  the L/D revised as the weight changes").

  Descent: Raymer's own words - "The detailed calculation of descent
  fuel is probably more trouble than it is worth for quick studies and
  student design projects. The earlier historical method... is usually
  good enough." A fixed historical weight fraction is used here for
  exactly that reason, with distance/time from a simple assumed descent
  angle (idle power, no detailed energy-height calculation).

  Engine start/warmup/taxi/takeoff and landing: Raymer's own historical
  mission-segment fractions (Chapter 3, Table 3.2-class values), which
  the same Chapter 19 section explicitly re-endorses even for "more
  refined sizing" ("This is probably good enough even for more refined
  sizing").

FEASIBILITY VERDICT: this is not a sizing loop - gross mass, empty mass,
and fuel tank capacity are already fixed (see run_raymer_mission_check's
own arguments, matching main.py's ENGINE & MISSION CONFIG section and
classical_mission.py's own placeholder values for a direct, apples-to-
apples comparison between the two independent methods on the same
aircraft). Raymer describes exactly this scenario: "the takeoff weight
calculated from the refined estimate of fuel burned and the as-drawn
empty weight will not equal the as-drawn takeoff weight" - i.e., the
fuel actually REQUIRED by the mission (per this chapter's method, plus
Raymer's stated 6% reserve/trapped-fuel allowance) will not generally
match the fuel actually AVAILABLE (this aircraft's real tank capacity).
RESIDUAL FUEL = fuel available - fuel required is exactly that mismatch:
positive means the mission is flyable with margin, negative means this
aircraft, as currently sized, cannot complete it.

MISSION PROFILE: climb - cruise - descent only, no combat/dash/loiter.
Raymer's own worked fighter-mission examples in this chapter include
supersonic dash and combat-turn segments; this project's aircraft flies
a much simpler transit mission (climb to a cruise altitude/Mach, cruise
the design range, descend), Mach 0.2-0.6 throughout - entirely subsonic,
well below where those extra segments or supersonic-specific equations
(e.g. the Oswald-efficiency correction for M > 1) would even apply. A
plain climb-cruise-descent profile matches both the actual research
question (does a baseline vs. RCS-shaped config complete a transit
mission, judged by fuel burn) and this aircraft's real, already-
established characteristics (a low-aspect-ratio, thrust-margin-limited
design - see classical_mission.py's development history), so it is the
right scope for this check, not an oversimplification of it.

SUPPORTING DATA: build_aero_polar.py/build_engine_deck.py are reused
directly (not duplicated) - they are this project's own general-purpose
VSPAero-polar-reading and Mattingly-&-Heiser-engine-deck-building
utilities, not anything specific to classical_mission.py's own
integration approach. This module's AeroLookup/EngineLookup classes
below are lighter-weight, independent wrappers around that same data
(no cl_margin bookkeeping, no adaptive Mach search, no throttle-fallback
retry ladder) - this file is a deliberately separate, self-contained
implementation of Raymer's method, not a re-skin of
classical_mission.py, even though both tools answer the same underlying
question about the same aircraft.
"""

import os
import sys

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

sys.path.insert(0, os.path.dirname(__file__))

import vsp_setup
from build_aero_polar import build_polar_arrays, reshape_to_grid
from build_engine_deck import build_deck

LBM_TO_KG = 0.45359237
FT_TO_M = 0.3048
NMI_TO_FT = 6076.11549
NMI_TO_M = NMI_TO_FT * FT_TO_M
LBF_TO_N = 4.4482216153
G = 9.80665


class ThrustMarginError(RuntimeError):
    """Raised when thrust does not exceed drag by enough margin to
    sustain the required climb rate - Raymer's own Eq. 19.8 becomes
    undefined/nonphysical when T <= D (the (1 - D/T) term in the
    denominator goes to zero or negative), so this is a real finding
    the equation itself flags, not an artificial check bolted on."""


class LiftMarginError(RuntimeError):
    """Raised when the required CL exceeds this aero table's tested
    range - a real lift/stall-margin shortfall, never fixable by more
    thrust or a different mission-segment equation."""


class AeroLookup:
    """(altitude, Mach, alpha) -> (CL, CD), built directly from this
    project's own VSPAero sweep via build_aero_polar.py - the same
    source classical_mission.py uses, wrapped independently here."""

    def __init__(self, geom_stem, expected_machs=None, expected_altitudes=None, search_dir=None):
        arrays = build_polar_arrays(geom_stem, expected_machs, expected_altitudes, search_dir)
        lift_grid, drag_grid = reshape_to_grid(arrays)
        alt_vals = np.sort(np.unique(np.round(arrays["altitude"], 3)))
        mach_vals = np.sort(np.unique(np.round(arrays["mach"], 3)))
        alpha_vals = np.sort(np.unique(np.round(arrays["alpha"], 3)))
        self.alpha_vals = alpha_vals
        self.max_cl = float(lift_grid.max())
        self._cl_interp = RegularGridInterpolator(
            (alt_vals, mach_vals, alpha_vals), lift_grid,
            bounds_error=False, fill_value=None,
        )
        self._cd_interp = RegularGridInterpolator(
            (alt_vals, mach_vals, alpha_vals), drag_grid,
            bounds_error=False, fill_value=None,
        )

    def cd_for_cl(self, alt_ft, mach, cl_required):
        """Cuts a (CL, CD)-vs-alpha slice at this exact flight condition
        and interpolates it for the CD at cl_required - a direct table
        lookup, not an iterative solve (extrapolation is the caller's
        responsibility to flag via cl_required vs self.max_cl)."""
        pts = np.array([[alt_ft, mach, a] for a in self.alpha_vals])
        cl_slice = self._cl_interp(pts)
        cd_slice = self._cd_interp(pts)
        order = np.argsort(cl_slice)
        return float(np.interp(cl_required, cl_slice[order], cd_slice[order]))


class EngineLookup:
    """(Mach, altitude, throttle) -> (thrust_lbf, fuel_flow_lbm_per_hr),
    from an engine deck built by build_engine_deck.py (or a real
    custom_engine_deck_path CSV in the same column format) - the same
    source classical_mission.py uses, read directly here.

    The deck models ONE ENGINE's performance curve - published, per-
    engine spec values, same convention this project's main.py uses for
    ENGINE_T_SL_DRY_LBF/ENGINE_T_SL_AB_LBF. num_engines scales thrust AND
    fuel flow up to the whole aircraft's installed total: this project's
    aircraft is a confirmed TWIN-engine design (see
    classical_mission.py's num_engines docstring for the full derivation
    - a single engine at this aircraft's mass gives an unrealistically
    low thrust-to-weight ratio), so num_engines=2 is this module's own
    smoke test default too."""

    def __init__(self, deck_path, num_engines=1):
        self.num_engines = num_engines
        df = pd.read_csv(deck_path, comment="#")
        df.columns = [c.strip() for c in df.columns]
        col_map = {c.lower().replace(" ", "").replace("_", ""): c for c in df.columns}

        def _find(*names):
            for n in names:
                key = n.lower().replace(" ", "").replace("_", "")
                if key in col_map:
                    return col_map[key]
            raise KeyError(f"None of {names} found in engine deck columns {list(df.columns)}")

        mach_col = _find("Mach_Number", "Mach", "MachNumber")
        alt_col = _find("Altitude(ft)", "Altitude", "Alt")
        throttle_col = _find("Throttle", "PowerCode")
        thrust_col = _find("Net_Thrust(lbf)", "Thrust", "NetThrust")
        fuel_col = _find("Fuel_Flow_Rate(lbm/h)", "FuelFlow", "Fuel_Flow", "FuelFlowRate")

        mach_vals = np.sort(df[mach_col].unique())
        alt_vals = np.sort(df[alt_col].unique())
        throttle_vals = np.sort(df[throttle_col].unique())
        self.throttle_vals = throttle_vals

        thrust_grid = np.full((len(mach_vals), len(alt_vals), len(throttle_vals)), np.nan)
        fuel_grid = np.full_like(thrust_grid, np.nan)
        m_idx = {v: i for i, v in enumerate(mach_vals)}
        a_idx = {v: i for i, v in enumerate(alt_vals)}
        t_idx = {v: i for i, v in enumerate(throttle_vals)}
        for _, row in df.iterrows():
            i, j, k = m_idx[row[mach_col]], a_idx[row[alt_col]], t_idx[row[throttle_col]]
            thrust_grid[i, j, k] = row[thrust_col]
            fuel_grid[i, j, k] = row[fuel_col]
        if np.isnan(thrust_grid).any():
            raise ValueError(
                f"Engine deck at {deck_path} is missing points for a complete "
                f"{len(mach_vals)}x{len(alt_vals)}x{len(throttle_vals)} "
                f"(Mach x Altitude x Throttle) grid."
            )

        self._thrust_interp = RegularGridInterpolator(
            (mach_vals, alt_vals, throttle_vals), thrust_grid,
            bounds_error=False, fill_value=None,
        )
        self._fuel_interp = RegularGridInterpolator(
            (mach_vals, alt_vals, throttle_vals), fuel_grid,
            bounds_error=False, fill_value=None,
        )

    def thrust_and_fuel_flow(self, mach, alt_ft, throttle):
        """Returns (thrust_lbf, fuel_flow_lbm_per_hr) for the WHOLE
        aircraft (per-engine deck values x num_engines)."""
        pt = np.array([[mach, alt_ft, throttle]])
        thrust_lbf = float(self._thrust_interp(pt)[0]) * self.num_engines
        fuel_flow_lbm_hr = float(self._fuel_interp(pt)[0]) * self.num_engines
        return thrust_lbf, fuel_flow_lbm_hr

    def throttle_for_thrust(self, mach, alt_ft, thrust_required_lbf):
        """Solves for the throttle giving exactly thrust_required_lbf,
        by linear interpolation against the deck's own throttle grid
        (build_engine_deck.py's decks are piecewise-linear in throttle by
        construction, so this is an exact inversion). Returns (throttle,
        fuel_flow_lbm_per_hr, achievable)."""
        thrusts = [self.thrust_and_fuel_flow(mach, alt_ft, t)[0] for t in self.throttle_vals]
        if thrust_required_lbf > thrusts[-1]:
            return float(self.throttle_vals[-1]), self.thrust_and_fuel_flow(
                mach, alt_ft, self.throttle_vals[-1])[1], False
        if thrust_required_lbf <= thrusts[0]:
            return float(self.throttle_vals[0]), self.thrust_and_fuel_flow(
                mach, alt_ft, self.throttle_vals[0])[1], True
        throttle = float(np.interp(thrust_required_lbf, thrusts, self.throttle_vals))
        fuel_flow = float(np.interp(throttle, self.throttle_vals,
                                     [self.thrust_and_fuel_flow(mach, alt_ft, t)[1]
                                      for t in self.throttle_vals]))
        return throttle, fuel_flow, True


def _required_cl(mass_lbm, mach, alt_ft, wing_area_ft2):
    _, rho, _, a_sound = vsp_setup.isa_atmosphere(alt_ft)
    v_mps = mach * a_sound
    weight_n = mass_lbm * LBM_TO_KG * G
    wing_area_m2 = wing_area_ft2 * (FT_TO_M ** 2)
    q_pa = 0.5 * rho * v_mps ** 2
    return weight_n / (q_pa * wing_area_m2), v_mps, q_pa


def _drag_lbf(cd, q_pa, wing_area_ft2):
    wing_area_m2 = wing_area_ft2 * (FT_TO_M ** 2)
    return cd * q_pa * wing_area_m2 / LBF_TO_N


def _raise_if_cl_exceeds_margin(segment_name, alt_ft, mach, mass_lbm, cl_req, cl_margin, max_cl):
    if cl_req > cl_margin * max_cl:
        raise LiftMarginError(
            f"{segment_name} at altitude={alt_ft:.0f} ft, Mach={mach:.3f}: required "
            f"CL={cl_req:.3f} exceeds {cl_margin:.0%} of this aero table's tested max "
            f"CL ({max_cl:.3f}) at mass={mass_lbm:.0f} lbm - a real lift-margin "
            f"shortfall, not a numerical artifact."
        )


def fly_climb_raymer(
    aero, engine, wing_area_ft2, mass_lbm,
    alt_start_ft, alt_end_ft, mach_start, mach_end, throttle,
    cl_margin=0.9, alt_step_ft=1000.0, min_climb_rate_fpm=300.0,
):
    """Raymer Ch 19, Eq. 19.8/19.9 (energy-height climb weight fraction),
    integrated in small altitude steps - Raymer's own guidance for when a
    single-segment average would not hold. Mach is ramped LINEARLY
    between mach_start/mach_end over the altitude range (a plain
    approximation of the actual climb schedule, appropriate for this
    method - no adaptive acceleration search the way
    classical_mission.py's own, separate tool does; that refinement is
    specific to that tool, not part of citing Raymer's method here).

    Distance credit follows Raymer's own stated convention exactly:
    "Distance travelled during climb is calculated as average velocity
    times the time to climb" (not a horizontal-only decomposition).

    min_climb_rate_fpm is a practical floor on top of Eq. 19.8's own
    built-in failure mode (T <= D makes (1 - D/T) <= 0, undefined) - this
    project's aircraft has a documented, real thrust-margin sensitivity
    to altitude (see classical_mission.py's development history), so a
    small positive climb rate is treated the same as no climb rate at
    all: not a realistic part of a cross-country climb schedule.

    Returns (time_s, distance_nmi, fuel_burned_lbm, final_mass_lbm).
    Raises ThrustMarginError naming the exact altitude/condition if climb
    rate collapses below min_climb_rate_fpm (or T stops exceeding D
    outright), or LiftMarginError if required CL exceeds the aero
    table's tested range - both real findings, not numerical failures."""
    n_steps = max(1, int(round(abs(alt_end_ft - alt_start_ft) / alt_step_ft)))
    alts = np.linspace(alt_start_ft, alt_end_ft, n_steps + 1)
    machs = np.linspace(mach_start, mach_end, n_steps + 1)

    total_time_s = 0.0
    total_dist_nmi = 0.0
    total_fuel_lbm = 0.0
    mass = mass_lbm

    for i in range(n_steps):
        alt_mid = 0.5 * (alts[i] + alts[i + 1])
        mach_mid = 0.5 * (machs[i] + machs[i + 1])
        v1_mps = machs[i] * vsp_setup.isa_atmosphere(alts[i])[3]
        v2_mps = machs[i + 1] * vsp_setup.isa_atmosphere(alts[i + 1])[3]
        v_avg_mps = 0.5 * (v1_mps + v2_mps)

        cl_req, v_mid_mps, q_pa = _required_cl(mass, mach_mid, alt_mid, wing_area_ft2)
        _raise_if_cl_exceeds_margin("climb", alt_mid, mach_mid, mass, cl_req, cl_margin, aero.max_cl)
        cd = aero.cd_for_cl(alt_mid, mach_mid, cl_req)
        drag_lbf = _drag_lbf(cd, q_pa, wing_area_ft2)
        thrust_lbf, fuel_flow_lbm_hr = engine.thrust_and_fuel_flow(mach_mid, alt_mid, throttle)
        c_per_s = (fuel_flow_lbm_hr / 3600.0) / thrust_lbf  # TSFC, 1/s

        d_alt_ft = alts[i + 1] - alts[i]
        d_alt_m = d_alt_ft * FT_TO_M
        delta_he_m = d_alt_m + 0.5 * (v2_mps ** 2 - v1_mps ** 2) / G  # Eq. 19.9

        one_minus_D_over_T = 1.0 - drag_lbf / thrust_lbf
        if one_minus_D_over_T <= 0:
            raise ThrustMarginError(
                f"climb at altitude={alt_mid:.0f} ft, mass={mass:.0f} lbm, "
                f"Mach={mach_mid:.3f}: thrust ({thrust_lbf:.0f} lbf) does not exceed "
                f"drag ({drag_lbf:.0f} lbf) - Raymer's Eq. 19.8 climb weight fraction "
                f"is undefined here (1 - D/T <= 0). This throttle setting's real "
                f"ceiling is below the requested cruise altitude "
                f"({alt_end_ft:.0f} ft); not a numerical failure."
            )
        weight_fraction = np.exp(-c_per_s * delta_he_m / (v_mid_mps * one_minus_D_over_T))  # Eq. 19.8

        ps_mps = (thrust_lbf - drag_lbf) * LBF_TO_N * v_mid_mps / (mass * LBM_TO_KG * G)  # specific excess power
        roc_fpm = ps_mps * 196.850394
        if roc_fpm < min_climb_rate_fpm:
            raise ThrustMarginError(
                f"climb at altitude={alt_mid:.0f} ft, mass={mass:.0f} lbm, "
                f"Mach={mach_mid:.3f}: climb rate has dropped to {roc_fpm:.0f} ft/min "
                f"(thrust={thrust_lbf:.0f} lbf, drag={drag_lbf:.0f} lbf), below the "
                f"{min_climb_rate_fpm:.0f} ft/min practical floor. This throttle "
                f"setting's real ceiling is below the requested cruise altitude "
                f"({alt_end_ft:.0f} ft); not a numerical failure."
            )

        dt_s = delta_he_m / ps_mps
        dx_m = v_avg_mps * dt_s  # Raymer's own stated distance convention
        d_fuel_lbm = mass * (1.0 - weight_fraction)

        total_time_s += dt_s
        total_dist_nmi += dx_m / NMI_TO_M
        total_fuel_lbm += d_fuel_lbm
        mass -= d_fuel_lbm

    return total_time_s, total_dist_nmi, total_fuel_lbm, mass


def fly_cruise_breguet(
    aero, engine, wing_area_ft2, mass_lbm, cruise_alt_ft, cruise_mach,
    distance_nmi, cl_margin=0.9, dist_step_nmi=20.0,
):
    """Raymer Ch 19, Eq. 19.10 (Breguet range equation), stepped by
    distance with throttle solved each step so thrust equals drag (level,
    unaccelerated flight) - per Raymer: "the cruise must be broken into
    shorter segments and the L/D revised as the weight changes."

    Returns (time_s, distance_nmi, fuel_burned_lbm, final_mass_lbm).
    Raises ThrustMarginError if required thrust exceeds this engine's
    full-throttle thrust, or LiftMarginError if required CL exceeds the
    aero table's tested range."""
    n_steps = max(1, int(round(distance_nmi / dist_step_nmi)))
    step_nmi = distance_nmi / n_steps
    step_m = step_nmi * NMI_TO_M
    mass = mass_lbm
    total_time_s = 0.0
    total_fuel_lbm = 0.0

    for _ in range(n_steps):
        cl_req, v_mps, q_pa = _required_cl(mass, cruise_mach, cruise_alt_ft, wing_area_ft2)
        _raise_if_cl_exceeds_margin("cruise", cruise_alt_ft, cruise_mach, mass, cl_req, cl_margin, aero.max_cl)
        cd = aero.cd_for_cl(cruise_alt_ft, cruise_mach, cl_req)
        drag_lbf = _drag_lbf(cd, q_pa, wing_area_ft2)
        l_over_d = cl_req / cd

        throttle, fuel_flow_lbm_hr, achievable = engine.throttle_for_thrust(cruise_mach, cruise_alt_ft, drag_lbf)
        if not achievable:
            raise ThrustMarginError(
                f"cruise at altitude={cruise_alt_ft:.0f} ft, Mach={cruise_mach:.3f}: "
                f"required thrust ({drag_lbf:.0f} lbf) exceeds this engine's full-"
                f"throttle thrust at mass={mass:.0f} lbm - a real thrust shortfall."
            )
        thrust_lbf, _ = engine.thrust_and_fuel_flow(cruise_mach, cruise_alt_ft, throttle)
        c_per_s = (fuel_flow_lbm_hr / 3600.0) / thrust_lbf

        weight_fraction = np.exp(-step_m * c_per_s / (v_mps * l_over_d))  # Eq. 19.10
        dt_s = step_m / v_mps
        d_fuel_lbm = mass * (1.0 - weight_fraction)

        total_time_s += dt_s
        total_fuel_lbm += d_fuel_lbm
        mass -= d_fuel_lbm

    return total_time_s, distance_nmi, total_fuel_lbm, mass


def fly_descent_historical(
    mass_lbm, alt_start_ft, alt_end_ft, mach_mid,
    descent_angle_deg=3.0, descent_fuel_fraction=0.99,
):
    """Raymer's own explicitly-endorsed simplification: "The detailed
    calculation of descent fuel is probably more trouble than it is
    worth for quick studies and student design projects. The earlier
    historical method... is usually good enough." A fixed historical
    weight fraction (descent_fuel_fraction) is used directly rather than
    an energy-height calculation; distance/time come from a simple
    assumed constant descent flight-path angle at idle-ish power (this
    part is ordinary flight kinematics, not a Raymer-specific equation).

    Returns (time_s, distance_nmi, fuel_burned_lbm, final_mass_lbm)."""
    alt_mid = 0.5 * (alt_start_ft + alt_end_ft)
    _, _, _, a_sound = vsp_setup.isa_atmosphere(alt_mid)
    v_mps = mach_mid * a_sound
    roc_mps = v_mps * np.sin(np.radians(descent_angle_deg))
    d_alt_m = abs(alt_end_ft - alt_start_ft) * FT_TO_M
    dt_s = d_alt_m / roc_mps
    dx_m = v_mps * dt_s
    fuel_burned_lbm = mass_lbm * (1.0 - descent_fuel_fraction)
    return dt_s, dx_m / NMI_TO_M, fuel_burned_lbm, mass_lbm - fuel_burned_lbm


def run_raymer_mission_check(
    geom_stem, wing_area_ft2, gross_mass_lbm, fuel_capacity_lbm, design_range_nmi,
    cruise_mach, cruise_altitude_ft,
    climb_mach_initial=0.38, climb_mach_final=None, descent_mach_final=0.3,
    mach_list=None, altitude_list=None,
    custom_engine_deck_path=None,
    engine_t_sl_dry_lbf=17800.0, engine_t_sl_ab_lbf=29100.0,
    engine_throttle_ratio=1.07, engine_type="low_bypass_mixed_flow_turbofan",
    num_engines=2,
    climb_throttle=0.5, climb_throttle_fallback=1.0,
    cl_margin=0.9,
    start_taxi_takeoff_fraction=0.97, landing_fraction=0.995,
    descent_fuel_fraction=0.99, descent_angle_deg=3.0,
    reserve_trapped_fuel_factor=1.06,
    aero_search_dir=None,
):
    """Runs the climb-cruise-descent mission via Raymer Ch 19's refined
    mission-segment method and checks it against this aircraft's KNOWN
    fuel capacity - not a sizing loop (gross_mass_lbm and
    fuel_capacity_lbm are inputs, not things being solved for).

    start_taxi_takeoff_fraction/landing_fraction: Raymer's own historical
    mission-segment fractions (Ch 3-class values, re-endorsed in Ch 19
    even for refined sizing - "probably good enough even for more
    refined sizing").

    reserve_trapped_fuel_factor: Raymer's stated 6% allowance ("A 6%
    allowance was added to the mission fuel to account for reserve and
    trapped fuel"), applied to the total fuel burned across all segments.

    climb_throttle_fallback: if the climb at climb_throttle (military
    power by default) hits a real thrust shortfall (ThrustMarginError -
    Eq. 19.8 undefined, or below min_climb_rate_fpm, even within this
    phase's own Mach range), the climb is retried in full from sea level
    at this higher throttle instead of failing outright - the same real-
    world response classical_mission.py's independent tool needed for
    this aircraft (afterburner, when military power cannot sustain the
    climb). Set to None (or <= climb_throttle) to disable.

    Returns a dict: if the climb cannot complete at any throttle tried,
    {'climb_completed': False, 'failure_reason': ..., 'achieved_altitude_ft': ...,
    'climb_throttle_used': ...} (cruise/descent never ran - mirrors
    classical_mission.py's own graceful-degradation convention, since
    "this config's climb ran out of thrust" needs to be a normal,
    comparable outcome for a baseline-vs-RCS-shaped comparison, not a
    crash). Otherwise {'climb_completed': True, 'feasible': bool,
    'residual_fuel_lbm': ..., 'fuel_required_lbm': ..., 'fuel_capacity_lbm': ...,
    'climb'/'cruise'/'descent': {'time_s', 'distance_nmi', 'fuel_lbm'},
    'climb_throttle_used': ...}. Every other failure mode (a lift-margin
    shortfall in any phase, a cruise thrust shortfall, climb+descent
    distance alone exceeding the design range) still raises."""
    climb_mach_final = climb_mach_final if climb_mach_final is not None else cruise_mach

    # aero_search_dir: None (default) makes AeroLookup search
    # vsp_setup.AERO_RESULTS_DIR (Results/Aero/) exactly as before - the
    # shared location main.py's own single-geometry runs use. Pass an
    # explicit directory when geom_stem's own aero CSVs were written
    # somewhere else (e.g. aero_stab_mission_worker.py redirects each
    # config's run_vspaero_aero() output to its own per-study aero/
    # subfolder via output_dir - see that file).
    aero = AeroLookup(geom_stem, expected_machs=set(mach_list) if mach_list else None,
                       expected_altitudes=set(altitude_list) if altitude_list else None,
                       search_dir=aero_search_dir)

    if custom_engine_deck_path:
        engine_deck_path = custom_engine_deck_path
    else:
        engine_deck_path = build_deck(
            out_dir=os.path.join(vsp_setup.AVIARY_FILES, "engines"),
            deck_name="raymer_mission_check_f100_pw229_simplified.deck",
            t_sl_dry=engine_t_sl_dry_lbf, t_sl_ab=engine_t_sl_ab_lbf,
            throttle_ratio=engine_throttle_ratio, engine_type=engine_type,
        )
    engine = EngineLookup(engine_deck_path, num_engines=num_engines)

    # Engine start/warmup/taxi/takeoff (Raymer historical fraction)
    mass_after_start = gross_mass_lbm * start_taxi_takeoff_fraction
    fuel_start_lbm = gross_mass_lbm - mass_after_start

    climb_throttle_used = climb_throttle
    unrecoverable = None
    try:
        t_climb, d_climb, fuel_climb, mass_after_climb = fly_climb_raymer(
            aero, engine, wing_area_ft2, mass_after_start,
            alt_start_ft=0.0, alt_end_ft=cruise_altitude_ft,
            mach_start=climb_mach_initial, mach_end=climb_mach_final,
            throttle=climb_throttle, cl_margin=cl_margin,
        )
    except ThrustMarginError as e:
        if climb_throttle_fallback is None or climb_throttle_fallback <= climb_throttle:
            unrecoverable = (e, climb_throttle)
        else:
            print(f"   [climb] military power (throttle={climb_throttle}) hit a real "
                  f"thrust shortfall - {e}\n"
                  f"   [climb] retrying the full climb at climb_throttle_fallback="
                  f"{climb_throttle_fallback} (this WILL burn substantially more fuel).")
            climb_throttle_used = climb_throttle_fallback
            try:
                t_climb, d_climb, fuel_climb, mass_after_climb = fly_climb_raymer(
                    aero, engine, wing_area_ft2, mass_after_start,
                    alt_start_ft=0.0, alt_end_ft=cruise_altitude_ft,
                    mach_start=climb_mach_initial, mach_end=climb_mach_final,
                    throttle=climb_throttle_fallback, cl_margin=cl_margin,
                )
            except ThrustMarginError as e2:
                unrecoverable = (e2, climb_throttle_fallback)

    if unrecoverable is not None:
        exc, throttle_tried = unrecoverable
        print(f"   [climb] MISSION NOT FEASIBLE: could not reach {cruise_altitude_ft:.0f} "
              f"ft even at throttle={throttle_tried} - {exc}")
        return {
            "engine_deck_path": engine_deck_path,
            "climb_completed": False,
            "failure_reason": str(exc),
            "climb_throttle_used": throttle_tried,
            "target_cruise_altitude_ft": cruise_altitude_ft,
            "gross_mass_lbm": gross_mass_lbm,
            "fuel_capacity_lbm": fuel_capacity_lbm,
            "design_range_nmi": design_range_nmi,
        }

    # Rough pre-estimate of descent (for cruise distance budgeting only -
    # matches classical_mission.py's own pattern for the same reason: the
    # real descent needs the post-cruise mass, which isn't known yet).
    _, d_descent_est, _, _ = fly_descent_historical(
        mass_after_climb * 0.97, cruise_altitude_ft, 500.0, 0.5 * (cruise_mach + descent_mach_final),
        descent_angle_deg=descent_angle_deg, descent_fuel_fraction=descent_fuel_fraction,
    )

    cruise_distance_nmi = design_range_nmi - d_climb - d_descent_est
    if cruise_distance_nmi <= 0:
        raise RuntimeError(
            f"Climb ({d_climb:.1f} nmi) + descent ({d_descent_est:.1f} nmi) ground "
            f"distance alone exceeds the {design_range_nmi:.0f} nmi design range - "
            f"this mission profile doesn't fit the design range at all, independent "
            f"of fuel."
        )

    t_cruise, d_cruise, fuel_cruise, mass_after_cruise = fly_cruise_breguet(
        aero, engine, wing_area_ft2, mass_after_climb, cruise_altitude_ft, cruise_mach,
        cruise_distance_nmi, cl_margin=cl_margin,
    )

    t_descent, d_descent, fuel_descent, mass_after_descent = fly_descent_historical(
        mass_after_cruise, cruise_altitude_ft, 500.0, 0.5 * (cruise_mach + descent_mach_final),
        descent_angle_deg=descent_angle_deg, descent_fuel_fraction=descent_fuel_fraction,
    )

    # Landing (Raymer historical fraction)
    mass_after_landing = mass_after_descent * landing_fraction
    fuel_landing_lbm = mass_after_descent - mass_after_landing

    total_range_nmi = d_climb + d_cruise + d_descent
    fuel_before_reserve_lbm = fuel_start_lbm + fuel_climb + fuel_cruise + fuel_descent + fuel_landing_lbm
    fuel_required_lbm = fuel_before_reserve_lbm * reserve_trapped_fuel_factor
    residual_fuel_lbm = fuel_capacity_lbm - fuel_required_lbm

    return {
        "engine_deck_path": engine_deck_path,
        "climb_completed": True,
        "feasible": bool(residual_fuel_lbm >= 0),
        "climb_throttle_used": climb_throttle_used,
        "start_taxi_takeoff": {"fuel_lbm": fuel_start_lbm},
        "climb": {"time_s": t_climb, "distance_nmi": d_climb, "fuel_lbm": fuel_climb},
        "cruise": {"time_s": t_cruise, "distance_nmi": d_cruise, "fuel_lbm": fuel_cruise},
        "descent": {"time_s": t_descent, "distance_nmi": d_descent, "fuel_lbm": fuel_descent},
        "landing": {"fuel_lbm": fuel_landing_lbm},
        "total_range_nmi": total_range_nmi,
        "design_range_nmi": design_range_nmi,
        "fuel_before_reserve_lbm": fuel_before_reserve_lbm,
        "fuel_required_lbm": fuel_required_lbm,
        "fuel_capacity_lbm": fuel_capacity_lbm,
        "residual_fuel_lbm": residual_fuel_lbm,
        "gross_mass_lbm": gross_mass_lbm,
        "final_mass_lbm": mass_after_landing,
    }


def print_results(results):
    print("\n" + "=" * 68)
    print("RAYMER (CH 19) MISSION-FUEL-FRACTION FEASIBILITY CHECK")
    print("=" * 68)
    if results.get("climb_completed") is False:
        print(f"  VERDICT: MISSION NOT FEASIBLE (could not complete the climb)")
        print(f"  Climb throttle tried    : {results['climb_throttle_used']:.2f}")
        print(f"  Target cruise altitude  : {results['target_cruise_altitude_ft']:.0f} ft")
        print("-" * 68)
        print(f"  Reason: {results['failure_reason']}")
        print("=" * 68)
        return

    print(f"  Climb throttle used     : {results['climb_throttle_used']:.2f}")
    for phase in ("climb", "cruise", "descent"):
        p = results[phase]
        print(f"  {phase.capitalize():8s}  {p['distance_nmi']:8.1f} nmi  "
              f"{p['time_s'] / 60.0:6.1f} min  {p['fuel_lbm']:9.1f} lbm fuel")
    print("-" * 68)
    print(f"  Start/taxi/takeoff fuel : {results['start_taxi_takeoff']['fuel_lbm']:.1f} lbm")
    print(f"  Landing fuel            : {results['landing']['fuel_lbm']:.1f} lbm")
    print(f"  Total range flown       : {results['total_range_nmi']:.1f} nmi "
          f"(design range: {results['design_range_nmi']:.1f} nmi)")
    print("-" * 68)
    print(f"  Fuel burned (pre-reserve): {results['fuel_before_reserve_lbm']:.1f} lbm")
    print(f"  Fuel REQUIRED (+6% reserve/trapped, Raymer Ch 19): {results['fuel_required_lbm']:.1f} lbm")
    print(f"  Fuel AVAILABLE (tank capacity)                   : {results['fuel_capacity_lbm']:.1f} lbm")
    print(f"  RESIDUAL FUEL (available - required)             : {results['residual_fuel_lbm']:+.1f} lbm")
    verdict = "FEASIBLE" if results["feasible"] else "NOT FEASIBLE"
    print(f"  VERDICT: MISSION {verdict}")
    print("=" * 68)


if __name__ == "__main__":
    # Standalone smoke test - same real geometry/mass/mission placeholders
    # classical_mission.py uses, for a direct, apples-to-apples comparison
    # between the two independently-derived methods on the same aircraft.
    # num_engines=2: this aircraft is a confirmed twin-engine design (see
    # classical_mission.py's num_engines docstring).
    # fuel_capacity_lbm=18064.672003: F22_FUEL_MASS_LBM/F22_WING_AREA_FT2 *
    # wing_area_ft2 above (same F-22A wing-loading scaling main.py's
    # GROSS_MASS_LBM/FUEL_CAPACITY_LBM use) - matches main.py's own
    # FUEL_CAPACITY_LBM exactly; replaces a prior 24590.81 placeholder of
    # unestablished provenance.
    results = run_raymer_mission_check(
        geom_stem="SSAM_final_geom_to_be_used_scaled_by_19_simplified",
        wing_area_ft2=843.018026816014,
        gross_mass_lbm=83800.00623707,
        fuel_capacity_lbm=18064.672003,
        design_range_nmi=400.0,
        cruise_mach=0.6,
        cruise_altitude_ft=35000.0,
        mach_list=[0.2, 0.4, 0.6],
        altitude_list=[0.0, 15000.0, 35000.0],
        num_engines=2,
    )
    print_results(results)
