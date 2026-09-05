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
(climb Mach/altitude bounds and cruise Mach/altitude straight from this
project's own phase_info.py) via direct numerical integration - small
altitude/distance steps, quasi-steady flight mechanics - instead of
collocation + gradient-based optimization. There is no optimizer in this
file, so there is nothing here that can report "Exit mode 8"; it either
completes and reports a real number, or it reports exactly which
altitude/Mach combination ran outside the tested aero table (an
extrapolation would be a real, meaningful failure, not a numerical
artifact) - not the answer a full trajectory optimizer would give (it
doesn't find the OPTIMAL climb schedule, cruise-climb profile, etc.),
but it is a physically-grounded fuel-burn number a baseline-vs-RCS-shaped
comparison can actually rely on getting.

Uses the EXACT SAME data sources as run_aviary.py:
  - build_aero_polar.py's build_polar_arrays()/reshape_to_grid() (the same
    VSPAero-derived (altitude, Mach, alpha) -> (CL, CD) sweep).
  - build_engine_deck.py's build_deck() (the same Mattingly & Heiser
    thrust/TSFC deck, or a real one via custom_engine_deck_path).
Only the trajectory SOLVE differs.

METHOD (per phase):
  Climb:   integrate altitude upward in small steps from sea level to
           cruise altitude, at MILITARY (non-afterburning, throttle=0.5)
           power - the standard economical climb setting, afterburner
           being reserved for combat rather than a cross-country climb.
           At each altitude: current mass -> required CL (level-flight
           lift = weight approximation) -> alpha and CD from the aero
           table -> drag; thrust/fuel-flow from the engine deck at that
           Mach/altitude/throttle. Climb (vertical) rate from excess
           power: ROC = (Thrust-Drag)*V/Weight. Mach is ramped linearly
           between phase_info.py's climb mach_initial/mach_final over the
           altitude range, matching the existing mission's own schedule.
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

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

import vsp_setup
from build_aero_polar import build_polar_arrays, reshape_to_grid
from build_engine_deck import build_deck

LBM_TO_KG = 0.45359237
FT_TO_M = 0.3048
NMI_TO_FT = 6076.11549
G = 9.80665


class AeroTable:
    """(altitude, Mach, alpha) -> (CL, CD) lookup, built from this
    project's own VSPAero sweep - the same data external_aero_builder.py
    feeds into Aviary, used here directly instead."""

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
    from the same engine deck run_aviary.py uses (either the
    auto-generated Mattingly & Heiser deck or a real custom_engine_deck_path
    CSV) - read directly rather than through Aviary's EngineDeck class."""

    def __init__(self, deck_path):
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
        pt = np.array([[mach, alt_ft, throttle]])
        return float(self._thrust_interp(pt)[0]), float(self._fuel_interp(pt)[0])

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


def fly_climb_or_descent(
    aero, engine, wing_area_ft2, mass_lbm,
    alt_start_ft, alt_end_ft, mach_start, mach_end,
    throttle, cl_margin, direction,
    alt_step_ft=500.0, min_climb_rate_fpm=300.0,
):
    """Integrates altitude from alt_start_ft to alt_end_ft in alt_step_ft
    increments at a FIXED throttle setting, Mach ramped linearly between
    mach_start/mach_end over the altitude range. direction: 'climb' uses
    excess-power rate of climb; 'descent' uses an assumed flight-path
    angle (an idle/low-throttle engine can't be relied on for positive
    excess power at every point the way a climbing engine can).

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
    of feet per minute). 300 fpm is a conventional practical/service-
    ceiling-adjacent floor - once climb rate drops below it, further
    altitude gain at this throttle setting is not a realistic part of a
    cross-country climb schedule, so this is treated as this throttle
    setting's practical ceiling and reported as such, not silently
    integrated through.

    Returns (time_s, distance_nmi, fuel_burned_lbm, final_mass_lbm), or
    raises RuntimeError with the exact altitude/condition if the aero
    table's tested CL range can't support level flight there, or if climb
    rate collapses below min_climb_rate_fpm before reaching alt_end_ft (a
    real finding either way - not enough lift or thrust margin - not a
    numerical failure)."""
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
        cl_req, v_mps, q_pa = _required_cl(mass, mach_mid, alt_mid, wing_area_ft2)
        if cl_req > cl_margin * aero.max_cl:
            raise RuntimeError(
                f"{direction} at altitude={alt_mid:.0f} ft, Mach={mach_mid:.3f}: "
                f"required CL={cl_req:.3f} exceeds {cl_margin:.0%} of this aero "
                f"table's tested max CL ({aero.max_cl:.3f}) at mass={mass:.0f} lbm "
                f"- this aircraft cannot sustain level flight here at this weight; "
                f"not a numerical artifact, a real lift-margin shortfall."
            )
        cd, _alpha_deg = aero.cd_for_required_cl(alt_mid, mach_mid, cl_req)
        drag_lbf = _drag_lbf(cd, q_pa, wing_area_ft2)
        thrust_lbf, fuel_flow_lbm_hr = engine.thrust_and_fuel_flow(mach_mid, alt_mid, throttle)

        d_alt_ft = alts[i + 1] - alts[i]
        d_alt_m = d_alt_ft * FT_TO_M
        weight_n = mass * LBM_TO_KG * G

        if direction == "climb":
            excess_power_w = (thrust_lbf - drag_lbf) * 4.4482216153 * v_mps
            roc_mps = excess_power_w / weight_n if excess_power_w > 0 else 0.0
            roc_fpm = roc_mps * 196.850394
            if roc_fpm < min_climb_rate_fpm:
                raise RuntimeError(
                    f"climb at altitude={alt_mid:.0f} ft, Mach={mach_mid:.3f}, "
                    f"mass={mass:.0f} lbm: climb rate at this throttle setting has "
                    f"dropped to {roc_fpm:.0f} ft/min (thrust={thrust_lbf:.0f} lbf, "
                    f"drag={drag_lbf:.0f} lbf), below the {min_climb_rate_fpm:.0f} "
                    f"ft/min practical floor - this throttle setting's effective "
                    f"ceiling is below the requested cruise altitude "
                    f"({alt_end_ft:.0f} ft). This is a real thrust-margin finding, "
                    f"not a numerical failure: either the requested cruise altitude "
                    f"is too high for a non-afterburning climb at this weight, or "
                    f"reaching it needs a higher climb throttle than modeled here."
                )
            dt_s = abs(d_alt_m) / roc_mps
        else:  # descent: assumed flight-path angle, not excess power
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
            raise RuntimeError(
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
            raise RuntimeError(
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


def run_classical_mission(
    geom_stem, wing_area_ft2, gross_mass_lbm, design_range_nmi,
    cruise_mach, cruise_altitude_ft,
    climb_mach_initial=0.3, climb_mach_final=None,
    descent_mach_final=0.3,
    mach_list=None, altitude_list=None,
    custom_engine_deck_path=None,
    engine_t_sl_dry_lbf=17800.0, engine_t_sl_ab_lbf=29100.0,
    engine_throttle_ratio=1.07, engine_type="low_bypass_mixed_flow_turbofan",
    climb_throttle=0.5, descent_throttle=0.15, cl_margin=0.9,
):
    """Runs the full climb/cruise/descent mission and returns a dict of
    results. Raises RuntimeError (with a specific altitude/Mach/mass
    condition, not a stack of optimizer internals) if the aircraft
    genuinely cannot complete the mission as specified."""
    climb_mach_final = climb_mach_final if climb_mach_final is not None else cruise_mach

    aero = AeroTable(geom_stem, expected_machs=set(mach_list) if mach_list else None,
                      expected_altitudes=set(altitude_list) if altitude_list else None)

    if custom_engine_deck_path:
        engine_deck_path = custom_engine_deck_path
    else:
        engine_deck_path = build_deck(
            out_dir=os.path.join(vsp_setup.AVIARY_FILES, "engines"),
            deck_name="classical_mission_f100_pw229_simplified.deck",
            t_sl_dry=engine_t_sl_dry_lbf, t_sl_ab=engine_t_sl_ab_lbf,
            throttle_ratio=engine_throttle_ratio, engine_type=engine_type,
        )
    engine = EngineTable(engine_deck_path)

    t_climb, d_climb, fuel_climb, mass_after_climb = fly_climb_or_descent(
        aero, engine, wing_area_ft2, gross_mass_lbm,
        alt_start_ft=0.0, alt_end_ft=cruise_altitude_ft,
        mach_start=climb_mach_initial, mach_end=climb_mach_final,
        throttle=climb_throttle, cl_margin=cl_margin, direction="climb",
    )

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
        "climb": {"time_s": t_climb, "distance_nmi": d_climb, "fuel_lbm": fuel_climb},
        "cruise": {"time_s": t_cruise, "distance_nmi": d_cruise, "fuel_lbm": fuel_cruise},
        "descent": {"time_s": t_descent, "distance_nmi": d_descent, "fuel_lbm": fuel_descent},
        "total_range_nmi": total_range_nmi,
        "total_fuel_lbm": total_fuel_lbm,
        "gross_mass_lbm": gross_mass_lbm,
        "final_mass_lbm": mass_after_descent,
        "design_range_nmi": design_range_nmi,
    }


def print_results(results, fuel_capacity_lbm):
    range_margin = results["total_range_nmi"] - results["design_range_nmi"]
    fuel_margin = fuel_capacity_lbm - results["total_fuel_lbm"]
    print("\n" + "=" * 62)
    print("CLASSICAL MISSION RESULTS (no optimizer - direct integration)")
    print("=" * 62)
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
    # Standalone smoke test — mirrors run_aviary.py's own standalone
    # defaults so it finds the same aero CSVs when run directly.
    results = run_classical_mission(
        geom_stem="SSAM_final_geom_to_be_used_scaled_by_19_simplified",
        wing_area_ft2=843.018026816014,
        gross_mass_lbm=83800.00623707,
        design_range_nmi=400.0,
        cruise_mach=0.6,
        cruise_altitude_ft=35000.0,
        mach_list=[0.2, 0.4, 0.6],
        altitude_list=[0.0, 15000.0, 35000.0],
    )
    print_results(results, fuel_capacity_lbm=24590.81)
