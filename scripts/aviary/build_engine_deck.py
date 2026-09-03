# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:04:36 2026

@author: KK
"""

"""
Simplified engine deck generator, built from published static thrust
ratings + a standard density-lapse approximation + a generic Mach-lapse
approximation. NOT real proprietary engine test data — an explicit,
stated placeholder.

All engine-specific numbers are passed in by the caller (see main.py's
AVIARY / MISSION CONFIG section) rather than hardcoded here, so there is
one place to edit them.

Altitude lapse uses vsp_setup.isa_atmosphere() (the same two-layer
troposphere+stratosphere ISA model used for the aero Reynolds-number
calc) rather than a second, separately-maintained copy — this file used
to have its own incomplete troposphere-only formula that silently gave
~3% too-high density (and thus thrust) above the 11 km/36,089 ft
tropopause, which the default altitude grid's 40,000 ft point hit.
"""

import os


def _isa_density_ratio(alt_ft):
    import vsp_setup
    _, rho, _, _ = vsp_setup.isa_atmosphere(alt_ft)
    RHO_SL = 1.225
    return rho / RHO_SL


def build_deck(
    out_dir,
    deck_name="engine_simplified.deck",
    t_sl_dry=17800.0,
    t_sl_ab=29100.0,
    tsfc_dry=0.8,
    tsfc_ab=2.0,
    altitudes_ft=(0, 10000, 20000, 30000, 35000, 40000),
    machs=(0.0, 0.2, 0.4, 0.6),   # 0.0 required — EngineDeck needs a sea-level static (M=0, alt=0) point
    throttles=(0.0, 0.5, 1.0),    # 0=idle, 0.5=dry, 1.0=full afterburner
    mach_lapse_coeff=0.3,
    # Generic subsonic ram-drag thrust-lapse coefficient for a low-bypass
    # military turbofan class engine — thrust_factor = 1 - mach_lapse_coeff*M,
    # so thrust falls off roughly linearly with Mach at fixed throttle/
    # altitude (captures the basic trend: increasing inlet/ram drag outpaces
    # ram-recovery at these speeds). This is a generic textbook-class
    # engineering approximation, NOT derived from real F100-PW-229 lapse
    # data, same placeholder tier as tsfc_dry/tsfc_ab above — adjust this
    # coefficient (or replace with a real lapse curve) if the mission's
    # fuel-burn numbers need to be more than a pipeline-plumbing check.
    # mach=0 is unaffected (factor=1), matching the sea-level-static point.
):
    """Write a simplified engine deck to <out_dir>/<deck_name> and return its path."""
    out_path = os.path.join(out_dir, deck_name)
    os.makedirs(out_dir, exist_ok=True)

    lines = [
        f"# Simplified engine deck - {deck_name}",
        f"# Based on published static thrust (dry {t_sl_dry:.0f} lbf / AB {t_sl_ab:.0f} lbf)",
        "# and a simple density-ratio + linear Mach-ram-drag lapse model",
        f"# (mach_lapse_coeff={mach_lapse_coeff}) - NOT real engine test data.",
        "Mach_Number,Altitude(ft),Throttle,Net_Thrust(lbf),Fuel_Flow_Rate(lbm/h)",
    ]
    for alt in altitudes_ft:
        sigma = _isa_density_ratio(alt)
        for mach in machs:
            mach_factor = max(0.0, 1.0 - mach_lapse_coeff * mach)
            lapse = sigma * mach_factor
            for throttle in throttles:
                if throttle <= 0.5:
                    t_frac = throttle / 0.5
                    thrust = t_sl_dry * t_frac * lapse
                    fuel_flow = thrust * tsfc_dry
                else:
                    ab_frac = (throttle - 0.5) / 0.5
                    thrust = (t_sl_dry + ab_frac * (t_sl_ab - t_sl_dry)) * lapse
                    tsfc = tsfc_dry + ab_frac * (tsfc_ab - tsfc_dry)
                    fuel_flow = thrust * tsfc
                lines.append(f"{mach},{alt},{throttle},{thrust:.1f},{fuel_flow:.1f}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Engine deck written: {out_path}")
    return out_path
