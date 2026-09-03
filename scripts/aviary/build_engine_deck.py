# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:04:36 2026

@author: KK
"""

"""
Simplified engine deck generator, built from published static thrust
ratings + Mattingly & Heiser's installed thrust-lapse model. NOT real
proprietary engine test data — an explicit, stated placeholder, but the
thrust-lapse SHAPE (how thrust falls off with Mach and altitude) is now a
cited textbook formula instead of a generic guess.

All engine-specific numbers are passed in by the caller (see main.py's
AVIARY / MISSION CONFIG section) rather than hardcoded here, so there is
one place to edit them.

Thrust lapse: Mattingly, J. D. and Heiser, W. H., "Aircraft Engine
Design", Ch. 2 "Constraint Analysis", Sec. 2.3.2 "Propulsion",
Eqs. (2.52a), (2.52b), (2.54a), (2.54b) — "low bypass ratio, mixed flow
turbofan" case, which is the F100-PW-229/F110 engine class (F-16/F-15).

    theta  = T/T_std,  theta0 = theta*(1 + [(gamma-1)/2]*M0**2)
    delta  = P/P_std,  delta0 = delta*(1 + [(gamma-1)/2]*M0**2)**(gamma/(gamma-1))

    Maximum power (afterburner), Eq. 2.54a:
        theta0 <= TR:  alpha = delta0
        theta0 >  TR:  alpha = delta0*(1 - 3.5*(theta0-TR)/theta0)

    Military power (dry), Eq. 2.54b:
        theta0 <= TR:  alpha = 0.6*delta0
        theta0 >  TR:  alpha = 0.6*delta0*(1 - 3.8*(theta0-TR)/theta0)

alpha ("installed thrust lapse ratio") is thrust as a fraction of
sea-level-static UNINSTALLED MAXIMUM (afterburner) thrust, T_SL_AB — i.e.
alpha is normalized against t_sl_ab, not t_sl_dry independently. This is
confirmed by the numbers themselves: at sea level static with TR=1.0,
Eq. 2.54b gives military thrust = 0.6*t_sl_ab = 0.6*29100 = 17460 lbf,
within 2% of the published F100-PW-229 dry static thrust (17800 lbf) —
build_deck() below prints this same cross-check every run.

Altitude/temperature terms (theta, delta) are derived from
vsp_setup.isa_atmosphere() (the same two-layer troposphere+stratosphere
ISA model used for the aero Reynolds-number calc) via the ideal gas law
delta = (rho/rho_std)*(T/T_std), rather than a second, separately-
maintained atmosphere model.

TR (throttle ratio) is an engine-specific empirical constant (Mattingly &
Heiser Appendix D): the theta0 breakpoint above which the engine is
temperature-limited rather than flat-rated. TR=1.0 for a standard-day-
rated engine (the default here); the book's own worked example for this
engine class sweeps TR=1.00-1.08. The real F100-PW-229's TR isn't in the
excerpt available for this project — 1.0 is the standard-day baseline,
not a verified engine-specific value.
"""

import os

GAMMA = 1.4
T_STD_K = 288.15
RHO_STD = 1.225


def _theta_delta(alt_ft):
    """Static temperature/pressure ratios (theta, delta) at alt_ft, ISA."""
    import vsp_setup
    T, rho, _, _ = vsp_setup.isa_atmosphere(alt_ft)
    theta = T / T_STD_K
    sigma = rho / RHO_STD
    delta = sigma * theta   # ideal gas law: P/P_std = (rho/rho_std)*(T/T_std)
    return theta, delta


def _mattingly_thrust_lapse(theta, delta, mach, throttle_ratio, power_setting):
    """
    Installed thrust lapse ratio alpha for a low-bypass, mixed-flow
    turbofan (Mattingly & Heiser Eqs. 2.54a/2.54b — see module docstring).
    power_setting: "military" (dry) or "max" (afterburner).
    """
    theta0 = theta * (1.0 + (GAMMA - 1) / 2.0 * mach**2)
    delta0 = delta * (1.0 + (GAMMA - 1) / 2.0 * mach**2) ** (GAMMA / (GAMMA - 1))

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

    return max(0.0, alpha)   # defensive clamp — formula can go negative far outside the fitted regime


def build_deck(
    out_dir,
    deck_name="engine_simplified.deck",
    t_sl_dry=17800.0,
    t_sl_ab=29100.0,
    tsfc_dry=0.8,
    tsfc_ab=2.0,
    altitudes_ft=(0, 10000, 20000, 30000, 35000, 40000),
    machs=(0.0, 0.2, 0.4, 0.6),   # 0.0 required — EngineDeck needs a sea-level static (M=0, alt=0) point
    throttles=(0.0, 0.5, 1.0),    # 0=idle, 0.5=military/dry, 1.0=full afterburner
    throttle_ratio=1.0,
):
    """Write a simplified engine deck to <out_dir>/<deck_name> and return its path."""
    out_path = os.path.join(out_dir, deck_name)
    os.makedirs(out_dir, exist_ok=True)

    # Sea-level-static cross-check — see module docstring. Flags loudly if
    # t_sl_dry/t_sl_ab/throttle_ratio don't agree with each other instead
    # of silently using two disconnected numbers for the same quantity.
    theta_sl, delta_sl = _theta_delta(0.0)
    alpha_mil_sl = _mattingly_thrust_lapse(theta_sl, delta_sl, 0.0, throttle_ratio, "military")
    predicted_dry_sl = alpha_mil_sl * t_sl_ab
    disagreement_pct = 100.0 * abs(predicted_dry_sl - t_sl_dry) / t_sl_dry
    print(f"   [engine deck] Mattingly SL-static military-thrust check: "
          f"formula predicts {predicted_dry_sl:.0f} lbf vs. published "
          f"t_sl_dry={t_sl_dry:.0f} lbf ({disagreement_pct:.1f}% difference)")
    if disagreement_pct > 15.0:
        print(f"   ⚠️  >15% disagreement — check throttle_ratio, or t_sl_dry/t_sl_ab values")

    lines = [
        f"# Simplified engine deck - {deck_name}",
        "# Thrust lapse: Mattingly & Heiser, Aircraft Engine Design, Ch.2",
        "# Sec 2.3.2, Eqs (2.52a/b),(2.54a/b) - low bypass ratio, mixed",
        f"# flow turbofan (F100-PW-229/F110 class), throttle_ratio TR={throttle_ratio}.",
        f"# T_SL_AB={t_sl_ab:.0f} lbf is the formula's reference thrust;",
        f"# t_sl_dry={t_sl_dry:.0f} lbf used only for the SL-static cross-check above.",
        "# NOT real F100-PW-229 test data.",
        "Mach_Number,Altitude(ft),Throttle,Net_Thrust(lbf),Fuel_Flow_Rate(lbm/h)",
    ]
    for alt in altitudes_ft:
        theta, delta = _theta_delta(alt)
        for mach in machs:
            thrust_mil = _mattingly_thrust_lapse(theta, delta, mach, throttle_ratio, "military") * t_sl_ab
            thrust_max = _mattingly_thrust_lapse(theta, delta, mach, throttle_ratio, "max") * t_sl_ab
            for throttle in throttles:
                if throttle <= 0.5:
                    # Mattingly's model only defines the two rated power
                    # points (military/max); idle->military is our own
                    # linear interpolation, same as before this rewrite.
                    t_frac = throttle / 0.5
                    thrust = thrust_mil * t_frac
                    fuel_flow = thrust * tsfc_dry
                else:
                    ab_frac = (throttle - 0.5) / 0.5
                    thrust = thrust_mil + ab_frac * (thrust_max - thrust_mil)
                    tsfc = tsfc_dry + ab_frac * (tsfc_ab - tsfc_dry)
                    fuel_flow = thrust * tsfc
                lines.append(f"{mach},{alt},{throttle},{thrust:.1f},{fuel_flow:.1f}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Engine deck written: {out_path}")
    return out_path
