# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:09:02 2026

@author: KK
"""

import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # for vsp_setup

import aviary.api as av
from aviary.api import Aircraft, Mission
from phase_info import phase_info
from external_aero_builder import ExternalAeroBuilder
from build_engine_deck import build_deck, T_SL_DRY

AIRCRAFT_CSV = os.path.join(os.path.dirname(__file__), "ssam_aircraft.csv")

# F-16C published reference specs (the mass-fraction / wing-loading basis
# below, and eventually the real full-scale run's mass values directly).
F16C_EMPTY_MASS_LBM = 18238.0
F16C_GROSS_MASS_LBM = 26463.0
F16C_FUEL_MASS_LBM  = 6972.0
F16C_WING_AREA_FT2  = 300.0   # published F-16C reference wing area

# Dividing the real F-16C masses by 19 (a *linear* scale factor) made no
# sense against this test config's wing area (1.174343 ft^2, from
# ssam_aircraft.csv) - that wing is a small, unrelated dev geometry, not a
# true 1/19 scale-down of the real jet. That combination gave a wing
# loading of ~1187 lbm/ft^2 (vs. the real F-16C's ~88 lbm/ft^2) - physically
# impossible (would need CL~9.5 for level flight) - which is exactly why
# the mission's climb aerodynamics Newton solve couldn't converge: no
# achievable alpha/CL exists at that wing loading anywhere in the polar
# table. Scaling mass to match the real F-16C's wing loading against this
# wing's *actual* area keeps the run physically self-consistent instead.
# Still a placeholder, not real masses — matches this project's real
# full-scale run still pending (real x19 geometry + true F-16C mass values,
# unscaled). If climb still fails to converge with this fix, the likely
# next culprit is CL demand at the low-Mach/low-altitude start of climb
# outrunning the -8..12 deg alpha polar's covered CL range.
TEST_WING_AREA_FT2 = 1.174343  # must match aircraft:wing:area in ssam_aircraft.csv
_wing_loading_lbm_per_ft2 = F16C_GROSS_MASS_LBM / F16C_WING_AREA_FT2
GROSS_MASS_LBM = _wing_loading_lbm_per_ft2 * TEST_WING_AREA_FT2
EMPTY_MASS_LBM = GROSS_MASS_LBM * (F16C_EMPTY_MASS_LBM / F16C_GROSS_MASS_LBM)
FUEL_MASS_LBM  = GROSS_MASS_LBM * (F16C_FUEL_MASS_LBM / F16C_GROSS_MASS_LBM)
print(f"   [mass] wing-loading-scaled GROSS={GROSS_MASS_LBM:.2f} lbm, "
      f"EMPTY={EMPTY_MASS_LBM:.2f} lbm, FUEL={FUEL_MASS_LBM:.2f} lbm")

def main():
    engine_deck_path = build_deck()

    from aviary.utils.named_values import NamedValues

    GEOM_STEM = "SSAM_final_geom_to_be_used_NOT_scaled_by_19_nozzle_mod"  # match whatever IMPORT_FILE you're testing with
    external_aero = ExternalAeroBuilder(geom_stem=GEOM_STEM)

    aero_data = NamedValues()
    aero_data.set_val("altitude", external_aero._data["altitude"], "ft")
    aero_data.set_val("mach", external_aero._data["mach"], "unitless")
    aero_data.set_val("angle_of_attack", external_aero._data["alpha"], "deg")

    for phase_name in ("climb", "cruise", "descent"):
        phase_info[phase_name]["subsystem_options"]["aerodynamics"]["aero_data"] = aero_data

    prob = av.AviaryProblem()
    prob.load_inputs(AIRCRAFT_CSV, phase_info)
    prob.load_external_subsystems([external_aero])
    
    # fixed mass overrides — settings:mass_method stays FLOPS (CSV), but since
    # EMPTY_MASS is set here on aviary_inputs *before* build_model()/setup(),
    # Aviary's override-variable mechanism disconnects FLOPS's own empirical
    # EmptyMass computation and treats this fixed value as the input instead
    # (see aviary/subsystems/premission.py:override_aviary_vars). GROSS_MASS
    # is already a plain input in FLOPS's mass buildup (never computed), so
    # setting it here is a normal input assignment, not an override.
    prob.aviary_inputs.set_val(Aircraft.Design.EMPTY_MASS, EMPTY_MASS_LBM, units="lbm")
    prob.aviary_inputs.set_val(Aircraft.Design.GROSS_MASS, GROSS_MASS_LBM, units="lbm")
    prob.aviary_inputs.set_val(Aircraft.Fuel.TOTAL_CAPACITY, FUEL_MASS_LBM, units="lbm")

    engine_options = av.AviaryValues()
    engine_options.set_val(Aircraft.Engine.DATA_FILE, engine_deck_path)
    engine_options.set_val(Aircraft.Engine.NUM_ENGINES, 1)
    engine_options.set_val(Aircraft.Engine.NUM_WING_ENGINES, 0)
    engine_options.set_val(Aircraft.Engine.NUM_FUSELAGE_ENGINES, 1)
    # Left at its default (True, unset by us) this crashed FLOPS's EngineMass
    # component: `np.where(scale_mass)` on a 0-d array ("Calling nonzero on
    # 0d arrays is not allowed"). Setting it explicitly avoids that shape bug.
    # We don't need FLOPS's thrust-scaled engine-mass equation anyway, since
    # EMPTY_MASS is overridden wholesale above — False just means "don't scale".
    engine_options.set_val(Aircraft.Engine.SCALE_MASS, False)
    # REFERENCE_MASS/REFERENCE_SLS_THRUST are also engine-model *options* in
    # the installed aviary==1.0.1 (add_aviary_option, not add_aviary_input) —
    # left unset they fell back to a bare-float default instead of an array,
    # crashing the same way SCALE_MASS did (`ref_engine_mass[scale_idx]`,
    # 'float' object is not subscriptable). With SCALE_MASS=False, scale_idx
    # is empty for every engine, so REFERENCE_MASS becomes Aircraft.Engine.MASS
    # unscaled/unchanged. 3740 lbm is the commonly cited F100-PW-229 dry
    # weight — approximate, not sourced from Pratt & Whitney data, same
    # placeholder tier as the rest of this deck. REFERENCE_SLS_THRUST reuses
    # the deck's own T_SL_DRY so thrust_ratio stays consistent at 1.0.
    engine_options.set_val(Aircraft.Engine.REFERENCE_MASS, 3740.0, units="lbm")
    engine_options.set_val(Aircraft.Engine.REFERENCE_SLS_THRUST, T_SL_DRY, units="lbf")
    engine_deck = av.EngineDeck(name="f100", options=engine_options)
    av.preprocess_propulsion(aviary_options=prob.aviary_inputs, engine_models=[engine_deck])
    
    prob.check_and_preprocess_inputs()

    from build_aero_polar import reshape_to_grid
    lift_grid, drag_grid = reshape_to_grid(external_aero._data)
    prob.aviary_inputs.set_val(Aircraft.Design.LIFT_POLAR, lift_grid, units="unitless")
    prob.aviary_inputs.set_val(Aircraft.Design.DRAG_POLAR, drag_grid, units="unitless")
    
    prob.check_and_preprocess_inputs()
    prob.build_model()

    # NO driver / design variables / objective — pure fixed-input analysis
    prob.setup()
    prob.run_model()

    print("\n--- RESULTS ---")
    fuel_residual = prob.get_val(Mission.Constraints.MASS_RESIDUAL)
    print(f"Fuel mass residual: {fuel_residual}  (positive = margin, negative = infeasible)")

if __name__ == "__main__":
    main()