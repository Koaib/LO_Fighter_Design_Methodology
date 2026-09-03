# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:03:49 2026

@author: KK
"""

"""
External aero subsystem: feeds VSPAero-derived lift/drag polars into Aviary,
completely replacing Aviary's internal FLOPS/GASP aero calculation.
"""

import aviary.api as av

from build_aero_polar import build_polar_arrays


class ExternalAeroBuilder(av.AerodynamicsBuilder):
    def __init__(self, geom_stem, expected_machs=None, expected_altitudes=None, name="external_aero"):
        super().__init__(name)
        self._data = build_polar_arrays(
            geom_stem,
            expected_machs=expected_machs,
            expected_altitudes=expected_altitudes,
        )

    
    def build_pre_mission(self, aviary_inputs, subsystem_options=None):
    # No custom component needed here: GASP's tabular_cruise aerodynamics
    # method (set in phase_info.py) reads Aircraft.Design.LIFT_POLAR /
    # DRAG_POLAR directly from aviary_inputs as fixed parameters (set via
    # prob.aviary_inputs.set_val() in run_aviary.py, correctly shaped by
    # reshape_to_grid()). A component here promoting the same names would
    # conflict with that mechanism, as it just did.
        return None