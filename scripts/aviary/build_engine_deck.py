# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:04:36 2026

@author: KK
"""

"""
Simplified engine deck generator, built from published static thrust
ratings + Mattingly & Heiser's installed thrust-lapse AND TSFC models.
NOT real proprietary engine test data — an explicit, stated placeholder,
but both the thrust-lapse and TSFC SHAPES (how they vary with Mach and
altitude) are now cited textbook formulas instead of generic guesses.

All engine-specific numbers are passed in by the caller (see main.py's
AVIARY / MISSION CONFIG section) rather than hardcoded here, so there is
one place to edit them.

=============================================================================
ENGINE CLASSES — thrust lapse and TSFC are both engine-ARCHITECTURE-
specific. Mattingly & Heiser's book gives a different equation per engine
class (turbojet, high-bypass turbofan, low-bypass mixed-flow turbofan,
turboprop), not one universal formula. build_deck()'s engine_type
parameter selects which class is used. Passing an unimplemented
engine_type raises NotImplementedError rather than silently reusing the
wrong class's numbers.

Implemented (IMPLEMENTED_ENGINE_TYPES), both thrust lapse AND TSFC:
  - "low_bypass_mixed_flow_turbofan" — the default, and the F100-PW-229/
    F110 engine class (F-16/F-15) matching this deck's actual engine.
    Thrust: Ch.2 Sec.2.3.2 Eqs. 2.54a (max/afterburner), 2.54b (military).
    TSFC:   Ch.3 Sec.3.3.2 Eqs. 3.55a (military), 3.55b (max/afterburner).
  - "turbojet" — same dry/afterburner two-rated-point structure, fits this
    file's throttle model cleanly.
    Thrust: Eqs. 2.55a (max), 2.55b (military).
    TSFC:   Eqs. 3.56a (military), 3.56b (max).

NOT implemented (deliberately, not just untried):
  - "high_bypass_turbofan" (thrust: Eq. 2.53; TSFC: Eq. 3.54) — this class
    has no afterburner, i.e. a single rated power point, which doesn't
    fit this file's idle -> military -> max three-point throttle model
    (built for afterburning engines). Adding it needs a small
    architecture decision (how a non-AB engine's "throttles" grid should
    work here), not just pasting the formula.
  - turboprop (thrust: Eq. 2.56; TSFC: Eq. 3.57) — the thrust equation's
    OCR extraction had ambiguous bracket placement, unverified against
    the actual textbook page image. Not implementing an unverified
    formula.

=============================================================================
THRUST LAPSE

    theta  = T/T_std,  theta0 = theta*(1 + [(gamma-1)/2]*M0**2)
    delta  = P/P_std,  delta0 = delta*(1 + [(gamma-1)/2]*M0**2)**(gamma/(gamma-1))

alpha ("installed thrust lapse ratio") is thrust as a fraction of
sea-level-static UNINSTALLED MAXIMUM (afterburner) thrust, T_SL_AB — i.e.
alpha is normalized against t_sl_ab, not t_sl_dry independently. For
low_bypass_mixed_flow_turbofan this is confirmed by the numbers
themselves: at sea level static, Eq. 2.54b gives military thrust =
0.6*t_sl_ab = 0.6*29100 = 17460 lbf, within 2% of the published
F100-PW-229 dry static thrust (17800 lbf) — build_deck() below prints
this same cross-check every run, for whichever engine_type is active.

Low bypass ratio, mixed flow turbofan — Eq. 2.54a/b:
    Max power:      theta0<=TR: alpha=delta0
                     theta0> TR: alpha=delta0*(1-3.5*(theta0-TR)/theta0)
    Military power:  theta0<=TR: alpha=0.6*delta0
                     theta0> TR: alpha=0.6*delta0*(1-3.8*(theta0-TR)/theta0)

Turbojet — Eq. 2.55a/b:
    Max power:      alpha=delta0*(1-0.3*(theta0-1)-0.1*sqrt(M0))                              [theta0<=TR]
                     alpha=delta0*(1-0.3*(theta0-1)-0.1*sqrt(M0)-1.5*(theta0-TR)/theta0)       [theta0>TR]
    Military power:  alpha=0.8*delta0*(1-0.16*sqrt(M0))                                        [theta0<=TR]
                     alpha=0.8*delta0*(1-0.16*sqrt(M0)-24*(theta0-TR)/((9+M0)*theta0))          [theta0>TR]

=============================================================================
TSFC (Ch.3 Sec.3.3.2, Eqs. 3.54-3.57) — units 1/hr (numerically
lbm-fuel/(lbf-thrust*hr) in English units). Uses theta0 and Mach only —
NO altitude/pressure (delta) or throttle-ratio dependence in these
correlations; the book flags them as design-estimate correlations "for
advanced engines in the 2010 era," not manufacturer-specific data.

    Low bypass mixed turbofan, military: TSFC = (0.9 + 0.30*M0)*sqrt(theta0)   Eq. 3.55a
    Low bypass mixed turbofan, max:      TSFC = (1.6 + 0.27*M0)*sqrt(theta0)   Eq. 3.55b
    Turbojet, military:                  TSFC = (1.1 + 0.30*M0)*sqrt(theta0)   Eq. 3.56a
    Turbojet, max:                       TSFC = (1.5 + 0.23*M0)*sqrt(theta0)   Eq. 3.56b

=============================================================================
ALTITUDE/TEMPERATURE terms (theta, delta) are derived from
vsp_setup.isa_atmosphere() (the same two-layer troposphere+stratosphere
ISA model used for the aero Reynolds-number calc) via the ideal gas law
delta = (rho/rho_std)*(T/T_std), rather than a second, separately-
maintained atmosphere model.

THROTTLE RATIO (TR) is an engine-specific empirical constant (Mattingly &
Heiser Appendix D, Eq. D.6): the theta0 breakpoint above which the
engine control system is temperature-limited (Tt4-limited) rather than
flat-rated. There is no lookup table of TR by engine class in the book —
TR is a control-system design choice, derived, not tabulated. The
closest available anchor for this project is the book's own AAF
(supercruise fighter, F100-class engine) worked example, which sweeps
TR=1.00-1.08 and settles on TR=1.07 (Ch.2 example, Fig.2.E1b/Table 2.E2)
— used as the default here since it's the closest textbook analog to the
F100-PW-229, though still not the real manufacturer TR value (not in any
excerpt available for this project). build_deck() prints a sea-level-
static thrust cross-check every run — if TR is changed, watch that check
for a large disagreement.

PARTIAL THROTTLE — the book only defines the two discrete rated points
(military and max/afterburner) via the equations above; it does NOT give
a closed-form model for thrust/TSFC between idle and military, or
between military and max (that needs full off-design cycle analysis,
Ch.5, not covered here). The idle->military and military->max
interpolation in build_deck() below is this project's own modeling
choice, not sourced from the book — confirmed explicitly when the
thrust-lapse/TSFC equations above were extracted.
"""

import os

GAMMA = 1.4
T_STD_K = 288.15
RHO_STD = 1.225

# Engine classes with verified Mattingly & Heiser thrust-lapse AND TSFC
# equations actually implemented below. Add to this set only alongside
# real equations from the book — never as a stand-in reusing another
# class's numbers. See module docstring for what's excluded and why.
IMPLEMENTED_ENGINE_TYPES = {"low_bypass_mixed_flow_turbofan", "turbojet"}


def _theta_delta(alt_ft):
    """Static temperature/pressure ratios (theta, delta) at alt_ft, ISA."""
    import vsp_setup
    T, rho, _, _ = vsp_setup.isa_atmosphere(alt_ft)
    theta = T / T_STD_K
    sigma = rho / RHO_STD
    delta = sigma * theta   # ideal gas law: P/P_std = (rho/rho_std)*(T/T_std)
    return theta, delta


def _check_engine_type(engine_type):
    if engine_type not in IMPLEMENTED_ENGINE_TYPES:
        raise NotImplementedError(
            f"No verified Mattingly & Heiser equations for "
            f"engine_type={engine_type!r} yet. Implemented: "
            f"{sorted(IMPLEMENTED_ENGINE_TYPES)}. To add another class, "
            f"paste its thrust-lapse AND TSFC equations from Mattingly & "
            f"Heiser, Aircraft Engine Design, Ch.2 Sec.2.3.2 / Ch.3 "
            f"Sec.3.3.2 — don't reuse another class's numbers."
        )


def _mattingly_thrust_lapse(theta, delta, mach, throttle_ratio, power_setting, engine_type):
    """
    Installed thrust lapse ratio alpha, from the Mattingly & Heiser
    equation for the given engine_type (see module docstring — different
    engine architectures use different equations, this is NOT universal).
    power_setting: "military" (dry) or "max" (afterburner).
    """
    _check_engine_type(engine_type)

    theta0 = theta * (1.0 + (GAMMA - 1) / 2.0 * mach**2)
    delta0 = delta * (1.0 + (GAMMA - 1) / 2.0 * mach**2) ** (GAMMA / (GAMMA - 1))

    if engine_type == "low_bypass_mixed_flow_turbofan":
        # Eqs. 2.54a (max power/afterburner), 2.54b (military power/dry)
        if power_setting == "max":
            if theta0 <= throttle_ratio:
                alpha = delta0
            else:
                alpha = delta0 * (1.0 - 3.5 * (theta0 - throttle_ratio) / theta0)
        elif power_setting == "military":
            if theta0 <= throttle_ratio:
                alpha = 0.6 * delta0
            else:
                alpha = 0.6 * delta0 * (1.0 - 3.8 * (theta0 - throttle_ratio) / theta0)
        else:
            raise ValueError("power_setting must be 'military' or 'max'")

    elif engine_type == "turbojet":
        # Eqs. 2.55a (max power/afterburner), 2.55b (military power/dry)
        sqrt_m = mach ** 0.5
        if power_setting == "max":
            common = 1.0 - 0.3 * (theta0 - 1.0) - 0.1 * sqrt_m
            if theta0 <= throttle_ratio:
                alpha = delta0 * common
            else:
                alpha = delta0 * (common - 1.5 * (theta0 - throttle_ratio) / theta0)
        elif power_setting == "military":
            common = 1.0 - 0.16 * sqrt_m
            if theta0 <= throttle_ratio:
                alpha = 0.8 * delta0 * common
            else:
                alpha = 0.8 * delta0 * (common - 24.0 * (theta0 - throttle_ratio) / ((9.0 + mach) * theta0))
        else:
            raise ValueError("power_setting must be 'military' or 'max'")

    return max(0.0, alpha)   # defensive clamp — formula can go negative far outside the fitted regime


def _mattingly_tsfc(theta, mach, power_setting, engine_type):
    """
    TSFC (1/hr) from Mattingly & Heiser Eqs. 3.55a/b (low bypass mixed
    turbofan) / 3.56a/b (turbojet) — see module docstring. Uses theta0
    and Mach only; no altitude/pressure (delta) or throttle_ratio term in
    these correlations. power_setting: "military" or "max".
    """
    _check_engine_type(engine_type)

    theta0 = theta * (1.0 + (GAMMA - 1) / 2.0 * mach**2)
    sqrt_theta0 = theta0 ** 0.5

    if engine_type == "low_bypass_mixed_flow_turbofan":
        if power_setting == "military":
            tsfc = (0.9 + 0.30 * mach) * sqrt_theta0    # Eq. 3.55a
        elif power_setting == "max":
            tsfc = (1.6 + 0.27 * mach) * sqrt_theta0    # Eq. 3.55b
        else:
            raise ValueError("power_setting must be 'military' or 'max'")

    elif engine_type == "turbojet":
        if power_setting == "military":
            tsfc = (1.1 + 0.30 * mach) * sqrt_theta0    # Eq. 3.56a
        elif power_setting == "max":
            tsfc = (1.5 + 0.23 * mach) * sqrt_theta0    # Eq. 3.56b
        else:
            raise ValueError("power_setting must be 'military' or 'max'")

    return tsfc


def build_deck(
    out_dir,
    deck_name="engine_simplified.deck",
    t_sl_dry=17800.0,
    t_sl_ab=29100.0,
    altitudes_ft=(0, 10000, 20000, 30000, 35000, 40000),
    machs=(0.0, 0.2, 0.4, 0.6),   # 0.0 required — EngineDeck needs a sea-level static (M=0, alt=0) point
    throttles=(0.0, 0.5, 1.0),    # 0=idle, 0.5=military/dry, 1.0=full afterburner
    throttle_ratio=1.07,
    # Mattingly & Heiser's TR — see module docstring "THROTTLE RATIO" for
    # why 1.07 (the AAF F100-class worked example), not a verified
    # F100-PW-229 manufacturer value.
    engine_type="low_bypass_mixed_flow_turbofan",
    # Selects which Mattingly & Heiser equations are used (thrust lapse
    # AND TSFC) — see module docstring / IMPLEMENTED_ENGINE_TYPES. Only
    # "low_bypass_mixed_flow_turbofan" and "turbojet" are implemented;
    # anything else raises NotImplementedError.
):
    """Write a simplified engine deck to <out_dir>/<deck_name> and return its path."""
    _check_engine_type(engine_type)

    out_path = os.path.join(out_dir, deck_name)
    os.makedirs(out_dir, exist_ok=True)

    # Sea-level-static cross-check — see module docstring. Flags loudly if
    # t_sl_dry/t_sl_ab/throttle_ratio don't agree with each other instead
    # of silently using two disconnected numbers for the same quantity.
    theta_sl, delta_sl = _theta_delta(0.0)
    alpha_mil_sl = _mattingly_thrust_lapse(theta_sl, delta_sl, 0.0, throttle_ratio, "military", engine_type)
    predicted_dry_sl = alpha_mil_sl * t_sl_ab
    disagreement_pct = 100.0 * abs(predicted_dry_sl - t_sl_dry) / t_sl_dry
    print(f"   [engine deck] Mattingly SL-static military-thrust check ({engine_type}): "
          f"formula predicts {predicted_dry_sl:.0f} lbf vs. published "
          f"t_sl_dry={t_sl_dry:.0f} lbf ({disagreement_pct:.1f}% difference)")
    if disagreement_pct > 15.0:
        print(f"   ⚠️  >15% disagreement — check throttle_ratio, or t_sl_dry/t_sl_ab values")

    lines = [
        f"# Simplified engine deck - {deck_name}",
        f"# Thrust lapse + TSFC: Mattingly & Heiser, Aircraft Engine Design,",
        f"# Ch.2 Sec.2.3.2 / Ch.3 Sec.3.3.2 - engine_type={engine_type},",
        f"# throttle_ratio TR={throttle_ratio}.",
        f"# T_SL_AB={t_sl_ab:.0f} lbf is the thrust formula's reference;",
        f"# t_sl_dry={t_sl_dry:.0f} lbf used only for the SL-static cross-check above.",
        "# NOT real engine test data.",
        "Mach_Number,Altitude(ft),Throttle,Net_Thrust(lbf),Fuel_Flow_Rate(lbm/h)",
    ]
    for alt in altitudes_ft:
        theta, delta = _theta_delta(alt)
        for mach in machs:
            thrust_mil = _mattingly_thrust_lapse(theta, delta, mach, throttle_ratio, "military", engine_type) * t_sl_ab
            thrust_max = _mattingly_thrust_lapse(theta, delta, mach, throttle_ratio, "max", engine_type) * t_sl_ab
            tsfc_mil = _mattingly_tsfc(theta, mach, "military", engine_type)
            tsfc_max = _mattingly_tsfc(theta, mach, "max", engine_type)
            for throttle in throttles:
                if throttle <= 0.5:
                    # Mattingly's model only defines the two rated power
                    # points (military/max); idle->military is our own
                    # linear interpolation — see module docstring
                    # "PARTIAL THROTTLE" (confirmed not in the book).
                    t_frac = throttle / 0.5
                    thrust = thrust_mil * t_frac
                    fuel_flow = thrust * tsfc_mil
                else:
                    ab_frac = (throttle - 0.5) / 0.5
                    thrust = thrust_mil + ab_frac * (thrust_max - thrust_mil)
                    tsfc = tsfc_mil + ab_frac * (tsfc_max - tsfc_mil)
                    fuel_flow = thrust * tsfc
                lines.append(f"{mach},{alt},{throttle},{thrust:.1f},{fuel_flow:.1f}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Engine deck written: {out_path}")
    return out_path
