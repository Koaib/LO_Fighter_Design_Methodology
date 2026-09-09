# -*- coding: utf-8 -*-
"""
Classical (non-optimized) climb/cruise/descent mission analysis.

WHY THIS EXISTS: run_aviary.py's Dymos/SLSQP trajectory optimization was
debugged extensively on the pipeline/improvements branch (see git log) -
several real bugs were found and fixed along the way (a units bug in the
diagnostics, dead code, a disconnected design variable under
OFF_DESIGN_MIN_FUEL, a stale objective reference in the diagnostics), and
the underlying model was proven structurally sound by matching, digit for
digit, a check_totals() result against Aviary's own bundled reference
aircraft. Despite that, the optimizer still stalls on this project's
actual aircraft ("Positive directional derivative for linesearch", a
genuine ~7% non-negligible KKT residual with SLSQP unable to move at all
for 65 iterations) - a real, reproducible numerical/scaling limitation,
not a remaining bug to patch. That matches what the Aviary dev team told
this project directly: off-design analysis is "under development" and
primarily tested with the 2-degrees-of-freedom method, not the
energy-state method this project uses.

This module answers the same question a different way: given a FIXED
aircraft (mass, aero, engine - nothing here is being sized or optimized),
does it complete a climb/cruise/descent mission of the design range, and
how much fuel does that take? It flies a fixed, reasonable schedule
(climb Mach/altitude bounds and cruise Mach/altitude matching this
project's original Aviary mission profile) via direct numerical
integration - small altitude/distance steps, quasi-steady flight
mechanics - instead of collocation + gradient-based optimization. There
is no optimizer in this file, so there is nothing here that can report
"Exit mode 8"; it either completes and reports a real number, or it
reports exactly which altitude/Mach combination ran outside the tested
aero table (an extrapolation would be a real, meaningful failure, not a
numerical artifact) - not the answer a full trajectory optimizer would
give (it doesn't find the OPTIMAL climb schedule, cruise-climb profile,
etc.), but it is a physically-grounded fuel-burn number a baseline-vs-
RCS-shaped comparison can actually rely on getting.

Uses the same data sources the project's now-retired Aviary pipeline
did:
  - build_aero_polar.py's build_polar_arrays()/reshape_to_grid() (the same
    VSPAero-derived (altitude, Mach, alpha) -> (CL, CD) sweep).
  - build_engine_deck.py's build_deck() (the same Mattingly & Heiser
    thrust/TSFC deck, or a real one via custom_engine_deck_path).
Only the trajectory SOLVE differs.

METHOD (per phase):
  Climb:   integrate altitude upward in small steps from sea level to
           cruise altitude, starting at MILITARY (non-afterburning,
           throttle=0.5) power - the standard economical climb setting,
           afterburner being reserved for combat rather than a cross-
           country climb. If that genuinely can't sustain a minimum climb
           rate (a real thrust shortfall, ThrustMarginError - found on
           this project's own real aircraft, not a hypothetical: low-
           aspect-ratio-wing induced drag can eat military thrust well
           below cruise altitude), the whole climb is retried at a higher
           throttle instead of failing the mission outright - exactly
           what a real fighter does when military power isn't enough
           to climb (see run_classical_mission's climb_throttle_fallback
           for details; results['climb_throttle_used'] always records
           which one the reported numbers came from). At each altitude:
           current mass -> required CL (level-flight lift = weight
           approximation) -> alpha and CD from the aero table -> drag;
           thrust/fuel-flow from the engine deck at that Mach/altitude/
           throttle. Climb (vertical) rate from excess power:
           ROC = (Thrust-Drag)*V/Weight. Mach is ramped linearly between
           the climb's mach_initial/mach_final over the altitude range as
           a nominal schedule, but can accelerate past that nominal ramp
           (bounded by mach_final) when needed to keep the climb-rate
           margin above the floor - see fly_climb_or_descent.
  Cruise:  step-cruise at the fixed design Mach/altitude: at each
           distance step, required CL/drag as above, but throttle is
           SOLVED (by direct linear interpolation of the engine deck's
           own piecewise-linear idle->military->max structure, not an
           iterative solver) so that thrust exactly equals drag (level,
           unaccelerated flight) - fuel flow follows directly. Iterated
           until the remaining design range is covered.
  Descent: integrates altitude downward like climb, but at a fixed LOW
           throttle (flight idle, throttle=0.15) - a real descent is
           engine-idle/partial-power, not thrust=drag or a climb-style
           power setting, so vertical rate here is set from an assumed
           descent flight-path angle instead of excess power (an idle
           engine often can't sustain positive excess power at all, so
           the climb phase's ROC formula doesn't apply symmetrically).

This is a deliberate simplification tier, consistent with the rest of
this project's engine deck (Mattingly & Heiser textbook correlations, not
manufacturer data) and aero table (VSPAero VLM, not CFD) - appropriate for
a baseline-vs-RCS-shaped-config COMPARISON, not for a certification-grade
performance guarantee.
"""

import os
import sys

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

# This file's own directory - needed because running it directly
# (Spyder's %runfile, or `python classical_mission.py`) only puts THIS
# file's own directory on sys.path by default; vsp_setup/build_aero_polar/
# build_engine_deck are all plain siblings in scripts/ alongside this file.
sys.path.insert(0, os.path.dirname(__file__))

import vsp_setup
from build_aero_polar import build_polar_arrays, reshape_to_grid
from build_engine_deck import build_deck

LBM_TO_KG = 0.45359237
FT_TO_M = 0.3048
NMI_TO_FT = 6076.11549
G = 9.80665


class ThrustMarginError(RuntimeError):
    """Raised when available thrust can't clear the required margin at a
    flight condition - a real THRUST shortfall (drag, or drag plus a
    climb-rate requirement, exceeds what's available at the throttle
    tried). Still a RuntimeError (any existing `except RuntimeError`
    keeps working), but a distinct subclass so run_classical_mission can
    catch specifically this - and only this - to retry a climb at a
    higher throttle: more thrust is a real fix for this kind of
    shortfall in a way it can never be for a LiftMarginError below.

    partial: when raised from a climb/descent integration that had
    already made real progress, a dict of {time_s, distance_nmi,
    fuel_lbm, mass_lbm, altitude_ft} for how far it got before the
    shortfall - lets a caller report "reached X ft, burned Y lbm getting
    there" as a real, comparable result instead of only a stack trace.
    None when there is no such partial progress to report (e.g. raised
    by find_min_climb_start_mach, which never starts an integration)."""

    def __init__(self, message, partial=None):
        super().__init__(message)
        self.partial = partial


class LiftMarginError(RuntimeError):
    """Raised when required CL exceeds the aero table's tested max CL
    times cl_margin - a real LIFT/stall-margin shortfall. Deliberately a
    different type from ThrustMarginError: more throttle does not
    generate more lift, so this is never worth retrying at a higher
    throttle the way a thrust shortfall is."""


class AeroTable:
    """(altitude, Mach, alpha) -> (CL, CD) lookup, built from this
    project's own VSPAero sweep - the same data the retired Aviary
    pipeline used to feed into Aviary's own aero subsystem, read directly
    here instead."""

    def __init__(self, geom_stem, expected_machs=None, expected_altitudes=None):
        arrays = build_polar_arrays(geom_stem, expected_machs, expected_altitudes)
        lift_grid, drag_grid = reshape_to_grid(arrays)
        alt_vals = np.sort(np.unique(np.round(arrays["altitude"], 3)))
        mach_vals = np.sort(np.unique(np.round(arrays["mach"], 3)))
        alpha_vals = np.sort(np.unique(np.round(arrays["alpha"], 3)))
        self.alt_bounds = (alt_vals.min(), alt_vals.max())
        self.mach_bounds = (mach_vals.min(), mach_vals.max())
        self.alpha_vals = alpha_vals
        self._cl_interp = RegularGridInterpolator(
            (alt_vals, mach_vals, alpha_vals), lift_grid,
            bounds_error=False, fill_value=None,
        )
        self._cd_interp = RegularGridInterpolator(
            (alt_vals, mach_vals, alpha_vals), drag_grid,
            bounds_error=False, fill_value=None,
        )
        self.max_cl = float(lift_grid.max())

    def cd_for_required_cl(self, alt_ft, mach, cl_required):
        """Solves for the CD that goes with cl_required at this flight
        condition, by cutting a (CL, CD)-vs-alpha slice out of the 3D
        table at this exact (alt, mach) and interpolating within it - a
        direct table lookup, not an iterative Newton solve, so it always
        returns a value (extrapolation is flagged by the caller checking
        cl_required against self.max_cl, not by this method failing)."""
        pts = np.array([[alt_ft, mach, a] for a in self.alpha_vals])
        cl_slice = self._cl_interp(pts)
        cd_slice = self._cd_interp(pts)
        order = np.argsort(cl_slice)
        alpha_deg = float(np.interp(cl_required, cl_slice[order], self.alpha_vals[order]))
        cd = float(np.interp(cl_required, cl_slice[order], cd_slice[order]))
        return cd, alpha_deg


class EngineTable:
    """(Mach, altitude, throttle) -> (thrust_lbf, fuel_flow_lbm_per_hr),
    from an engine deck (either the auto-generated Mattingly & Heiser
    deck or a real custom_engine_deck_path CSV) - read directly rather
    than through Aviary's now-retired EngineDeck class.

    The deck (and build_engine_deck.py's t_sl_dry/t_sl_ab inputs) model
    ONE ENGINE's performance curve - published, per-engine F100-PW-229
    spec values, the same convention Aviary itself used for
    Aircraft.Engine.REFERENCE_SLS_THRUST (a per-engine value Aviary
    scaled by Aircraft.Engine.NUM_ENGINES internally). num_engines
    here does the same scaling explicitly: confirmed this session that
    this aircraft is a TWIN-engine design (gross_mass_lbm=83,800 with a
    single F100-PW-229-class engine gives T/W~0.35 at full afterburner -
    3-5x below any real fighter's, and was the dominant reason an earlier
    climb-feasibility check found this aircraft couldn't sustain even a
    modest climb rate past a few thousand feet); num_engines=1 remains
    the default since this class has no way to know the real engine
    count on its own."""

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

        self._mach_col = _find("Mach_Number", "Mach", "MachNumber")
        self._alt_col = _find("Altitude(ft)", "Altitude", "Alt")
        self._throttle_col = _find("Throttle", "PowerCode")
        self._thrust_col = _find("Net_Thrust(lbf)", "Thrust", "NetThrust")
        self._fuel_col = _find("Fuel_Flow_Rate(lbm/h)", "FuelFlow", "Fuel_Flow", "FuelFlowRate")

        mach_vals = np.sort(df[self._mach_col].unique())
        alt_vals = np.sort(df[self._alt_col].unique())
        throttle_vals = np.sort(df[self._throttle_col].unique())
        self.mach_bounds = (mach_vals.min(), mach_vals.max())
        self.alt_bounds = (alt_vals.min(), alt_vals.max())
        self.throttle_vals = throttle_vals

        thrust_grid = np.full((len(mach_vals), len(alt_vals), len(throttle_vals)), np.nan)
        fuel_grid = np.full_like(thrust_grid, np.nan)
        m_idx = {v: i for i, v in enumerate(mach_vals)}
        a_idx = {v: i for i, v in enumerate(alt_vals)}
        t_idx = {v: i for i, v in enumerate(throttle_vals)}
        for _, row in df.iterrows():
            i, j, k = m_idx[row[self._mach_col]], a_idx[row[self._alt_col]], t_idx[row[self._throttle_col]]
            thrust_grid[i, j, k] = row[self._thrust_col]
            fuel_grid[i, j, k] = row[self._fuel_col]
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
        aircraft (per-engine deck values x num_engines), not one engine -
        every other method on this class (throttle_for_required_thrust
        included, since it's built from repeated calls to this one)
        inherits the scaling automatically."""
        pt = np.array([[mach, alt_ft, throttle]])
        thrust_lbf = float(self._thrust_interp(pt)[0]) * self.num_engines
        fuel_flow_lbm_hr = float(self._fuel_interp(pt)[0]) * self.num_engines
        return thrust_lbf, fuel_flow_lbm_hr

    def throttle_for_required_thrust(self, mach, alt_ft, thrust_required_lbf):
        """Solves for the throttle giving exactly thrust_required_lbf at
        this Mach/altitude, by linearly interpolating between the deck's
        own throttle grid points - the deck is itself piecewise-linear in
        throttle by construction (build_engine_deck.py interpolates
        idle->military->max linearly), so this is an exact inversion, not
        an approximation, as long as the deck's own throttle grid is used
        (the default (0.0, 0.5, 1.0) works; a real custom deck should
        supply enough throttle points for this to still hold reasonably).
        Returns (throttle, fuel_flow_lbm_per_hr, achievable) - achievable
        is False if even full throttle can't produce enough thrust."""
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
    velocity_mps = mach * a_sound
    weight_n = mass_lbm * LBM_TO_KG * G
    wing_area_m2 = wing_area_ft2 * (FT_TO_M ** 2)
    q = 0.5 * rho * velocity_mps ** 2
    return weight_n / (q * wing_area_m2), velocity_mps, q


def _drag_lbf(cd, q_pa, wing_area_ft2):
    wing_area_m2 = wing_area_ft2 * (FT_TO_M ** 2)
    drag_n = cd * q_pa * wing_area_m2
    return drag_n / 4.4482216153  # N -> lbf


def _flight_condition(aero, engine, wing_area_ft2, mass_lbm, alt_ft, mach, throttle):
    """Required CL/CD/drag/thrust/fuel-flow at one (altitude, Mach, mass,
    throttle) point - the level-flight lift=weight approximation shared by
    every phase and by the climb-Mach search below, so there is exactly
    one place computing this instead of several copies that could drift
    apart. Returns (cl_req, v_mps, q_pa, cd, drag_lbf, thrust_lbf,
    fuel_flow_lbm_hr)."""
    cl_req, v_mps, q_pa = _required_cl(mass_lbm, mach, alt_ft, wing_area_ft2)
    cd, _alpha_deg = aero.cd_for_required_cl(alt_ft, mach, cl_req)
    drag_lbf = _drag_lbf(cd, q_pa, wing_area_ft2)
    thrust_lbf, fuel_flow_lbm_hr = engine.thrust_and_fuel_flow(mach, alt_ft, throttle)
    return cl_req, v_mps, q_pa, cd, drag_lbf, thrust_lbf, fuel_flow_lbm_hr


def _climb_rate_fpm(mass_lbm, thrust_lbf, drag_lbf, v_mps):
    """Excess-power rate of climb: ROC = (Thrust-Drag)*V/Weight, floored
    at zero (negative excess power means climb can't be sustained here,
    not that the aircraft is modeled as sinking - the caller's own
    min_climb_rate_fpm floor catches an inadequate climb well before this
    would ever reach zero). Returns (roc_mps, roc_fpm)."""
    weight_n = mass_lbm * LBM_TO_KG * G
    excess_power_w = (thrust_lbf - drag_lbf) * 4.4482216153 * v_mps
    roc_mps = excess_power_w / weight_n if excess_power_w > 0 else 0.0
    return roc_mps, roc_mps * 196.850394


def _raise_if_cl_exceeds_margin(direction, alt_ft, mach, mass_lbm, cl_req, cl_margin, max_cl):
    if cl_req > cl_margin * max_cl:
        raise LiftMarginError(
            f"{direction} at altitude={alt_ft:.0f} ft, Mach={mach:.3f}: "
            f"required CL={cl_req:.3f} exceeds {cl_margin:.0%} of this aero "
            f"table's tested max CL ({max_cl:.3f}) at mass={mass_lbm:.0f} lbm "
            f"- this aircraft cannot sustain level flight here at this weight; "
            f"not a numerical artifact, a real lift-margin shortfall."
        )


def fly_climb_or_descent(
    aero, engine, wing_area_ft2, mass_lbm,
    alt_start_ft, alt_end_ft, mach_start, mach_end,
    throttle, cl_margin, direction,
    alt_step_ft=500.0, min_climb_rate_fpm=300.0, mach_accel_step=0.01,
    mach_schedule_alt_end_ft=None,
):
    """Integrates altitude from alt_start_ft to alt_end_ft in alt_step_ft
    increments at a FIXED throttle setting. Mach is ramped linearly
    between mach_start/mach_end over the altitude range as the NOMINAL
    schedule. direction: 'climb' uses excess-power rate of climb, and can
    accelerate FASTER than that nominal ramp when needed (see
    min_climb_rate_fpm below); 'descent' uses an assumed flight-path
    angle at the nominal ramp's Mach directly (an idle/low-throttle
    engine can't be relied on for positive excess power the way a
    climbing engine can, so there is no margin to search for there).

    mach_schedule_alt_end_ft: the altitude at which the nominal Mach ramp
    is defined to reach mach_end, if different from alt_end_ft (default
    None uses alt_end_ft - today's behavior, unchanged for every existing
    caller). This matters whenever THIS call is only checking feasibility
    up to some altitude SHORT of the real, intended final altitude (e.g.
    probing "can it at least reach 23,000 ft" while the actual mission
    target is 35,000 ft): without this, the nominal ramp rate (Mach
    gained per foot of altitude) is silently RECOMPUTED to fit whatever
    alt_end_ft this particular call happens to use - a shorter alt_end_ft
    doesn't just truncate the same climb, it computes a genuinely
    DIFFERENT one (reaching a given Mach at a lower altitude for a
    shorter target). Demonstrated for real, not hypothetical: re-running
    this project's own smoke test with cruise_altitude_ft lowered in
    steps (35000 -> 25000 -> 23500 -> 23000, each time using the PREVIOUS
    run's achieved altitude as the next target) reported a DIFFERENT
    "how far did it get" each time and never converged, because each run
    silently asked a different question. Pass the real, intended final
    altitude here (independent of how far this call actually needs to
    check) to keep the schedule fixed and get a true, comparable
    truncation instead - see run_classical_mission's
    climb_schedule_reference_altitude_ft, which does exactly this.

    min_climb_rate_fpm: as thrust lapses with altitude, excess power at a
    FIXED (military) throttle setting can taper toward zero well before
    reaching the requested cruise altitude - the resulting climb rate
    doesn't go negative, it just gets very small, so a naive "excess
    power <= 0" check alone lets the integration grind through a handful
    of feet at a time with each step's dt_s (and therefore fuel burned)
    blowing up, producing a technically-non-crashing but physically
    absurd result (caught in testing: a synthetic case that should climb
    to 35,000 ft in single-digit minutes instead reported 199 minutes and
    more fuel burned in climb alone than the whole mission should need,
    because the last few thousand feet were being climbed at a few tens
    of feet per minute).

    Before treating a shortfall against min_climb_rate_fpm as this
    throttle setting's practical ceiling, the climb branch first tries
    ACCELERATING at that same altitude - scanning Mach upward in
    mach_accel_step increments, bounded by mach_end (this phase's own
    target Mach, e.g. the cruise Mach for the climb phase) - before
    giving up. This matters for a low-aspect-ratio wing: found on this
    project's real aircraft data that a comfortable-looking CL (well
    under the aero table's tested max) can still mean induced drag has
    eaten nearly all of military thrust at the nominal schedule's Mach,
    while a faster Mach at the SAME altitude (moving toward the wing's
    min-drag speed - a low-AR wing well below that speed trades a little
    parasite drag for a lot less induced drag) restores real margin. A
    fixed linear Mach-vs-altitude ramp alone can under-predict what this
    aircraft can actually do, and can also under-predict a shortfall that
    only appears PARTWAY up the climb even after the start of climb has
    already been fixed (e.g. via find_min_climb_start_mach), because
    thrust keeps lapsing with altitude faster than a slow linear ramp's
    Mach increase compensates for. Once a step accelerates, later steps
    never fall back below that Mach even if the nominal ramp would - nothing
    here calls for slowing back down, only for speeding up when margin
    runs thin. 300 fpm is a conventional practical/service-ceiling-
    adjacent floor - once climb rate drops below it even at mach_end,
    further altitude gain at this throttle setting is not a realistic
    part of a cross-country climb schedule, so THAT is treated as this
    throttle setting's practical ceiling and reported as such, not
    silently integrated through.

    Returns (time_s, distance_nmi, fuel_burned_lbm, final_mass_lbm), or
    raises RuntimeError with the exact altitude/condition if the aero
    table's tested CL range can't support level flight there, or if climb
    rate collapses below min_climb_rate_fpm - even after accelerating to
    mach_end - before reaching alt_end_ft (a real finding either way -
    not enough lift or thrust margin - not a numerical failure)."""
    n_steps = max(1, int(round(abs(alt_end_ft - alt_start_ft) / alt_step_ft)))
    alts = np.linspace(alt_start_ft, alt_end_ft, n_steps + 1)
    mach_ref_end_ft = alt_end_ft if mach_schedule_alt_end_ft is None else mach_schedule_alt_end_ft
    machs = mach_start + (mach_end - mach_start) * (alts - alt_start_ft) / (mach_ref_end_ft - alt_start_ft)

    total_time_s = 0.0
    total_dist_nmi = 0.0
    total_fuel_lbm = 0.0
    mass = mass_lbm
    mach_floor = mach_start  # climb only: an acceleration is never undone later

    for i in range(n_steps):
        alt_mid = 0.5 * (alts[i] + alts[i + 1])
        mach_mid = 0.5 * (machs[i] + machs[i + 1])

        if direction == "climb":
            mach_mid = max(mach_mid, mach_floor)
            cl_req, v_mps, q_pa, cd, drag_lbf, thrust_lbf, fuel_flow_lbm_hr = _flight_condition(
                aero, engine, wing_area_ft2, mass, alt_mid, mach_mid, throttle
            )
            roc_mps, roc_fpm = _climb_rate_fpm(mass, thrust_lbf, drag_lbf, v_mps)

            mach_try = mach_mid
            while roc_fpm < min_climb_rate_fpm and mach_try < mach_end - 1e-9:
                mach_try = min(mach_try + mach_accel_step, mach_end)
                cl_req, v_mps, q_pa, cd, drag_lbf, thrust_lbf, fuel_flow_lbm_hr = _flight_condition(
                    aero, engine, wing_area_ft2, mass, alt_mid, mach_try, throttle
                )
                roc_mps, roc_fpm = _climb_rate_fpm(mass, thrust_lbf, drag_lbf, v_mps)
            mach_mid = mach_try

            if roc_fpm < min_climb_rate_fpm:
                raise ThrustMarginError(
                    f"climb at altitude={alt_mid:.0f} ft, mass={mass:.0f} lbm: climb "
                    f"rate has dropped to {roc_fpm:.0f} ft/min (thrust={thrust_lbf:.0f} "
                    f"lbf, drag={drag_lbf:.0f} lbf at Mach={mach_mid:.3f}) even after "
                    f"accelerating to this phase's target Mach ({mach_end:.3f}) looking "
                    f"for more thrust margin - still below the {min_climb_rate_fpm:.0f} "
                    f"ft/min practical floor. This throttle setting's real ceiling is "
                    f"below the requested cruise altitude ({alt_end_ft:.0f} ft); it "
                    f"cannot be fixed by flying faster within this phase's Mach range. "
                    f"This is a real thrust-margin finding, not a numerical failure: "
                    f"either the requested cruise altitude is too high for a non-"
                    f"afterburning climb at this weight, or reaching it needs a higher "
                    f"climb throttle than modeled here.",
                    partial={
                        "time_s": total_time_s, "distance_nmi": total_dist_nmi,
                        "fuel_lbm": total_fuel_lbm, "mass_lbm": mass,
                        "altitude_ft": alts[i],
                    },
                )
            _raise_if_cl_exceeds_margin(direction, alt_mid, mach_mid, mass, cl_req, cl_margin, aero.max_cl)
            mach_floor = mach_mid
        else:  # descent: assumed flight-path angle, not excess power
            cl_req, v_mps, q_pa, cd, drag_lbf, thrust_lbf, fuel_flow_lbm_hr = _flight_condition(
                aero, engine, wing_area_ft2, mass, alt_mid, mach_mid, throttle
            )
            _raise_if_cl_exceeds_margin(direction, alt_mid, mach_mid, mass, cl_req, cl_margin, aero.max_cl)

        d_alt_ft = alts[i + 1] - alts[i]
        d_alt_m = d_alt_ft * FT_TO_M

        if direction == "climb":
            dt_s = abs(d_alt_m) / roc_mps
        else:
            descent_angle_rad = np.radians(3.0)  # standard ~3 deg descent
            roc_mps = v_mps * np.sin(descent_angle_rad)
            dt_s = abs(d_alt_m) / roc_mps

        dx_m = (v_mps ** 2 - roc_mps ** 2) ** 0.5 * dt_s if v_mps > roc_mps else v_mps * dt_s
        d_fuel_lbm = fuel_flow_lbm_hr * (dt_s / 3600.0)

        total_time_s += dt_s
        total_dist_nmi += dx_m / (NMI_TO_FT * FT_TO_M)
        total_fuel_lbm += d_fuel_lbm
        mass -= d_fuel_lbm

    return total_time_s, total_dist_nmi, total_fuel_lbm, mass


def fly_cruise(aero, engine, wing_area_ft2, mass_lbm, cruise_alt_ft, cruise_mach,
               distance_nmi, cl_margin, dist_step_nmi=10.0):
    """Step-cruise at fixed Mach/altitude: throttle solved each step so
    thrust exactly equals drag (level, unaccelerated flight)."""
    n_steps = max(1, int(round(distance_nmi / dist_step_nmi)))
    step_nmi = distance_nmi / n_steps
    mass = mass_lbm
    total_time_s = 0.0
    total_fuel_lbm = 0.0

    for _ in range(n_steps):
        cl_req, v_mps, q_pa = _required_cl(mass, cruise_mach, cruise_alt_ft, wing_area_ft2)
        if cl_req > cl_margin * aero.max_cl:
            raise LiftMarginError(
                f"cruise at altitude={cruise_alt_ft:.0f} ft, Mach={cruise_mach:.3f}: "
                f"required CL={cl_req:.3f} exceeds {cl_margin:.0%} of this aero "
                f"table's tested max CL ({aero.max_cl:.3f}) at mass={mass:.0f} lbm "
                f"- this aircraft cannot sustain cruise here at this weight; a real "
                f"lift-margin shortfall, not a numerical artifact."
            )
        cd, _alpha_deg = aero.cd_for_required_cl(cruise_alt_ft, cruise_mach, cl_req)
        drag_lbf = _drag_lbf(cd, q_pa, wing_area_ft2)
        throttle, fuel_flow_lbm_hr, achievable = engine.throttle_for_required_thrust(
            cruise_mach, cruise_alt_ft, drag_lbf
        )
        if not achievable:
            raise ThrustMarginError(
                f"cruise at altitude={cruise_alt_ft:.0f} ft, Mach={cruise_mach:.3f}: "
                f"required thrust ({drag_lbf:.0f} lbf) exceeds this engine's full-"
                f"throttle thrust at mass={mass:.0f} lbm - a real thrust shortfall, "
                f"not a numerical failure."
            )
        dt_s = (step_nmi * NMI_TO_FT * FT_TO_M) / v_mps
        d_fuel_lbm = fuel_flow_lbm_hr * (dt_s / 3600.0)
        total_time_s += dt_s
        total_fuel_lbm += d_fuel_lbm
        mass -= d_fuel_lbm

    return total_time_s, distance_nmi, total_fuel_lbm, mass


def find_min_climb_start_mach(
    aero, engine, wing_area_ft2, gross_mass_lbm, climb_throttle,
    min_climb_rate_fpm=300.0, safety_margin_fpm=200.0, cl_margin=0.9,
    mach_scan=np.arange(0.20, 0.95, 0.01),
):
    """Scans Mach at SEA LEVEL and the aircraft's full gross mass (the
    worst case for weight-driven induced drag - heaviest, and lowest
    altitude so highest required CL for a given Mach) to find the lowest
    Mach where excess thrust at climb_throttle clears min_climb_rate_fpm
    plus a safety margin.

    A low-aspect-ratio wing (this project's own wing-loading-scaled
    configs are typically AR ~2-3) has a LARGE induced-drag penalty at
    low speed/high CL - simply picking a slow, comfortable-sounding climb
    Mach (or even a CL-margin-based Mach targeting stall margin, a
    DIFFERENT constraint - the retired Aviary pipeline computed one this
    way) can leave inadequate THRUST margin even though there is plenty
    of LIFT margin. Caught exactly this running the real aircraft data
    for the first time: CL
    was a comfortable 0.71 (well under this table's ~1.0 max), but
    induced drag at that CL nearly equaled available military thrust at
    Mach 0.3 near sea level. A single Mach scan at the worst-case
    condition (no iterative solver, so it can't fail to converge) finds a
    starting Mach with real thrust margin instead of guessing one.

    cl_margin: must match the SAME value passed to fly_climb_or_descent
    (run_classical_mission ensures this). Skipping candidates with a
    looser threshold here was a real bug caught in testing: at
    climb_throttle=1.0 this scan could return a Mach clearing the THRUST
    check while still exceeding fly_climb_or_descent's own (stricter)
    LIFT-margin check, so the climb it "found a start for" immediately
    raised a lift-margin RuntimeError on its very first step - a starting
    Mach is only real if it satisfies the same constraint the climb
    itself will be judged against.

    Returns the found Mach, or raises RuntimeError if nothing in
    mach_scan clears the margin (a real finding - this aircraft may need
    afterburner to get established in a climb at all, at this weight)."""
    for mach in mach_scan:
        cl_req, v_mps, _q_pa = _required_cl(gross_mass_lbm, mach, 0.0, wing_area_ft2)
        if cl_req > cl_margin * aero.max_cl:
            continue  # fails the SAME lift-margin test fly_climb_or_descent enforces
        _, v_mps, _, _, drag_lbf, thrust_lbf, _ = _flight_condition(
            aero, engine, wing_area_ft2, gross_mass_lbm, 0.0, mach, climb_throttle
        )
        _, roc_fpm = _climb_rate_fpm(gross_mass_lbm, thrust_lbf, drag_lbf, v_mps)
        if roc_fpm >= min_climb_rate_fpm + safety_margin_fpm:
            return round(float(mach), 2)
    raise ThrustMarginError(
        f"No Mach in the scanned range [{mach_scan[0]:.2f}, {mach_scan[-1]:.2f}] gives "
        f"adequate climb-rate margin at sea level, mass={gross_mass_lbm:.0f} lbm, "
        f"throttle={climb_throttle} - this aircraft may need a higher climb throttle "
        f"(afterburner) to get established in a climb at all at this weight. Try "
        f"climb_throttle=1.0."
    )


def run_classical_mission(
    geom_stem, wing_area_ft2, gross_mass_lbm, design_range_nmi,
    cruise_mach, cruise_altitude_ft,
    climb_mach_initial=None, climb_mach_final=None,
    descent_mach_final=0.3,
    mach_list=None, altitude_list=None,
    custom_engine_deck_path=None,
    engine_t_sl_dry_lbf=17800.0, engine_t_sl_ab_lbf=29100.0,
    engine_throttle_ratio=1.07, engine_type="low_bypass_mixed_flow_turbofan",
    num_engines=1,
    climb_throttle=0.5, climb_throttle_fallback=1.0,
    descent_throttle=0.15, cl_margin=0.9,
    climb_schedule_reference_altitude_ft=None,
):
    """Runs the full climb/cruise/descent mission and returns a dict of
    results. Raises RuntimeError (with a specific altitude/Mach/mass
    condition, not a stack of optimizer internals) if the aircraft
    genuinely cannot complete the mission as specified - EXCEPT for one
    case: if the climb itself cannot reach cruise_altitude_ft at any
    throttle tried (climb_throttle, then climb_throttle_fallback), that
    is reported as a normal return value instead
    (results['climb_completed'] = False, results['cruise'] and
    ['descent'] = None, results['failure_reason'] holds the same message
    the exception would have carried) rather than raised - a baseline-
    vs-RCS-shaped-config comparison needs "this config can't complete
    the climb" to be an ordinary, comparable outcome (how far did it
    get?), not a crash, since some configs are EXPECTED to fail this
    check. Every other failure mode (a lift-margin shortfall in any
    phase, a cruise/descent thrust shortfall, climb+descent distance
    alone exceeding the design range) still raises - only this one,
    demonstrated failure mode has been made to degrade gracefully so far.

    num_engines: engine_t_sl_dry_lbf/engine_t_sl_ab_lbf are PER-ENGINE
    published F100-PW-229 spec values (the same convention the retired
    Aviary pipeline used for Aircraft.Engine.REFERENCE_SLS_THRUST) -
    num_engines scales
    the deck's thrust AND fuel flow up to the whole aircraft's installed
    total. Defaults to 1 because this function has no way to know the
    real engine count on its own, but confirmed this session that this
    project's actual aircraft is a TWIN-engine design: at num_engines=1,
    gross_mass_lbm=83,800 against a single F100-PW-229-class engine gives
    T/W~0.35 at full afterburner (a modern fighter's is typically
    ~0.9-1.2), which was the dominant reason an earlier feasibility
    check found this aircraft couldn't sustain climb past a few thousand
    feet - re-running with num_engines=2 (same aero, same mass, only
    thrust and fuel flow doubled) confirmed the fix: achieved altitude
    went from 23,000 ft to 34,500 ft against the same 35,000 ft target.

    climb_mach_initial: if None (the default), computed automatically via
    find_min_climb_start_mach() - a real, non-guessed starting speed with
    adequate climb-THRUST margin for THIS aircraft's own aero/mass/engine,
    not a flat placeholder. Pass an explicit value to override.

    climb_throttle_fallback: if the climb at climb_throttle (military
    power by default) hits a genuine THRUST shortfall (ThrustMarginError
    - not enough thrust to sustain min_climb_rate_fpm even after
    accelerating within the phase's own Mach range), the climb is retried
    in full from sea level at this higher throttle instead of failing the
    whole mission outright - this is exactly what a real fighter does
    when military power can't get it to altitude: it uses afterburner.
    Found on this project's own real aircraft data, not a hypothetical:
    at military power, drag can exceed available thrust outright (climb
    rate pinned at 0, not just below the practical floor) well below the
    design cruise altitude. A LiftMarginError is never retried this way -
    more throttle cannot produce more lift, so a lift shortfall is always
    a real, final failure. Set to None (or <= climb_throttle) to disable
    the fallback and try only climb_throttle - a shortfall then still
    degrades gracefully per the class docstring above, just without a
    retry at a different throttle first.
    results['climb_throttle_used'] records which throttle the reported
    climb numbers actually came from, since a fallback climb burns
    substantially more fuel than a military-power one and that must stay
    visible in the report, not silently absorbed into "the fuel burn".

    climb_schedule_reference_altitude_ft: the altitude the climb's Mach
    ramp is defined to reach climb_mach_final at, if different from
    cruise_altitude_ft (default None uses cruise_altitude_ft, matching
    every call before this parameter existed). Only matters when
    cruise_altitude_ft here is a SHORTER checkpoint than the aircraft's
    real, intended cruise altitude - e.g. probing "does it at least clear
    23,000 ft" while the real mission target is 35,000 ft. Demonstrated
    as a real point of confusion, not hypothetical: without this,
    lowering cruise_altitude_ft doesn't just check a shorter climb, it
    silently recomputes a DIFFERENT, faster-accelerating Mach schedule
    (reaching climb_mach_final in fewer feet) - re-running this project's
    own smoke test with cruise_altitude_ft stepped down (35000 -> 25000
    -> 23500 -> 23000, each time using the previous run's
    achieved_altitude_ft as the next target) reported a DIFFERENT "how
    far did it get" every time and never converged, because each run was
    silently answering a different question. Pass the aircraft's real,
    intended cruise altitude here (independent of the shorter
    cruise_altitude_ft being checked) to make repeated, shorter probes
    genuine truncations of the SAME schedule, so they finally agree with
    each other - or better, just run once at the real cruise_altitude_ft
    and trust results['achieved_altitude_ft'] directly; no probing
    required, since the integration already stops exactly where the
    real shortfall is."""
    climb_mach_final = climb_mach_final if climb_mach_final is not None else cruise_mach
    climb_schedule_reference_altitude_ft = (
        cruise_altitude_ft if climb_schedule_reference_altitude_ft is None
        else climb_schedule_reference_altitude_ft
    )

    aero = AeroTable(geom_stem, expected_machs=set(mach_list) if mach_list else None,
                      expected_altitudes=set(altitude_list) if altitude_list else None)

    if custom_engine_deck_path:
        engine_deck_path = custom_engine_deck_path
    else:
        engine_deck_path = build_deck(
            out_dir=os.path.join(vsp_setup.GENERATED_FILES, "engines"),
            deck_name="classical_mission_f100_pw229_simplified.deck",
            t_sl_dry=engine_t_sl_dry_lbf, t_sl_ab=engine_t_sl_ab_lbf,
            throttle_ratio=engine_throttle_ratio, engine_type=engine_type,
        )
    engine = EngineTable(engine_deck_path, num_engines=num_engines)

    if climb_mach_initial is None:
        climb_mach_initial = find_min_climb_start_mach(
            aero, engine, wing_area_ft2, gross_mass_lbm, climb_throttle, cl_margin=cl_margin,
        )
        print(f"   [climb] computed start-of-climb Mach={climb_mach_initial:.2f} "
              f"(minimum Mach with adequate climb-rate margin at sea level/full "
              f"gross mass/throttle={climb_throttle})")

    climb_throttle_used = climb_throttle
    unrecoverable = None  # (ThrustMarginError, throttle_it_was_tried_at), or None
    try:
        t_climb, d_climb, fuel_climb, mass_after_climb = fly_climb_or_descent(
            aero, engine, wing_area_ft2, gross_mass_lbm,
            alt_start_ft=0.0, alt_end_ft=cruise_altitude_ft,
            mach_start=climb_mach_initial, mach_end=climb_mach_final,
            throttle=climb_throttle, cl_margin=cl_margin, direction="climb",
            mach_schedule_alt_end_ft=climb_schedule_reference_altitude_ft,
        )
    except ThrustMarginError as e:
        if climb_throttle_fallback is None or climb_throttle_fallback <= climb_throttle:
            unrecoverable = (e, climb_throttle)
        else:
            print(f"   [climb] military power (throttle={climb_throttle}) hit a real "
                  f"thrust shortfall - {e}\n"
                  f"   [climb] retrying the full climb at climb_throttle_fallback="
                  f"{climb_throttle_fallback} (this WILL burn substantially more fuel "
                  f"in climb - a real cost of needing more power to reach this cruise "
                  f"altitude at this weight, not a numerical artifact).")
            climb_throttle_used = climb_throttle_fallback
            try:
                t_climb, d_climb, fuel_climb, mass_after_climb = fly_climb_or_descent(
                    aero, engine, wing_area_ft2, gross_mass_lbm,
                    alt_start_ft=0.0, alt_end_ft=cruise_altitude_ft,
                    mach_start=climb_mach_initial, mach_end=climb_mach_final,
                    throttle=climb_throttle_fallback, cl_margin=cl_margin, direction="climb",
                    mach_schedule_alt_end_ft=climb_schedule_reference_altitude_ft,
                )
            except ThrustMarginError as e2:
                unrecoverable = (e2, climb_throttle_fallback)

    if unrecoverable is not None:
        # A real, final finding - not enough thrust to reach the requested
        # cruise altitude at ANY throttle this function is willing to try -
        # not something more retrying can fix. Reported as a normal
        # "not feasible" result (with however far the climb DID get, so
        # different configs can still be compared by how close they came)
        # rather than as a crash, since this is an expected, meaningful
        # outcome for a baseline-vs-RCS-shaped-config comparison: some
        # configs are supposed to fail this check. Every OTHER failure
        # mode in this module (a lift-margin shortfall, a cruise/descent
        # shortfall, climb+descent alone exceeding the design range) still
        # raises - only this specific, now-recovery-exhausted climb
        # failure degrades to a return value.
        exc, throttle_tried = unrecoverable
        p = exc.partial or {"time_s": 0.0, "distance_nmi": 0.0, "fuel_lbm": 0.0,
                             "mass_lbm": gross_mass_lbm, "altitude_ft": 0.0}
        print(f"   [climb] MISSION NOT FEASIBLE: could not reach {cruise_altitude_ft:.0f} "
              f"ft even at throttle={throttle_tried} - reached {p['altitude_ft']:.0f} ft "
              f"before the climb-rate floor was violated with no more throttle to try.")
        return {
            "engine_deck_path": engine_deck_path,
            "climb_completed": False,
            "failure_phase": "climb",
            "failure_reason": str(exc),
            "climb_throttle_used": throttle_tried,
            "target_cruise_altitude_ft": cruise_altitude_ft,
            "achieved_altitude_ft": p["altitude_ft"],
            "climb": {"time_s": p["time_s"], "distance_nmi": p["distance_nmi"], "fuel_lbm": p["fuel_lbm"]},
            "cruise": None,
            "descent": None,
            "total_range_nmi": p["distance_nmi"],
            "total_fuel_lbm": p["fuel_lbm"],
            "gross_mass_lbm": gross_mass_lbm,
            "final_mass_lbm": p["mass_lbm"],
            "design_range_nmi": design_range_nmi,
        }

    t_descent_est, d_descent_est, fuel_descent_est, _ = fly_climb_or_descent(
        aero, engine, wing_area_ft2, mass_after_climb * 0.97,  # rough pre-estimate for distance budgeting
        alt_start_ft=cruise_altitude_ft, alt_end_ft=500.0,
        mach_start=cruise_mach, mach_end=descent_mach_final,
        throttle=descent_throttle, cl_margin=cl_margin, direction="descent",
    )

    cruise_distance_nmi = design_range_nmi - d_climb - d_descent_est
    if cruise_distance_nmi <= 0:
        raise RuntimeError(
            f"Climb ({d_climb:.1f} nmi) + descent ({d_descent_est:.1f} nmi) ground "
            f"distance alone exceeds the {design_range_nmi:.0f} nmi design range - "
            f"this mission profile doesn't fit the design range at all, independent "
            f"of fuel."
        )

    t_cruise, d_cruise, fuel_cruise, mass_after_cruise = fly_cruise(
        aero, engine, wing_area_ft2, mass_after_climb, cruise_altitude_ft, cruise_mach,
        cruise_distance_nmi, cl_margin=cl_margin,
    )

    t_descent, d_descent, fuel_descent, mass_after_descent = fly_climb_or_descent(
        aero, engine, wing_area_ft2, mass_after_cruise,
        alt_start_ft=cruise_altitude_ft, alt_end_ft=500.0,
        mach_start=cruise_mach, mach_end=descent_mach_final,
        throttle=descent_throttle, cl_margin=cl_margin, direction="descent",
    )

    total_range_nmi = d_climb + d_cruise + d_descent
    total_fuel_lbm = fuel_climb + fuel_cruise + fuel_descent

    return {
        "engine_deck_path": engine_deck_path,
        "climb_completed": True,
        "climb": {"time_s": t_climb, "distance_nmi": d_climb, "fuel_lbm": fuel_climb},
        "cruise": {"time_s": t_cruise, "distance_nmi": d_cruise, "fuel_lbm": fuel_cruise},
        "descent": {"time_s": t_descent, "distance_nmi": d_descent, "fuel_lbm": fuel_descent},
        "total_range_nmi": total_range_nmi,
        "total_fuel_lbm": total_fuel_lbm,
        "gross_mass_lbm": gross_mass_lbm,
        "final_mass_lbm": mass_after_descent,
        "design_range_nmi": design_range_nmi,
        "climb_throttle_used": climb_throttle_used,
    }


def print_results(results, fuel_capacity_lbm):
    print("\n" + "=" * 62)
    print("CLASSICAL MISSION RESULTS (no optimizer - direct integration)")
    print("=" * 62)
    if results.get("climb_completed") is False:
        # Cruise/descent never ran - the climb itself couldn't reach the
        # requested cruise altitude at any throttle tried. A real, final
        # result (see run_classical_mission's climb_throttle_fallback
        # docs), not a partial/broken run - reported in full so a
        # baseline-vs-RCS-shaped-config comparison still has a number to
        # compare (how far each config's climb actually got).
        c = results["climb"]
        print(f"  VERDICT: MISSION NOT FEASIBLE (could not complete the climb)")
        print(f"  Climb throttle tried  : {results['climb_throttle_used']:.2f}")
        print(f"  Target cruise altitude: {results['target_cruise_altitude_ft']:.0f} ft")
        print(f"  Altitude achieved     : {results['achieved_altitude_ft']:.0f} ft")
        print(f"  Distance covered      : {c['distance_nmi']:.1f} nmi (of "
              f"{results['design_range_nmi']:.0f} nmi design range)")
        print(f"  Time elapsed          : {c['time_s'] / 60.0:.1f} min")
        print(f"  Fuel burned           : {c['fuel_lbm']:.1f} lbm")
        print("-" * 62)
        print(f"  Reason: {results['failure_reason']}")
        print("=" * 62)
        return

    range_margin = results["total_range_nmi"] - results["design_range_nmi"]
    fuel_margin = fuel_capacity_lbm - results["total_fuel_lbm"]
    if results.get("climb_throttle_used") is not None:
        print(f"  Climb throttle used   : {results['climb_throttle_used']:.2f} "
              f"{'(military power)' if results['climb_throttle_used'] <= 0.5 else '(FALLBACK - higher than military power, see [climb] notes above)'}")
    for phase in ("climb", "cruise", "descent"):
        p = results[phase]
        print(f"  {phase.capitalize():8s}  {p['distance_nmi']:8.1f} nmi  "
              f"{p['time_s'] / 60.0:6.1f} min  {p['fuel_lbm']:9.1f} lbm fuel")
    print("-" * 62)
    print(f"  Total range flown     : {results['total_range_nmi']:.1f} nmi")
    print(f"  Design range required : {results['design_range_nmi']:.1f} nmi")
    print(f"  RANGE MARGIN          : {range_margin:+.1f} nmi")
    print(f"  Total fuel burned     : {results['total_fuel_lbm']:.1f} lbm")
    print(f"  Fuel capacity (loaded): {fuel_capacity_lbm:.1f} lbm")
    print(f"  FUEL MARGIN           : {fuel_margin:+.1f} lbm")
    verdict = "FEASIBLE" if (range_margin >= -0.5 and fuel_margin >= 0) else "NOT FEASIBLE"
    print(f"  VERDICT: MISSION {verdict}")
    print("=" * 62)


if __name__ == "__main__":
    # Standalone smoke test — uses this project's real geometry/mass
    # placeholders so it finds the same aero CSVs when run directly.
    # num_engines=2: confirmed this session that this project's real
    # aircraft is twin-engine - see run_classical_mission's num_engines
    # docstring for why single-engine gave an unrealistically low T/W.
    results = run_classical_mission(
        geom_stem="SSAM_final_geom_to_be_used_scaled_by_19_simplified",
        wing_area_ft2=843.018026816014,
        gross_mass_lbm=83800.00623707,
        design_range_nmi=400.0,
        cruise_mach=0.6,
        cruise_altitude_ft=35000.0,
        mach_list=[0.2, 0.4, 0.6],
        altitude_list=[0.0, 15000.0, 35000.0],
        num_engines=2,
    )
    print_results(results, fuel_capacity_lbm=24590.81)
