# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:04:36 2026

@author: KK
"""

"""
Simplified F100-PW-229 engine deck, built from published static thrust
ratings + a standard density-lapse approximation. NOT real proprietary
engine test data — an explicit, stated placeholder.
"""

import os
import numpy as np
import vsp_setup

T_SL_DRY = 17800.0   # lbf, published F100-PW-229 dry static thrust
T_SL_AB  = 29100.0   # lbf, published F100-PW-229 afterburner static thrust
TSFC_DRY = 0.8        # lb/(lb*hr), typical for this engine class
TSFC_AB  = 2.0        # lb/(lb*hr), typical for this engine class

ALTITUDES_FT = [0, 10000, 20000, 30000, 35000, 40000]
MACHS        = [0.0, 0.2, 0.4, 0.6]   # 0.0 required — EngineDeck needs a sea-level static (M=0, alt=0) point
THROTTLES    = [0.0, 0.5, 1.0]   # 0=idle, 0.5=dry, 1.0=full afterburner

def isa_density_ratio(alt_ft):
    alt_m = alt_ft * 0.3048
    T = 288.15 - 0.0065 * alt_m
    rho = 1.225 * (T / 288.15) ** 4.2561
    return rho / 1.225

def build_deck():
    out_path = os.path.join(vsp_setup.VSP_FILES, "..", "engines", "f100_pw229_simplified.deck")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    lines = [
        "# Simplified F100-PW-229 engine deck",
        "# Based on published static thrust (dry 17,800 lbf / AB 29,100 lbf)",
        "# and a simple density-ratio thrust lapse model - NOT real engine test data.",
        "Mach_Number,Altitude(ft),Throttle,Net_Thrust(lbf),Fuel_Flow_Rate(lbm/h)",
    ]
    for alt in ALTITUDES_FT:
        sigma = isa_density_ratio(alt)
        for mach in MACHS:
            for throttle in THROTTLES:
                if throttle <= 0.5:
                    t_frac = throttle / 0.5
                    thrust = T_SL_DRY * t_frac * sigma
                    fuel_flow = thrust * TSFC_DRY
                else:
                    ab_frac = (throttle - 0.5) / 0.5
                    thrust = (T_SL_DRY + ab_frac * (T_SL_AB - T_SL_DRY)) * sigma
                    tsfc = TSFC_DRY + ab_frac * (TSFC_AB - TSFC_DRY)
                    fuel_flow = thrust * tsfc
                lines.append(f"{mach},{alt},{throttle},{thrust:.1f},{fuel_flow:.1f}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Engine deck written: {out_path}")
    return out_path

if __name__ == "__main__":
    build_deck()