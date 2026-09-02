# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:03:49 2026

@author: KK
"""

"""
External aero subsystem: feeds VSPAero-derived lift/drag polars into Aviary,
completely replacing Aviary's internal FLOPS/GASP aero calculation.
"""

import numpy as np
import openmdao.api as om
import aviary.api as av
from aviary.api import Aircraft

from build_aero_polar import build_polar_arrays


class ExternalAero(om.ExplicitComponent):
    def initialize(self):
        self.options.declare("altitude")
        self.options.declare("mach")
        self.options.declare("alpha")
        self.options.declare("cl")
        self.options.declare("cd")

    def setup(self):
        n = len(self.options["cl"])
        self.add_output("lift_table", val=self.options["cl"], shape=(n,))
        self.add_output("drag_table", val=self.options["cd"], shape=(n,))

    def compute(self, inputs, outputs):
        outputs["lift_table"] = self.options["cl"]
        outputs["drag_table"] = self.options["cd"]


class ExternalAeroBuilder(av.AerodynamicsBuilder):
    def __init__(self, geom_stem, name="external_aero"):
        super().__init__(name)
        self._data = build_polar_arrays(
            geom_stem,
            expected_machs={0.2, 0.4, 0.6},
            expected_altitudes={0.0, 15000.0, 35000.0},
        )

    
    def build_pre_mission(self, aviary_inputs, subsystem_options=None):
    # No custom component needed here: GASP's tabular_cruise aerodynamics
    # method (set in phase_info.py) reads Aircraft.Design.LIFT_POLAR /
    # DRAG_POLAR directly from aviary_inputs as fixed parameters (set via
    # prob.aviary_inputs.set_val() in run_aviary.py, correctly shaped by
    # reshape_to_grid()). A component here promoting the same names would
    # conflict with that mechanism, as it just did.
        return None