# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:04:36 2026

@author: KK
"""

"""
Simplified engine deck generator, built from published static thrust
ratings + a standard density-lapse approximation. NOT real proprietary
engine test data — an explicit, stated placeholder.

All engine-specific numbers are passed in by the caller (see the USER
CONFIG block in run_aviary.py) rather than hardcoded here, so there is
one place to edit them.
"""

import os


def isa_density_ratio(alt_ft):
    alt_m = alt_ft * 0.3048
    T = 288.15 - 0.0065 * alt_m
    rho = 1.225 * (T / 288.15) ** 4.2561
    return rho / 1.225


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
):
    """Write a simplified engine deck to <out_dir>/<deck_name> and return its path."""
    out_path = os.path.join(out_dir, deck_name)
    os.makedirs(out_dir, exist_ok=True)

    lines = [
        f"# Simplified engine deck - {deck_name}",
        f"# Based on published static thrust (dry {t_sl_dry:.0f} lbf / AB {t_sl_ab:.0f} lbf)",
        "# and a simple density-ratio thrust lapse model - NOT real engine test data.",
        "Mach_Number,Altitude(ft),Throttle,Net_Thrust(lbf),Fuel_Flow_Rate(lbm/h)",
    ]
    for alt in altitudes_ft:
        sigma = isa_density_ratio(alt)
        for mach in machs:
            for throttle in throttles:
                if throttle <= 0.5:
                    t_frac = throttle / 0.5
                    thrust = t_sl_dry * t_frac * sigma
                    fuel_flow = thrust * tsfc_dry
                else:
                    ab_frac = (throttle - 0.5) / 0.5
                    thrust = (t_sl_dry + ab_frac * (t_sl_ab - t_sl_dry)) * sigma
                    tsfc = tsfc_dry + ab_frac * (tsfc_ab - tsfc_dry)
                    fuel_flow = thrust * tsfc
                lines.append(f"{mach},{alt},{throttle},{thrust:.1f},{fuel_flow:.1f}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Engine deck written: {out_path}")
    return out_path
