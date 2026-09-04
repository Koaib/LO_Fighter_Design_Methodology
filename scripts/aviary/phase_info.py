# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:06:45 2026

@author: KK
"""

from aviary.variable_info.enums import Transcription

phase_info = {
    'pre_mission': {'include_takeoff': False, 'optimize_mass': True},
    'climb': {
        # Dynamic.Mission.DISTANCE is declared input_initial=True (an
        # externally-supplied input, no built-in default) - unlike mass/
        # altitude/mach/time, set_initial_guesses() has no fallback default
        # for it (aviary/mission/energy_state_problem_configurator.py's
        # set_phase_initial_guesses only auto-defaults those four). Left
        # unset it landed on OpenMDAO's generic 1.0 placeholder instead of
        # a real integrated distance.
        # 'mass' has the same problem distance had: set_phase_initial_guesses()
        # only auto-fills a FLAT scalar (Aircraft.Design.GROSS_MASS, same
        # value at every node, same across all three phases) when 'mass' is
        # missing here — never decreasing to reflect fuel burn. With only a
        # single Newton pass (no driver/optimizer), that bad flat guess is
        # exactly what produced Mission.FUEL_MASS = 0.0 (fuel_burned =
        # GROSS_MASS - final descent mass, and the solver settled near the
        # flat guess instead of a real fuel-depleting trajectory).
        #
        # The placeholder values below are OVERWRITTEN at runtime by
        # run_aviary_mission() (scripts/aviary/run_aviary.py), which
        # recomputes distance/mass guesses from main.py's actual
        # DESIGN_RANGE_NMI and wing-loading-scaled gross mass on every run
        # — they're just here so this file stays self-consistent if
        # imported/read standalone. Don't rely on editing these directly;
        # edit main.py's AVIARY / MISSION CONFIG section instead.
        'initial_guesses': {
            'distance': ([0.0, 100.0], 'nmi'),
            'mass': ([103.59, 100.59], 'lbm'),
        },
        'subsystem_options': {
    'aerodynamics': {
        'method': 'tabular_cruise',
        'solve_alpha': True,
        'connect_training_data': True,
    }
},
        'user_options': {
            'num_segments': 5, 'order': 3,
            'mach_optimize': False,
            # mach_initial/mach_bounds below are OVERWRITTEN at runtime by
            # run_aviary_mission() (scripts/aviary/run_aviary.py), which
            # computes the minimum sea-level Mach that keeps CL within this
            # run's own measured max tested CL, from THIS run's actual gross
            # mass and wing area — same "don't rely on editing these
            # directly" pattern as the initial_guesses block above.
            #
            # Why this exists: mach_initial=0.2 (V~132 kt at sea level) once
            # demanded CL~1.68 for level flight against this geometry's
            # ~1.0 max tested CL (alpha=-10..22 deg VSPAero sweep) — not a
            # mass-basis error (even a real aircraft can't sustain level
            # flight at 132 kt at max gross weight), just an unrealistic
            # START-of-climb condition (closer to rotation speed than an
            # established climb schedule). That made solve_alpha's Newton
            # iteration walk off the LIFT_POLAR table's edge (extrapolation
            # -> singular gradient) and the climb-phase RHS solve failed
            # outright with an AnalysisError. 0.3 below is just a sensible
            # static fallback if this file is ever imported without going
            # through run_aviary_mission() first.
            'mach_initial': (0.3, 'unitless'), 'mach_final': (0.6, 'unitless'),
            'mach_bounds': ((0.28, 0.62), 'unitless'),
            'mach_polynomial_order': 3,
            'altitude_optimize': False,
            'altitude_initial': (0.0, 'ft'), 'altitude_final': (35000.0, 'ft'),
            'altitude_bounds': ((0.0, 36000.0), 'ft'),
            'altitude_polynomial_order': 3,
            'throttle_enforcement': 'path_constraint',
            'time_initial': (0.0, 'min'),
            'time_duration_bounds': ((10.0, 40.0), 'min'),
            'transcription': Transcription.COLLOCATION,
        },
    },
    'cruise': {
        # See 'climb' phase above — overwritten at runtime by run_aviary_mission().
        'initial_guesses': {
            'distance': ([100.0, 300.0], 'nmi'),
            'mass': ([100.59, 97.59], 'lbm'),
        },
        'subsystem_options': {
    'aerodynamics': {
        'method': 'tabular_cruise',
        'solve_alpha': True,
        'connect_training_data': True,
    }
},
        'user_options': {
            'num_segments': 5, 'order': 3,
            'mach_optimize': False,
            'mach_initial': (0.6, 'unitless'), 'mach_final': (0.6, 'unitless'),
            'mach_bounds': ((0.58, 0.62), 'unitless'),
            'mach_polynomial_order': 3,
            'altitude_optimize': False,
            'altitude_initial': (35000.0, 'ft'), 'altitude_final': (35000.0, 'ft'),
            'altitude_bounds': ((34000.0, 36000.0), 'ft'),
            'altitude_polynomial_order': 3,
            'throttle_enforcement': 'path_constraint',
            'time_initial_bounds': ((10.0, 40.0), 'min'),
            'time_duration_bounds': ((20.0, 90.0), 'min'),
            'transcription': Transcription.COLLOCATION,
        },
    },
    'descent': {
        # See 'climb' phase above — overwritten at runtime by run_aviary_mission().
        'initial_guesses': {
            'distance': ([300.0, 400.0], 'nmi'),
            'mass': ([97.59, 96.59], 'lbm'),
        },
        'subsystem_options': {
    'aerodynamics': {
        'method': 'tabular_cruise',
        'solve_alpha': True,
        'connect_training_data': True,
    }
},
        'user_options': {
            'num_segments': 5, 'order': 3,
            'mach_optimize': False,
            'mach_initial': (0.6, 'unitless'), 'mach_final': (0.3, 'unitless'),
            'mach_bounds': ((0.28, 0.62), 'unitless'),
            'mach_polynomial_order': 3,
            'altitude_optimize': False,
            'altitude_initial': (35000.0, 'ft'), 'altitude_final': (500.0, 'ft'),
            'altitude_bounds': ((0.0, 36000.0), 'ft'),
            'altitude_polynomial_order': 3,
            'throttle_enforcement': 'path_constraint',
            'time_initial_bounds': ((30.0, 130.0), 'min'),
            'time_duration_bounds': ((10.0, 40.0), 'min'),
            'transcription': Transcription.COLLOCATION,
        },
    },
    'post_mission': {
        'include_landing': False,
        'constrain_range': True,
        'target_range': (400.0, 'nmi'),   # PLACEHOLDER — sanity-checked against
                                            # F-16C's published 360 nmi hi-lo-hi
                                            # tactical radius in a different config
    },
}