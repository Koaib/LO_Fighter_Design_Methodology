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
from build_engine_deck import build_deck

AIRCRAFT_CSV = os.path.join(os.path.dirname(__file__), "ssam_aircraft.csv")

# fixed F-16C-derived mass values — see placeholder table
EMPTY_MASS_LBM = 18238.0/19
GROSS_MASS_LBM = 26463.0/19
FUEL_MASS_LBM  = 6972.0/19

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