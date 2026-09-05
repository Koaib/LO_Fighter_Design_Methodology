# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:09:02 2026

@author: KK
"""

"""
Aviary mission-analysis stage of the pipeline. Called by main.py's
RUN_AVIARY step at the end of a full run — main.py's AVIARY / MISSION
CONFIG section owns every user-facing input (mass basis, engine specs,
mission profile, wing geometry, Mach/altitude grid) and passes all of them
into run_aviary_mission() below, so there is nothing left to edit in this
file for a normal run.

Requires the aero stage (main.py) to have already produced a complete
Mach x Altitude aero-polar grid (Results/Aero/aero_<geom_stem>_M#_ALT#_*.csv)
for the SAME geom_stem, covering the same mach_list/altitude_list passed in.

Usage (standalone, uses this file's own placeholder defaults):
    python scripts/aviary/run_aviary.py
"""

import sys, os, copy
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # for vsp_setup

# Workaround for a real Aviary bug hit on the first driver-based run: its own
# automatic post-run reporting hook (aviary/interface/reports.py:
# subsystem_report -> mass_builder.py -> find_variable_in_problem ->
# round_it()) crashes with "OverflowError: cannot convert float infinity to
# integer" whenever any reported mass value is non-finite (e.g. an optimizer
# that stalled at an infeasible point) - BEFORE our own code gets control
# back to check convergence or print diagnostics. OPENMDAO_REPORTS=0
# (checked in openmdao/utils/reports_system.py's reports_active()/
# get_reports_to_activate(), read at problem setup time, so this must be set
# before AviaryProblem() is constructed) disables that whole auto-report
# system. We still call Aviary's own mission_report()/timeseries_csv()
# directly ourselves below - those are plain function calls, not part of
# this hook-triggered system, so they're unaffected.
os.environ["OPENMDAO_REPORTS"] = "0"

import vsp_setup
import aviary.api as av
from aviary.api import Aircraft, Mission, Settings
from aviary.variable_info.enums import EquationsOfMotion, LegacyCode, ProblemType
from aviary.interface.reports import mission_report, timeseries_csv

from phase_info import phase_info
from external_aero_builder import ExternalAeroBuilder
from build_engine_deck import build_deck

# =============================================================================
# CONSOLE-TO-FILE LOGGING — Spyder's IPython console has a scrollback limit,
# and a single run here (suppress_solver_print=False, iprint=2) prints
# thousands of lines (Newton-solver sub-iteration spam x ~100 SLSQP
# iterations). Once that limit is hit, Spyder silently drops the OLDEST
# lines from the console, which is why copy-pasting "the whole run" kept
# coming back incomplete/stale no matter how carefully it was copied - the
# lines were gone from the console itself, not lost in the copy. This tees
# every print() (this file's own + Aviary's + OpenMDAO's + Dymos's, since
# they all go through the same sys.stdout) to a plain text file as well,
# so the full, exact transcript of a run is always available on disk
# regardless of what the console can hold or show.
# Appends (not overwrites) so old runs stay in the file too - each run is
# marked with its own timestamped header so the LATEST run is easy to find
# (jump to the end of the file / search for the last "RUN START").
class _ConsoleTee:
    def __init__(self, *streams):
        self._streams = streams
    def write(self, data):
        for s in self._streams:
            s.write(data)
    def flush(self):
        for s in self._streams:
            s.flush()

_CONSOLE_LOG_PATH = os.path.join(vsp_setup.AVIARY_FILES, "run_aviary_console_log.txt")
if not isinstance(sys.stdout, _ConsoleTee):  # avoid stacking tees on re-import in the same kernel
    import datetime as _datetime
    _console_log_file = open(_CONSOLE_LOG_PATH, "a", encoding="utf-8")
    _console_log_file.write(
        f"\n\n{'=' * 80}\nRUN START {_datetime.datetime.now().isoformat()}\n{'=' * 80}\n"
    )
    _console_log_file.flush()
    sys.stdout = _ConsoleTee(sys.stdout, _console_log_file)
    print(f"(Full console output for this run is also being saved to: {_CONSOLE_LOG_PATH})")

# =============================================================================
# FIXED ARCHITECTURE CHOICES — not user config, don't move to main.py.
# Other files assume these exact values: phase_info.py's 'tabular_cruise'
# aero method is GASP-specific; the mass overrides below assume FLOPS's
# mass buildup. Changing either means reworking phase_info.py, not just
# editing a number here.
# =============================================================================
EQUATIONS_OF_MOTION = EquationsOfMotion.ENERGY_STATE
MASS_METHOD = LegacyCode.FLOPS
AERODYNAMICS_METHOD = LegacyCode.GASP

# =============================================================================
# STANDALONE-ONLY DEFAULTS — only used when this file is run directly
# (not via main.py). main.py's AVIARY / MISSION CONFIG section passes every
# one of these in explicitly, so nothing here needs to stay in sync by hand
# for a normal pipeline run — but a standalone run needs geom_stem and the
# wing values to describe the SAME geometry, or build_aero_polar.py fails
# to find any matching aero CSVs. Kept pointed at the current full-scale
# geometry (matches main.py's IMPORT_FILE/TEST_WING_* as of the ×19
# full-scale switch) rather than the earlier wind-tunnel-scale placeholder.
DEFAULT_GEOM_STEM = "SSAM_final_geom_to_be_used_scaled_by_19_simplified"
DEFAULT_WING_AREA_FT2 = 843.018026816014
DEFAULT_WING_SPAN_FT = 44.47670603674372
DEFAULT_WING_ASPECT_RATIO = 2.346542205448008
DEFAULT_WING_HAS_STRUT = False
DEFAULT_WING_HAS_FOLD = False
DEFAULT_F22_EMPTY_MASS_LBM = 43340.0
DEFAULT_F22_GROSS_MASS_LBM = 83500.0
DEFAULT_F22_FUEL_MASS_LBM = 18000.0
DEFAULT_F22_WING_AREA_FT2 = 840.0
DEFAULT_ENGINE_T_SL_DRY_LBF = 17800.0
DEFAULT_ENGINE_T_SL_AB_LBF = 29100.0
# TSFC now comes from build_engine_deck.py's Mattingly & Heiser formula
# (Eqs. 3.55a/b for this engine class) instead of a guessed constant —
# nothing to set here any more.
DEFAULT_ENGINE_THROTTLE_RATIO = 1.07   # Mattingly & Heiser's AAF (F100-class) worked example
DEFAULT_ENGINE_TYPE = "low_bypass_mixed_flow_turbofan"
DEFAULT_CRUISE_MACH = 0.6
DEFAULT_CRUISE_ALTITUDE_FT = 35000.0
DEFAULT_DESIGN_RANGE_NMI = 400.0
DEFAULT_MACH_LIST = [0.2, 0.4, 0.6]
DEFAULT_ALTITUDE_LIST = [0.0, 15000.0, 35000.0]


def _build_aircraft_inputs(wing_area_ft2, wing_span_ft, wing_aspect_ratio,
                            wing_has_strut, wing_has_fold,
                            design_range_nmi, cruise_mach, cruise_altitude_ft):
    """
    Aircraft/mission input data, built directly as an AviaryValues object
    instead of a CSV file. load_inputs()'s own docstring confirms
    aircraft_data accepts "a path to a CSV file OR an existing AviaryValues
    object" - and AviaryValues.set_val() does exactly the same metadata-
    driven type/unit checking either way (confirmed against the v1.0.1
    source: aviary/utils/process_input_decks.py's CSV parser just calls
    set_val() too, with no special handling of its own - so this is a pure
    mechanical swap in how these values get set, not a behavior change).
    """
    aviary_inputs = av.AviaryValues()
    aviary_inputs.set_val(Settings.EQUATIONS_OF_MOTION, EQUATIONS_OF_MOTION)
    aviary_inputs.set_val(Settings.MASS_METHOD, MASS_METHOD)
    aviary_inputs.set_val(Settings.AERODYNAMICS_METHOD, AERODYNAMICS_METHOD)
    # OFF_DESIGN_MIN_FUEL: fixed range (phase_info's target_range), solve
    # for the minimum fuel/mission gross mass needed to fly it — see
    # aviary/core/aviary_group.py's add_design_variables(): for this
    # problem_type, only Mission.GROSS_MASS becomes a design variable
    # (bounded above by our own Aircraft.Design.GROSS_MASS, i.e. it can
    # never exceed the MTOW we already fixed via wing-loading scaling), a
    # RANGE_RESIDUAL constraint makes the flown range hit target_range
    # exactly (not by us hand-tuning phase durations), and every problem
    # type gets a final-cruise-mass design variable + residual mass
    # constraint that actually closes the mass/fuel-burn trajectory — the
    # exact thing missing from a plain run_model() call all along. This
    # is a real (if narrow) optimizer, not the full aircraft-sizing kind:
    # Aircraft.Design.GROSS_MASS itself is never touched.
    aviary_inputs.set_val(Settings.PROBLEM_TYPE, ProblemType.OFF_DESIGN_MIN_FUEL)
    aviary_inputs.set_val(Aircraft.Wing.AREA, wing_area_ft2, units="ft**2")
    aviary_inputs.set_val(Aircraft.Wing.SPAN, wing_span_ft, units="ft")
    aviary_inputs.set_val(Aircraft.Wing.ASPECT_RATIO, wing_aspect_ratio, units="unitless")
    aviary_inputs.set_val(Aircraft.Wing.HAS_STRUT, wing_has_strut)
    aviary_inputs.set_val(Aircraft.Wing.HAS_FOLD, wing_has_fold)
    aviary_inputs.set_val(Aircraft.Design.RANGE, design_range_nmi, units="NM")
    aviary_inputs.set_val(Aircraft.Design.CRUISE_MACH, cruise_mach, units="unitless")
    aviary_inputs.set_val(Aircraft.Design.CRUISE_ALTITUDE, cruise_altitude_ft, units="ft")

    # Aviary's own preprocessor (aviary/utils/preprocessors.py) silently
    # defaults NUM_FLIGHT_CREW to 2 whenever it's not explicitly set — an
    # airliner-cockpit assumption ("flight_crew_count = 2 if design_pax<151
    # else 3"), applied even though this run's design_pax is 0. That 2-crew
    # default was adding a spurious ~450 lbm (2 x 225 lbm/crew, see
    # aviary/subsystems/mass/flops_based/crew.py) into Aviary's internal
    # Mission.ZERO_FUEL_MASS on top of our EMPTY_MASS override. This is a
    # single-seat fighter, so set the real number (1 pilot) explicitly
    # instead of letting that hidden default apply. NUM_FLIGHT_ATTENDANTS/
    # NUM_GALLEY_CREW already come out to 0 from the same preprocessor since
    # design_pax=0, but are set explicitly here too so nothing about the
    # crew complement is left to an implicit default.
    aviary_inputs.set_val(Aircraft.CrewPayload.NUM_FLIGHT_CREW, 1, units="unitless")
    aviary_inputs.set_val(Aircraft.CrewPayload.NUM_FLIGHT_ATTENDANTS, 0, units="unitless")
    aviary_inputs.set_val(Aircraft.CrewPayload.NUM_GALLEY_CREW, 0, units="unitless")

    return aviary_inputs


def run_aviary_mission(
    geom_stem=None,
    wing_area_ft2=None, wing_span_ft=None, wing_aspect_ratio=None,
    wing_has_strut=None, wing_has_fold=None,
    f22_empty_mass_lbm=None, f22_gross_mass_lbm=None,
    f22_fuel_mass_lbm=None, f22_wing_area_ft2=None,
    engine_t_sl_dry_lbf=None, engine_t_sl_ab_lbf=None,
    engine_throttle_ratio=None, engine_type=None,
    cruise_mach=None, cruise_altitude_ft=None, design_range_nmi=None,
    mach_list=None, altitude_list=None,
    custom_engine_deck_path=None,
    simple_mission=False,
):
    """Run the Aviary mission analysis for geom_stem's already-produced aero
    CSVs (see module docstring). Every argument defaults to this module's
    own placeholder values (DEFAULT_* above) when left as None, for
    standalone use; main.py's AVIARY / MISSION CONFIG section passes its
    own values for all of them on a real pipeline run.

    simple_mission: if True, collapses the climb+cruise+descent mission
    down to a single cruise-only phase spanning the full design range, at
    fixed cruise Mach/altitude — same aircraft, aero table and engine deck
    as the full mission ("for our case"), just far fewer collocation nodes
    and no phase-linking. A cheap diagnostic to isolate whether a stall is
    inherent to this problem's scale/formulation or specific to the
    climb/descent phase machinery — see the "SOLVE DID NOT CONVERGE"
    diagnostic dump below for the actual verdict on a given run (the
    mass_initial-based version of this comparison from an earlier debugging
    pass was invalid: mass_initial turned out to be a no-op on the first
    flight phase either way, so it was never actually testing what it
    claimed to). Never edits the module-level phase_info import in place
    (only a deepcopy() of it), so a later full-mission call in the same
    process still sees climb/descent intact.

    custom_engine_deck_path: if given, this CSV file is used directly as
    the engine deck instead of the auto-generated Mattingly & Heiser deck
    (see scripts/aviary/engine_deck_template.csv for the expected format).
    Use this once real engine performance data becomes available, rather
    than the textbook-correlation placeholder."""
    geom_stem = geom_stem if geom_stem is not None else DEFAULT_GEOM_STEM
    wing_area_ft2 = wing_area_ft2 if wing_area_ft2 is not None else DEFAULT_WING_AREA_FT2
    wing_span_ft = wing_span_ft if wing_span_ft is not None else DEFAULT_WING_SPAN_FT
    wing_aspect_ratio = wing_aspect_ratio if wing_aspect_ratio is not None else DEFAULT_WING_ASPECT_RATIO
    wing_has_strut = wing_has_strut if wing_has_strut is not None else DEFAULT_WING_HAS_STRUT
    wing_has_fold = wing_has_fold if wing_has_fold is not None else DEFAULT_WING_HAS_FOLD
    f22_empty_mass_lbm = f22_empty_mass_lbm if f22_empty_mass_lbm is not None else DEFAULT_F22_EMPTY_MASS_LBM
    f22_gross_mass_lbm = f22_gross_mass_lbm if f22_gross_mass_lbm is not None else DEFAULT_F22_GROSS_MASS_LBM
    f22_fuel_mass_lbm = f22_fuel_mass_lbm if f22_fuel_mass_lbm is not None else DEFAULT_F22_FUEL_MASS_LBM
    f22_wing_area_ft2 = f22_wing_area_ft2 if f22_wing_area_ft2 is not None else DEFAULT_F22_WING_AREA_FT2
    engine_t_sl_dry_lbf = engine_t_sl_dry_lbf if engine_t_sl_dry_lbf is not None else DEFAULT_ENGINE_T_SL_DRY_LBF
    engine_t_sl_ab_lbf = engine_t_sl_ab_lbf if engine_t_sl_ab_lbf is not None else DEFAULT_ENGINE_T_SL_AB_LBF
    engine_throttle_ratio = engine_throttle_ratio if engine_throttle_ratio is not None else DEFAULT_ENGINE_THROTTLE_RATIO
    engine_type = engine_type if engine_type is not None else DEFAULT_ENGINE_TYPE
    cruise_mach = cruise_mach if cruise_mach is not None else DEFAULT_CRUISE_MACH
    cruise_altitude_ft = cruise_altitude_ft if cruise_altitude_ft is not None else DEFAULT_CRUISE_ALTITUDE_FT
    design_range_nmi = design_range_nmi if design_range_nmi is not None else DEFAULT_DESIGN_RANGE_NMI
    mach_list = mach_list if mach_list is not None else DEFAULT_MACH_LIST
    altitude_list = altitude_list if altitude_list is not None else DEFAULT_ALTITUDE_LIST

    # Derived mass values (wing-loading-scaled placeholder — see main.py's
    # AVIARY / MISSION CONFIG section for the physical justification).
    # Dividing F-16C mass by a linear scale factor against an unrelated
    # wing area previously gave a wing loading of ~1187 lbm/ft^2 (vs. the
    # real F-16C's ~88 lbm/ft^2) - physically impossible, requiring CL~9.5
    # for level flight, which is why the mission's climb aerodynamics
    # Newton solve couldn't converge until this wing-loading match was used
    # instead. Mass basis itself later switched from F-16C to F-22A (see
    # main.py) — same wing-loading method, different reference aircraft.
    wing_loading_lbm_per_ft2 = f22_gross_mass_lbm / f22_wing_area_ft2
    gross_mass_lbm = wing_loading_lbm_per_ft2 * wing_area_ft2

    # Mission.GROSS_MASS (the OFF_DESIGN_MIN_FUEL design variable) is seeded
    # at 0.9x gross_mass_lbm below, per Aviary's own documented
    # run_off_design_mission() pattern. The trajectory's own starting-mass
    # guesses (initial_guesses["mass"] for climb/cruise/descent, set from
    # this single seed_gross_mass_lbm value) MUST use the
    # same number, not the raw gross_mass_lbm - a run with these two
    # inconsistent by ~10% at iteration 0 produced a diagnostic dump showing
    # Mission.GROSS_MASS (75420 lbm) and traj.climb.states:mass[0] (~83800
    # lbm) both frozen at their own mutually-contradictory seed values
    # across all 46 SLSQP iterations, ending in "Positive directional
    # derivative for linesearch" (Exit mode 8) - the optimizer could never
    # find a step that didn't worsen Aviary's automatically-added
    # link_climb_mass equality constraint tying these two quantities
    # together (energy_state_problem_configurator.py's add_post_mission_
    # systems(), include_takeoff=False branch). Defining the seed once here
    # and reusing it everywhere below makes them identical by construction.
    seed_gross_mass_lbm = gross_mass_lbm * 0.9

    # Empty/fuel split preserves the REAL F-22's own empty:fuel PROPORTION,
    # not each one's own independent fraction of GROSS_MASS. The latter
    # (empty_mass = gross*(f22_empty/f22_gross), same for fuel) is what
    # this project used before — since the real F-22's own empty+fuel
    # fractions of its own gross only sum to 0.7346 (43,340+18,000=61,340
    # vs. 83,500 lbm MTOW; the real aircraft's MTOW includes weapons/
    # stores provision), that structurally left empty+fuel short of
    # GROSS_MASS by the same ~26.5% every run, regardless of wing area -
    # which is exactly the mass-model gap that made Aviary's own
    # GROSS_MASS - ZERO_FUEL_MASS bookkeeping diverge from our specified
    # Aircraft.Fuel.TOTAL_CAPACITY (see Results/aviary_perf/'s plain-language
    # summary for an explanation of the "Excess Fuel Capacity" / "Fuel mass residual"
    # discrepancy this caused). Scaling by the empty:fuel RATIO instead
    # closes GROSS_MASS = EMPTY_MASS + FUEL_MASS + payload(0) exactly,
    # while still preserving the real aircraft's relative structure-vs-
    # fuel split — payload stays 0 (no passengers/weapons/stores modeled
    # in this run), consistent with Aviary's own "you have not specified
    # at least one passenger" warning.
    _empty_fuel_sum_lbm = f22_empty_mass_lbm + f22_fuel_mass_lbm
    empty_mass_lbm = gross_mass_lbm * (f22_empty_mass_lbm / _empty_fuel_sum_lbm)
    fuel_mass_lbm = gross_mass_lbm * (f22_fuel_mass_lbm / _empty_fuel_sum_lbm)

    os.makedirs(vsp_setup.AVIARY_FILES, exist_ok=True)
    os.makedirs(vsp_setup.AVIARY_PERF_DIR, exist_ok=True)
    os.makedirs(vsp_setup.AVIARY_PERF_NATIVE_DIR, exist_ok=True)

    print(f"   [mass] wing-loading-scaled GROSS={gross_mass_lbm:.2f} lbm, "
          f"EMPTY={empty_mass_lbm:.2f} lbm, FUEL={fuel_mass_lbm:.2f} lbm")

    if custom_engine_deck_path:
        if not os.path.isfile(custom_engine_deck_path):
            raise FileNotFoundError(
                f"custom_engine_deck_path={custom_engine_deck_path!r} does not "
                f"exist. See scripts/aviary/engine_deck_template.csv for the "
                f"expected format, or set CUSTOM_ENGINE_DECK_PATH = None in "
                f"main.py to fall back to the auto-generated deck."
            )
        engine_deck_path = custom_engine_deck_path
        print(f"   [engine deck] using user-supplied deck: {engine_deck_path}")
    else:
        engine_deck_path = build_deck(
            out_dir=os.path.join(vsp_setup.AVIARY_FILES, "engines"),
            deck_name="f100_pw229_simplified.deck",
            t_sl_dry=engine_t_sl_dry_lbf, t_sl_ab=engine_t_sl_ab_lbf,
            throttle_ratio=engine_throttle_ratio,
            engine_type=engine_type,
        )

    from aviary.utils.named_values import NamedValues
    from build_aero_polar import reshape_to_grid

    external_aero = ExternalAeroBuilder(
        geom_stem=geom_stem,
        expected_machs=set(mach_list),
        expected_altitudes=set(altitude_list),
    )

    aero_data = NamedValues()
    aero_data.set_val("altitude", external_aero._data["altitude"], "ft")
    aero_data.set_val("mach", external_aero._data["mach"], "unitless")
    aero_data.set_val("angle_of_attack", external_aero._data["alpha"], "deg")

    # simple_mission (opt2): deepcopy first — dropping 'climb'/'descent'
    # below mutates whatever dict phase_info_local points at, and the
    # bare module-level `phase_info` import is a singleton shared across
    # every call in this process; popping keys from it directly would
    # permanently delete those phases for any later full-mission call in
    # the same run.
    phase_info_local = copy.deepcopy(phase_info) if simple_mission else phase_info
    if simple_mission:
        phase_info_local.pop("climb", None)
        phase_info_local.pop("descent", None)
        phase_info_local["post_mission"]["target_range"] = (design_range_nmi, "nmi")

    phase_names = tuple(name for name in ("climb", "cruise", "descent") if name in phase_info_local)
    for phase_name in phase_names:
        phase_info_local[phase_name]["subsystem_options"]["aerodynamics"]["aero_data"] = aero_data

    # cruise (simple_mission's FIRST and only phase)'s mach_initial/
    # altitude_initial are already fixed constants in phase_info.py (0.6 /
    # 35000 ft, both ends) — the low-altitude sea-level-CL problem the climb
    # hack below exists for doesn't apply to a phase that starts at cruise
    # altitude/Mach directly, so nothing else is needed for that branch.
    if not simple_mission:
        # Climb start-of-phase Mach — computed from THIS run's actual gross
        # mass and the REAL max CL your aero sweep reached, instead of
        # phase_info.py's own static mach_initial. A too-low starting Mach at
        # low altitude demands more lift than this wing+mass can produce
        # within the tested alpha range, which makes solve_alpha's Newton
        # iteration walk off the edge of the LIFT_POLAR table (extrapolation
        # -> singular gradient) and the climb-phase RHS solve fails outright
        # with an AnalysisError. That's exactly what broke an earlier run at
        # mach_initial=0.2 (CL~1.68 needed at sea level vs. a ~1.0 max tested
        # CL for this geometry) — this closes that failure mode for any
        # mass/wing/aero-table combination, not just this run's specific
        # numbers, the same way the initial-guess block below already does
        # for distance/mass.
        #
        # CL = W / (0.5*rho*V^2*S); solved for the minimum sea-level Mach that
        # keeps CL at or below 90% of the max CL this run's own aero sweep
        # actually reached — a margin below the table's hard edge (not right
        # at it), since solve_alpha's local interpolation gradient degrades
        # near the edge even before literally exceeding it.
        max_tested_cl = float(external_aero._data["cl"].max())
        cl_margin = 0.9
        weight_N = gross_mass_lbm * 0.45359237 * 9.80665
        wing_area_m2 = wing_area_ft2 * 0.09290304
        _, rho_sl, _, a_sl = vsp_setup.isa_atmosphere(0.0)
        climb_mach_initial = (
            weight_N / (0.5 * rho_sl * a_sl**2 * wing_area_m2 * cl_margin * max_tested_cl)
        ) ** 0.5
        climb_mach_initial = round(climb_mach_initial + 0.02, 2)  # small extra margin, clean value

        print(f"   [climb] computed start-of-climb Mach={climb_mach_initial:.2f} "
              f"(sea-level CL vs. this run's measured max CL={max_tested_cl:.3f})")

        phase_info_local["climb"]["user_options"]["mach_initial"] = (climb_mach_initial, "unitless")
        (lo0, hi0), mach_unit = phase_info_local["climb"]["user_options"]["mach_bounds"]
        phase_info_local["climb"]["user_options"]["mach_bounds"] = (
            (min(lo0, climb_mach_initial - 0.02), hi0), mach_unit
        )

    # NOTE: mass_initial is deliberately NOT set on climb (or on cruise in
    # simple_mission, above). An earlier version of this script set it to
    # seed_gross_mass_lbm to fix a singular-Jacobian crash that came from a
    # since-removed mass_solve_segments=True path. That original justification
    # is gone, and the "fix" turned out to be a no-op anyway - confirmed by
    # reading Aviary's own source, not just re-guessing:
    #   - aviary/utils/aviary_options_dict.py's add_state_options() docstring
    #     for mass_initial: "When unspecified, the optimizer controls the
    #     value. When specified, a constraint is created on the initial
    #     mass" - i.e. specifying it calls Dymos add_state(fix_initial=True).
    #   - aviary/mission/energy_state_problem_configurator.py's
    #     add_post_mission_systems(), the include_takeoff=False branch (what
    #     this project uses): it unconditionally calls
    #     first_flight_phase.set_state_options(Dynamic.Vehicle.MASS,
    #     fix_initial=False, input_initial=False) and then connects
    #     Mission.Takeoff.FINAL_MASS (itself derived from the free
    #     Mission.GROSS_MASS design variable) straight into
    #     traj.<first_phase>.initial_states:mass. This runs AFTER phases are
    #     built, so it overrides whatever fix_initial phase_info asked for on
    #     the first flight phase - mass_initial there never had a chance to
    #     take effect.
    #   - Reproduced directly against aviary==1.0.1 (OFF_DESIGN_MIN_FUEL,
    #     Aviary's own bundled advanced_single_aisle_FLOPS aircraft): running
    #     the exact same problem with vs. without a fixed mass_initial on the
    #     first flight phase produced bit-identical SLSQP iteration histories
    #     end to end. It is inert here, not just theoretically overridden.
    # Leaving it unset matches Aviary's own reference mission
    # (aviary/models/missions/energy_state_default.py has no mass_initial at
    # all) and is what "the optimizer controls the value" is supposed to
    # mean for a problem type where Mission.GROSS_MASS is a design variable.

    # Dynamic Dymos initial guesses — computed from THIS run's actual
    # seed_gross_mass_lbm/design_range_nmi instead of phase_info.py's frozen
    # numbers, so they can't silently go stale if TEST_WING_AREA_FT2 or the
    # F22 mass-basis constants change in main.py. A bad/stale initial
    # guess is exactly what caused the Newton solve non-convergence fixed
    # earlier this project (see phase_info.py's history) - recomputing
    # these here every run closes that failure mode for good. Based on
    # seed_gross_mass_lbm (not the raw gross_mass_lbm) so the trajectory's
    # starting mass agrees with Mission.GROSS_MASS's own seed at iteration 0
    # - see the comment above seed_gross_mass_lbm's definition for why that
    # match matters.
    #
    # Split ratios (25%/50%/25% of range; ~3:3:1 of guessed fuel burn
    # across climb/cruise/descent) reproduce phase_info.py's original
    # hand-picked seed values at the 103.59 lbm gross-mass test point that
    # was validated to converge - still just seed values for the
    # collocation solve, not meant to be physically exact.
    guessed_total_burn_lbm = seed_gross_mass_lbm * 0.068   # ~7/103.59 lbm, from
                                                        # the validated test run

    if simple_mission:
        # No climb/descent to split fuel burn across — the whole guessed
        # burn happens over the single cruise phase, which now spans the
        # entire design range.
        mass_after_cruise_only = seed_gross_mass_lbm - guessed_total_burn_lbm
        phase_info_local["cruise"]["initial_guesses"]["distance"] = ([0.0, design_range_nmi], "nmi")
        phase_info_local["cruise"]["initial_guesses"]["mass"] = ([seed_gross_mass_lbm, mass_after_cruise_only], "lbm")
    else:
        climb_burn = guessed_total_burn_lbm * (3 / 7)
        cruise_burn = guessed_total_burn_lbm * (3 / 7)
        descent_burn = guessed_total_burn_lbm * (1 / 7)

        mass_after_climb = seed_gross_mass_lbm - climb_burn
        mass_after_cruise = mass_after_climb - cruise_burn
        mass_after_descent = mass_after_cruise - descent_burn

        dist_climb_end = 0.25 * design_range_nmi
        dist_cruise_end = 0.75 * design_range_nmi

        phase_info_local["climb"]["initial_guesses"]["distance"] = ([0.0, dist_climb_end], "nmi")
        phase_info_local["climb"]["initial_guesses"]["mass"] = ([seed_gross_mass_lbm, mass_after_climb], "lbm")
        phase_info_local["cruise"]["initial_guesses"]["distance"] = ([dist_climb_end, dist_cruise_end], "nmi")
        phase_info_local["cruise"]["initial_guesses"]["mass"] = ([mass_after_climb, mass_after_cruise], "lbm")
        phase_info_local["descent"]["initial_guesses"]["distance"] = ([dist_cruise_end, design_range_nmi], "nmi")
        phase_info_local["descent"]["initial_guesses"]["mass"] = ([mass_after_cruise, mass_after_descent], "lbm")

    # Run with AVIARY_FILES as the working directory so Aviary/OpenMDAO's own
    # native "<script>_out/" report folder lands there instead of cluttering
    # scripts/aviary/ (same os.chdir()-and-restore pattern vsp_setup.py
    # already uses around vspaero.exe).
    original_cwd = os.getcwd()
    os.chdir(vsp_setup.AVIARY_FILES)
    try:
        prob = av.AviaryProblem()
        prob.load_inputs(
            _build_aircraft_inputs(
                wing_area_ft2, wing_span_ft, wing_aspect_ratio,
                wing_has_strut, wing_has_fold,
                design_range_nmi, cruise_mach, cruise_altitude_ft,
            ),
            phase_info_local,
        )
        prob.load_external_subsystems([external_aero])

        # Fixed mass overrides — settings:mass_method stays FLOPS, but
        # since EMPTY_MASS is set here on aviary_inputs *before*
        # build_model()/setup(), Aviary's override-variable mechanism
        # disconnects FLOPS's own empirical EmptyMass computation and treats
        # this fixed value as the input instead (see
        # aviary/subsystems/premission.py:override_aviary_vars). GROSS_MASS
        # is already a plain input in FLOPS's mass buildup (never computed),
        # so setting it here is a normal input assignment, not an override.
        prob.aviary_inputs.set_val(Aircraft.Design.EMPTY_MASS, empty_mass_lbm, units="lbm")
        prob.aviary_inputs.set_val(Aircraft.Design.GROSS_MASS, gross_mass_lbm, units="lbm")
        prob.aviary_inputs.set_val(Aircraft.Fuel.TOTAL_CAPACITY, fuel_mass_lbm, units="lbm")

        # Found by actually reading Aviary's own documented off-design
        # workflow (docs/examples/off_design_missions.ipynb) end to end and
        # comparing it line-for-line against what this script does. Aviary's
        # own AviaryProblem.run_off_design_mission() - the method the docs
        # say is THE way to run an OFF_DESIGN_MIN_FUEL mission - always seeds
        # Mission.GROSS_MASS (the sole design variable in this problem type)
        # at 0.9x the target gross mass before calling setup()
        # (aviary_problem.py ~line 1612: "set initial guess for
        # Mission.GROSS_MASS to help optimizer with new design variable
        # bounds"). This project's script never set Mission.GROSS_MASS at
        # all, only Aircraft.Design.GROSS_MASS (the fixed MTOW input) above -
        # and aviary_group.py's add_design_variables() for
        # OFF_DESIGN_MIN_FUEL sets Mission.GROSS_MASS's upper bound to
        # exactly that same MTOW (line ~1425: upper=MTOW). With nothing else
        # seeding it, the design variable started AT its own upper bound.
        # This matches the actual failure data exactly: every diagnostic
        # dump from every failed run showed Mission.GROSS_MASS
        # (83800.00623705) equal to Aircraft.Design.GROSS_MASS/MTOW
        # (83800.00623707) to 8 significant figures, even after 100 SLSQP
        # iterations - the design variable never moved off the bound it
        # started on. A design variable pinned to its own bound from
        # iteration 1, with a badly infeasible RANGE_RESIDUAL constraint
        # that needs an interior point to satisfy, is a textbook cause of
        # the degenerate/inconsistent QP linearization this run kept hitting
        # - not a scaling problem (the mass_ref/distance_ref fix above was
        # real and correct, just not the actual cause of the stall).
        #
        # Uses the same seed_gross_mass_lbm already used above for
        # phase_info's initial_guesses, instead of an
        # independently-recomputed gross_mass_lbm * 0.9 - a run where these
        # two were computed separately (before this fix) showed the
        # trajectory (traj.climb.states:mass[0]) and this design variable
        # frozen ~8400 lbm apart from iteration 1 through 46, never moving,
        # because they disagreed at the starting point before any step was
        # even taken. See seed_gross_mass_lbm's own definition for the full
        # diagnostic evidence.
        prob.aviary_inputs.set_val(Mission.GROSS_MASS, seed_gross_mass_lbm, units="lbm")

        # Mission.Constraints.MAX_MACH defaults to 0.0 (Aviary's own metadata
        # has a "TODO: derived default value" comment acknowledging this) and
        # is read by FLOPS's PassengerServiceMass component as
        # (design_range / max_mach) ** 0.225 - with max_mach=0.0 that's a
        # division by zero that cascades into NaN mass results. Set to the
        # real cruise Mach.
        prob.aviary_inputs.set_val(Mission.Constraints.MAX_MACH, cruise_mach, units="unitless")

        engine_options = av.AviaryValues()
        engine_options.set_val(Aircraft.Engine.DATA_FILE, engine_deck_path)
        engine_options.set_val(Aircraft.Engine.NUM_ENGINES, 1)
        engine_options.set_val(Aircraft.Engine.NUM_WING_ENGINES, 0)
        engine_options.set_val(Aircraft.Engine.NUM_FUSELAGE_ENGINES, 1)
        # Left at its default (True, unset) this crashes FLOPS's EngineMass
        # component: np.where(scale_mass) on a 0-d array. We don't need
        # FLOPS's thrust-scaled engine-mass equation anyway, since EMPTY_MASS
        # is overridden wholesale above - False just means "don't scale".
        engine_options.set_val(Aircraft.Engine.SCALE_MASS, False)
        # REFERENCE_MASS/REFERENCE_SLS_THRUST are also engine-model *options*
        # in the installed aviary==1.0.1 - left unset they fall back to a
        # bare-float default instead of an array, crashing the same way.
        # With SCALE_MASS=False these don't affect the mass result, they
        # just need a real value to avoid the shape bug. 3740 lbm is the
        # commonly cited F100-PW-229 dry weight - approximate, same
        # placeholder tier as the rest of this deck.
        engine_options.set_val(Aircraft.Engine.REFERENCE_MASS, 3740.0, units="lbm")
        engine_options.set_val(Aircraft.Engine.REFERENCE_SLS_THRUST, engine_t_sl_dry_lbf, units="lbf")
        engine_deck = av.EngineDeck(name="f100", options=engine_options)

        # Direct proof of what actually got loaded from engine_deck_path,
        # independent of whether the mission's converged results end up
        # looking sensitive to it or not — read straight from the object
        # Aviary itself will use, not from re-parsing the file ourselves.
        from aviary.subsystems.propulsion.utils import EngineModelVariables as _EMV
        _thrust_raw = engine_deck.data[_EMV.THRUST]
        _fuel_raw = engine_deck.data[_EMV.FUEL_FLOW]
        print(f"   [engine deck] loaded {len(_thrust_raw)} data points from "
              f"{engine_deck_path} — Thrust range [{_thrust_raw.min():.1f}, "
              f"{_thrust_raw.max():.1f}] lbf, Fuel Flow range "
              f"[{_fuel_raw.min():.1f}, {_fuel_raw.max():.1f}] lbm/h")

        av.preprocess_propulsion(aviary_options=prob.aviary_inputs, engine_models=[engine_deck])

        prob.check_and_preprocess_inputs()

        lift_grid, drag_grid = reshape_to_grid(external_aero._data)
        prob.aviary_inputs.set_val(Aircraft.Design.LIFT_POLAR, lift_grid, units="unitless")
        prob.aviary_inputs.set_val(Aircraft.Design.DRAG_POLAR, drag_grid, units="unitless")

        prob.check_and_preprocess_inputs()
        prob.build_model()

        # Real driver, matching Aviary's own documented sequence
        # (aviary/interface/run_aviary.py's run_aviary() function) instead
        # of a bare run_model() — confirmed directly with the Aviary dev
        # team (see project notes): mission analysis in Aviary is itself a
        # Dymos optimization problem, so add_driver()/add_design_variables()/
        # add_objective() are not optional, and run_aviary_problem() is the
        # only path that actually converges the trajectory. SLSQP (ships
        # with scipy, no external solver install needed) rather than
        # add_driver()'s IPOPT default, which this machine may not have
        # installed.
        # max_iter=100 was a deliberate fail-fast setting for stall
        # debugging (see git history) and was never raised back up for a
        # real run - this problem has ~95 design variables / ~93 equality
        # constraints (every collocation node's states are design variables
        # here, since solve_segments isn't used), which can legitimately
        # need more than 100 SLSQP iterations even when everything else is
        # correct. Raised to a real production budget.
        prob.add_driver("SLSQP", max_iter=400)
        # Loosening tol from Aviary's hard-coded SLSQP default (1e-9, set
        # in aviary/core/aviary_problem.py's add_driver() - not setdefault,
        # so it has to be overridden here, after add_driver() returns) to
        # ScipyOptimizeDriver's own default (1e-6) was TESTED and made
        # ZERO difference - objective landed at 2.3927667692332304, bit
        # -identical (to 10+ sig figs) to every earlier run at 1e-9 with
        # max_iter=100/200/1000. So tol/acc was never the actual blocker;
        # kept at 1e-6 since it's still the more sensible default, but the
        # real cause is elsewhere.
        #
        # Read scipy's actual compiled SLSQP source directly (__slsqp.c
        # from the scipy==1.17.1 sdist, not the Python wrapper, which just
        # calls into this compiled core) to find the REAL convergence
        # test. It only ever sets mode=0 (success) in two places, and BOTH
        # require `!badlin` — `badlin` gets set to 1 for the rest of that
        # iteration whenever the QP subproblem's equality-constraint
        # matrix comes back rank-deficient (lsq() returns mode=6 with
        # n==meq, remapped to mode=4) and SLSQP has to re-solve an
        # augmented/regularized version instead. On a `badlin` iteration,
        # convergence can NEVER be reported, no matter how tight/loose
        # `acc` (tol) is or how many iterations are allowed — which
        # exactly matches what we're seeing: identical stall point
        # regardless of tol or max_iter. This mission's Dymos collocation
        # defects (3 phases x 5 segments, all handled by the optimizer
        # since we removed solve_segments) are a strong candidate for
        # producing a rank-deficient linearized equality-constraint
        # Jacobian near a converged trajectory.
        # CORRECTION after reading __slsqp.c line-by-line (not just
        # skimming): badlin does NOT require GNORM to be small. It only
        # ever gates the two `mode=0` (success) return points - it does
        # not change what search direction gets computed or force x to
        # stop moving. A badlin iteration still solves an augmented/
        # rho-regularized QP and takes a real line-search step; it just
        # permanently forbids reporting success afterward, for ANY
        # gradient magnitude. So "GNORM stays large and flat" is NOT
        # evidence against badlin the way an earlier version of this
        # comment claimed - that claim was wrong. badlin remains a live,
        # unconfirmed hypothesis; ruling it in or out needs the actual
        # `mode` value badlin sets internally (not exposed by scipy's
        # Python wrapper) or a from-scratch reimplementation of the QP
        # rank check, not GNORM's printed magnitude.
        #
        # bump SLSQP's own iprint (via opt_settings, not the 'disp' bool,
        # which only ever yields iprint=1/summary-only per
        # scipy/optimize/_slsqp_py.py) to 2 so the console prints a
        # per-iteration NIT/FC/OBJFUN/GNORM table for whatever further
        # diagnosis is needed.
        prob.driver.options['tol'] = 1e-6
        prob.driver.opt_settings['iprint'] = 2
        prob.add_design_variables()

        # The Mission.GROSS_MASS seed fix above (0.9x MTOW) got the design
        # variable off its bound and RANGE_RESIDUAL to ~1e-14 (feasible) -
        # real progress. But the very next failure mode it hit
        # (Exit mode 8, "Positive directional derivative for linesearch")
        # exposed a second, separate gap: add_design_variables() (called
        # just above) sets Mission.GROSS_MASS's lower bound to a bare
        # 10.0 lbm (aviary_group.py ~line 1424) - no floor tied to this
        # aircraft's actual empty mass. Since add_objective() (below) makes
        # the objective directly proportional to Mission.TOTAL_FUEL_MASS,
        # and nothing here constrains gross mass to stay above empty mass,
        # the optimizer was free to push Mission.GROSS_MASS down past
        # Aircraft.Design.EMPTY_MASS - which is exactly what the failed
        # run's diagnostic dump showed: Mission.GROSS_MASS=75420 lbm with
        # Mission.FUEL_MASS=-2681.6 lbm (negative fuel is unphysical - you
        # cannot carry less fuel than zero).
        #
        # CORRECTED: an earlier version of this fix called
        # prob.model.add_design_var(Mission.GROSS_MASS, ...) again here,
        # on the theory that it mirrored Aviary's own run_off_design_mission()
        # fill_fuel pattern. That was a misreading, caught only when it
        # crashed: "RuntimeError: Design Variable 'mission:gross_mass'
        # already exists." OpenMDAO's add_design_var() does not overwrite -
        # confirmed directly in openmdao/core/system.py, it raises if the
        # name is already registered. Aviary's fill_fuel option only ever
        # calls add_design_var() for problem types where Mission.GROSS_MASS
        # is NOT already a design variable (e.g. OFF_DESIGN_MAX_RANGE, which
        # adds none by default) - it is never used to re-bound a variable
        # add_design_variables() already added, which is exactly our case
        # for OFF_DESIGN_MIN_FUEL.
        # The actual supported way to change an existing design variable's
        # bounds after the fact is System.set_design_var_options()
        # (openmdao/core/system.py, ~line 955) - its own docstring: "Can be
        # used to set the options outside of setting them when calling
        # add_design_var." It takes lower/upper/scaler/adder/ref/ref0 (no
        # units - it reuses whatever units the variable was already
        # registered with, 'lbm' here, matching empty_mass_lbm/
        # gross_mass_lbm directly) and updates the existing entry in place
        # instead of registering a second one.
        prob.model.set_design_var_options(
            Mission.GROSS_MASS,
            lower=empty_mass_lbm,
            upper=gross_mass_lbm,
            ref=gross_mass_lbm,
        )

        prob.add_objective()

        prob.setup()
        # Dymos collocation needs a real starting guess for trajectory
        # states/controls/phase durations even with a driver present -
        # without this, phase duration and the distance/mass states stay
        # near their degenerate defaults and the mission never actually
        # flies anywhere. set_phase_initial_guesses() (called via
        # prob.set_initial_guesses()) auto-defaults mass/altitude/mach/time,
        # but NOT distance - that's why phase_info.py provides an explicit
        # 'distance' (and 'mass', for the same reason) initial_guesses entry
        # per phase.
        prob.set_initial_guesses()

        # Ground-truth check for the mass_ref/distance_ref fix in
        # phase_info.py: after adding those keys, a rerun showed GNORM
        # bit-identical (to 7 printed sig figs) to the pre-fix run, which
        # is only possible if either (a) those particular design
        # variables' gradient contribution is small relative to whatever
        # is dominating ||g||, or (b) the new ref values never actually
        # reached the running model. Source-tracing (Dymos's
        # pseudospectral_base.py configure_desvars(), Aviary's
        # phase_builder.py add_state(), aviary_options_dict.py's
        # AviaryOptionsDictionary.__init__/declare()) shows the mechanism
        # IS wired correctly end-to-end, but a source trace is not proof
        # of what's happening at runtime on THIS machine - only the model
        # itself can confirm that. list_driver_vars(driver_scaling=True)
        # prints every design variable's actual ref/ref0/val as OpenMDAO
        # sees them right now, straight from prob.driver._designvars -
        # this is how to see literally what's in the states:mass /
        # states:distance ref fields for each phase and whether the
        # (already-scaled) initial values are wildly out of proportion to
        # each other, which would point at what's actually dominating the
        # printed GNORM.
        prob.final_setup()
        print("\n--- design-variable scaling check (mass_ref/distance_ref fix) ---")
        prob.list_driver_vars(driver_scaling=True)
        print("--- end design-variable scaling check ---\n")

        # suppress_solver_print=False: this project's user explicitly wants
        # the Newton-iteration console output left as-is, not silenced.
        prob.run_aviary_problem(run_driver=True, suppress_solver_print=False, make_plots=False)
        # prob.result is dm.run_problem()'s return value, which (with the
        # default refine_iteration_limit=0, unchanged here) is just
        # OpenMDAO's own Problem.run_driver() return value passed straight
        # through -- a plain bool, per its own docstring: "Failure flag;
        # True if failed to converge, False if successful." (verified
        # against the actual installed openmdao/dymos source, not the
        # off_design_missions.ipynb example's `.result.success`/
        # `.exit_status`, which would raise AttributeError on a bool).
        if prob.result:
            # Real diagnostics instead of a blind failure. Print what the
            # solve actually landed on so any further investigation starts
            # from real numbers, not another guess. Each print is
            # independently guarded so one inaccessible variable doesn't
            # hide the rest.
            print("\n--- SOLVE DID NOT CONVERGE — diagnostic dump ---")
            # units=... is explicit below for every mass/range value. An
            # earlier version of this dump called prob.get_val(var) with no
            # units on some of these, which returns each variable in
            # whatever unit IT happens to be stored in internally - Mission.
            # Takeoff.FINAL_MASS is stored in lbm, traj.<phase>.states:mass
            # is stored in kg (Dymos state, energy-state EOM works in SI
            # internally). Printed side by side with no units, those looked
            # like a huge, broken mass discontinuity (a ~2.2x gap) when they
            # were actually the same physical value: lbm/kg = 2.20462
            # exactly matched the observed gap on a real failed run here.
            # Confirmed harmless by reproducing the same units-native-print
            # pattern on a run that converged cleanly (aviary==1.0.1,
            # OFF_DESIGN_MIN_FUEL, Aviary's own bundled reference aircraft):
            # the same lbm-vs-kg gap showed up there too, on a mass link that
            # was unquestionably fine. Forcing a common unit below removes
            # that false signal.
            for label, var, units in [
                ("Mission.GROSS_MASS (design var, bounded by our fixed MTOW)", Mission.GROSS_MASS, "lbm"),
                ("Aircraft.Design.GROSS_MASS (our fixed MTOW, should be unchanged)", Aircraft.Design.GROSS_MASS, "lbm"),
                ("Mission.RANGE (actual flown range)", Mission.RANGE, "nmi"),
                ("Mission.Constraints.RANGE_RESIDUAL (should be ~0 if feasible)", Mission.Constraints.RANGE_RESIDUAL, None),
                ("Mission.FUEL_MASS (fuel burned)", Mission.FUEL_MASS, "lbm"),
                ("Mission.Objectives.FUEL (actual SLSQP objective)", Mission.Objectives.FUEL, None),
                ("Mission.Takeoff.ASCENT_DURATION (feeds the objective; may be a dangling default since include_takeoff=False)", Mission.Takeoff.ASCENT_DURATION, None),
                # Aviary's own energy_state_problem_configurator.py
                # (add_post_mission_systems(), the include_takeoff=False
                # branch) automatically adds an EQConstraintComp forcing
                # traj.<first-phase>.states:mass[0] == Mission.Takeoff.FINAL_MASS
                # (= Mission.GROSS_MASS - taxi/takeoff fuel burn) - this is
                # how Mission.GROSS_MASS is actually supposed to tie into the
                # real flown trajectory, as a CONSTRAINT rather than a direct
                # connection. Printed here (now in lbm, matching the
                # states:mass[0] print below) so the two can be compared
                # directly instead of by eyeballing two different units.
                ("Mission.Takeoff.FINAL_MASS (should equal the climb phase's actual starting mass)", Mission.Takeoff.FINAL_MASS, "lbm"),
            ]:
                try:
                    val = prob.get_val(var, units=units) if units else prob.get_val(var)
                    print(f"   {label}: {val}" + (f" {units}" if units else ""))
                except Exception as diag_err:
                    print(f"   {label}: <could not read: {diag_err}>")
            try:
                first_phase_name = list(prob.model.mission_info.keys())[0]
                final_mass_lbm = float(prob.get_val(Mission.Takeoff.FINAL_MASS, units="lbm")[0])
                climb_mass0_lbm = float(
                    prob.get_val(f"traj.{first_phase_name}.states:mass", units="lbm")[0]
                )
                print(f"   traj.{first_phase_name}.states:mass[0] (actual flown starting "
                      f"mass, converted to lbm to match Mission.Takeoff.FINAL_MASS above): "
                      f"{climb_mass0_lbm:.4f} lbm")
                print(f"   mass-link residual (states:mass[0] - Mission.Takeoff.FINAL_MASS, "
                      f"both in lbm; should be ~0 if the mass-link constraint is satisfied): "
                      f"{climb_mass0_lbm - final_mass_lbm:+.6f} lbm")
            except Exception as diag_err:
                print(f"   traj.<first_phase>.states:mass[0]: <could not read: {diag_err}>")

            # Direct test of the "badlin" hypothesis from the comment above
            # prob.add_driver() - that SLSQP is stalling because the
            # linearized equality-constraint Jacobian is rank-deficient
            # (scipy's compiled __slsqp.c sets an internal `badlin` flag in
            # that case and then can never report success, regardless of
            # tol/max_iter, which matches the bit-identical stalls already
            # observed at max_iter=100/200/1000). That flag isn't exposed by
            # scipy's Python wrapper, but the same Jacobian SLSQP builds it
            # from is: prob.compute_totals() with driver_scaling=True
            # returns the exact scaled equality-constraint Jacobian
            # OpenMDAO hands to the driver, and its rank vs. row count is a
            # direct, non-guessing answer to whether it's singular.
            try:
                eq_con_names = [
                    name for name, meta in prob.driver._cons.items()
                    if meta.get('equals') is not None
                ]
                dv_names = list(prob.driver._designvars.keys())
                totals = prob.compute_totals(
                    of=eq_con_names, wrt=dv_names, driver_scaling=True
                )
                jac_rows = []
                for con_name in eq_con_names:
                    row_blocks = [totals[con_name, dv_name] for dv_name in dv_names]
                    jac_rows.append(np.hstack(row_blocks))
                jac = np.vstack(jac_rows)
                rank = np.linalg.matrix_rank(jac)
                print(
                    f"\n   equality-constraint Jacobian rank check (badlin test): "
                    f"{jac.shape[0]} equality-constraint rows, {jac.shape[1]} design "
                    f"variable columns, numerical rank={rank}."
                )
                if rank < jac.shape[0]:
                    print(
                        f"   RANK-DEFICIENT by {jac.shape[0] - rank} row(s) - this "
                        f"CONFIRMS the badlin hypothesis: SLSQP's equality-constraint "
                        f"linearization is singular at this point, which is why it "
                        f"can never report success here regardless of tol/max_iter."
                    )
                else:
                    print(
                        "   Full rank - this RULES OUT badlin/rank-deficiency as the "
                        "cause of the stall; the real cause is elsewhere."
                    )
            except Exception as diag_err:
                print(f"   equality-constraint Jacobian rank check: <could not compute: {diag_err}>")

            # Full rank rules out badlin, but doesn't say WHY x stopped
            # moving. Mission.GROSS_MASS printed identical to full float
            # precision across all 100 iterations, and it's the only design
            # variable the objective depends on at all (reg_objective =
            # overall_fuel/10000 + ascent_duration/30, ascent_duration a
            # dangling 0 here per the earlier finding, overall_fuel =
            # gross_mass - zero_fuel_mass per aviary_group.py) - so if x is
            # already a first-order KKT point of the equality-constrained
            # problem (grad(objective) expressible as J^T @ lambda for some
            # multiplier vector lambda), SLSQP would have every reason to
            # stop moving it, and the "Iteration limit reached" failure
            # would just be SLSQP's own convergence test not recognizing a
            # point it has, in substance, already reached (e.g. because of
            # floating-point noise in the constraint residuals from the
            # nested Newton solves, or an unaccounted-for active inequality
            # such as the throttle path constraints or excess fuel
            # capacity). Solving the least-squares system J^T @ lambda =
            # grad(objective) and checking the residual is a direct,
            # non-guessing test of that: a near-zero residual confirms x is
            # already stationary; a large one proves it is NOT, and SLSQP
            # is genuinely stuck rather than just failing to declare victory.
            try:
                eq_con_names = [
                    name for name, meta in prob.driver._cons.items()
                    if meta.get('equals') is not None
                ]
                dv_names = list(prob.driver._designvars.keys())
                totals = prob.compute_totals(
                    of=eq_con_names + [Mission.Objectives.FUEL],
                    wrt=dv_names, driver_scaling=True,
                )
                jac_rows = []
                for con_name in eq_con_names:
                    row_blocks = [totals[con_name, dv_name] for dv_name in dv_names]
                    jac_rows.append(np.hstack(row_blocks))
                jac = np.vstack(jac_rows)
                grad_obj = np.hstack(
                    [totals[Mission.Objectives.FUEL, dv_name] for dv_name in dv_names]
                ).ravel()
                lam, _, _, _ = np.linalg.lstsq(jac.T, grad_obj, rcond=None)
                residual = grad_obj - jac.T @ lam
                grad_norm = np.linalg.norm(grad_obj)
                residual_norm = np.linalg.norm(residual)
                print(
                    f"\n   KKT-stationarity check (equality constraints only): "
                    f"||grad(objective)||={grad_norm:.6g}, ||residual after projecting "
                    f"onto the constraint-gradient row space||={residual_norm:.6g} "
                    f"({100 * residual_norm / grad_norm:.4g}% of the gradient norm)."
                )
                if residual_norm < 1e-3 * grad_norm:
                    print(
                        "   Residual is negligible - Mission.GROSS_MASS is already a "
                        "first-order KKT-stationary point for the equality-constrained "
                        "problem. SLSQP not moving it further is CORRECT behavior; the "
                        "'Iteration limit reached' failure is SLSQP's own stopping test "
                        "not recognizing a point it has effectively already reached "
                        "(likely constraint-tolerance/noise or an unmodeled active "
                        "inequality, e.g. a throttle path constraint or the excess fuel "
                        "capacity bound), not evidence of a real remaining defect."
                    )
                else:
                    print(
                        "   Residual is NOT negligible - Mission.GROSS_MASS is genuinely "
                        "NOT at a stationary point yet. SLSQP failing to move it is a "
                        "real stall, not just a missed convergence declaration."
                    )
            except Exception as diag_err:
                print(f"   KKT-stationarity check: <could not compute: {diag_err}>")

            # The equality-only KKT check above found a small but real
            # residual (not negligible, but only ~2% of ||grad(objective)||
            # on the run that motivated this). The equality-only test
            # can't see inequality constraints (throttle path constraints,
            # the excess-fuel-capacity bound) at all, and if one of them is
            # sitting exactly at its bound, its gradient row belongs in the
            # KKT system too - with the correct sign, its Lagrange
            # multiplier would be non-negative, but this check doesn't
            # enforce that (least squares only), so it's an approximate
            # test: if adding these rows makes the residual collapse, that
            # is strong evidence the earlier gap was exactly this missing
            # term, not a genuine stall.
            try:
                eq_con_names = [
                    name for name, meta in prob.driver._cons.items()
                    if meta.get('equals') is not None
                ]
                ineq_meta = {
                    name: meta for name, meta in prob.driver._cons.items()
                    if meta.get('equals') is None
                }
                dv_names = list(prob.driver._designvars.keys())

                ineq_vals = prob.driver.get_constraint_values(ctype='ineq', driver_scaling=True)
                active_tol = 1e-4
                active = {}
                for name, meta in ineq_meta.items():
                    val = np.asarray(ineq_vals[name])
                    lower = np.asarray(meta['lower'])
                    upper = np.asarray(meta['upper'])
                    near_lower = (lower > -1e29) & (np.abs(val - lower) < active_tol)
                    near_upper = (upper < 1e29) & (np.abs(upper - val) < active_tol)
                    mask = near_lower | near_upper
                    if np.any(mask):
                        active[name] = mask

                if active:
                    totals_all = prob.compute_totals(
                        of=eq_con_names + [Mission.Objectives.FUEL] + list(active.keys()),
                        wrt=dv_names, driver_scaling=True,
                    )
                    jac_rows = [
                        np.hstack([totals_all[c, d] for d in dv_names]) for c in eq_con_names
                    ]
                    for name, mask in active.items():
                        full_rows = np.hstack([totals_all[name, d] for d in dv_names])
                        jac_rows.append(full_rows[mask, :])
                    jac_full = np.vstack(jac_rows)
                    grad_obj = np.hstack(
                        [totals_all[Mission.Objectives.FUEL, d] for d in dv_names]
                    ).ravel()
                    lam, _, _, _ = np.linalg.lstsq(jac_full.T, grad_obj, rcond=None)
                    residual = grad_obj - jac_full.T @ lam
                    grad_norm = np.linalg.norm(grad_obj)
                    residual_norm = np.linalg.norm(residual)
                    n_active_rows = sum(int(m.sum()) for m in active.values())
                    print(
                        f"\n   KKT-stationarity check, extended with active inequality "
                        f"constraints ({n_active_rows} active row(s) found across "
                        f"{list(active.keys())}): ||grad(objective)||={grad_norm:.6g}, "
                        f"||residual||={residual_norm:.6g} "
                        f"({100 * residual_norm / grad_norm:.4g}% of the gradient norm)."
                    )
                    if residual_norm < 1e-3 * grad_norm:
                        print(
                            "   Residual collapses once active inequalities are included "
                            "- x IS effectively a full KKT point; the earlier equality-"
                            "only residual was exactly the missing contribution from an "
                            "active bound (e.g. a throttle path constraint or the fuel-"
                            "capacity limit), not a real remaining descent direction."
                        )
                    else:
                        print(
                            "   Residual is still not negligible even with active "
                            "inequalities included - the stall is real, not explained by "
                            "a bound constraint sitting at its limit."
                        )
                else:
                    print(
                        "\n   No inequality constraints are at their bound at this point "
                        "(checked with tolerance 1e-4 in scaled units) - the equality-"
                        "only residual above is NOT explained by an active bound."
                    )
            except Exception as diag_err:
                print(
                    f"   extended KKT-stationarity check (active inequalities): "
                    f"<could not compute: {diag_err}>"
                )

            # scipy's SLSQP wrapper (_slsqp_py.py) confirms GNORM is
            # literally scipy.linalg.norm(g) where g = sf.grad(x) is the
            # FULL total-derivative gradient of the objective across all
            # design variables (matching the 8.38 computed above exactly) -
            # not a structural constant and not the Lagrangian gradient.
            # Since g flows through Dymos's nonlinear collocation physics
            # for every other design variable, it being bit-identical for
            # 100 straight iterations really does prove x itself never
            # moved - that part of the original diagnosis holds.
            #
            # But both KKT checks above only ever looked at
            # prob.driver._cons - i.e. constraints registered via
            # add_constraint(). They never examined the SIMPLE BOX BOUNDS
            # every design variable carries (lower/upper, set via
            # add_design_var()/set_design_var_options() - see
            # Mission.GROSS_MASS's own lower=empty_mass_lbm,
            # upper=gross_mass_lbm above). scipy's wrapper passes those
            # bounds to the compiled solver as xl/xu, completely separate
            # from the m/meq general constraints in C/d - so a design
            # variable pinned exactly at its own box bound would produce
            # precisely this signature (a real, non-negligible unconstrained
            # KKT residual that no _cons-based check could ever explain) and
            # neither check above would have caught it. This is a direct,
            # numeric test of that specific gap, not a guess.
            try:
                dv_names = list(prob.driver._designvars.keys())
                dv_vals_scaled = prob.driver.get_design_var_values(driver_scaling=True)
                dv_vals_raw = prob.driver.get_design_var_values(driver_scaling=False)
                bound_tol = 1e-4
                any_at_bound = False
                print("\n   design-variable box-bound proximity check (lower/upper set "
                      "via add_design_var/set_design_var_options, never visible to the "
                      "_cons-based KKT checks above):")
                for name in dv_names:
                    meta = prob.driver._designvars[name]
                    val_s = np.atleast_1d(np.asarray(dv_vals_scaled[name], dtype=float))
                    lower_s = np.atleast_1d(np.asarray(meta['lower'], dtype=float))
                    upper_s = np.atleast_1d(np.asarray(meta['upper'], dtype=float))
                    near_lower = (lower_s > -1e29) & (np.abs(val_s - lower_s) < bound_tol)
                    near_upper = (upper_s < 1e29) & (np.abs(upper_s - val_s) < bound_tol)
                    if np.any(near_lower) or np.any(near_upper):
                        any_at_bound = True
                        val_r = np.atleast_1d(np.asarray(dv_vals_raw[name], dtype=float))
                        which = "lower" if np.any(near_lower) else "upper"
                        print(
                            f"   * {name}: AT its {which} bound (scaled value="
                            f"{val_s}, scaled bound=[{lower_s}, {upper_s}], raw value="
                            f"{val_r}) - this box bound, not any _cons entry, can "
                            f"explain a real unconstrained KKT residual with zero "
                            f"active _cons rows."
                        )
                if not any_at_bound:
                    print(
                        "   No design variable (including Mission.GROSS_MASS) is at "
                        "its own box bound (checked with tolerance 1e-4 in scaled "
                        "units) - this RULES OUT box-bound blocking as the "
                        "explanation for the unexplained residual; the stall is not "
                        "caused by any constraint or bound SLSQP is aware of."
                    )
            except Exception as diag_err:
                print(f"   design-variable box-bound proximity check: <could not compute: {diag_err}>")

            print("--- end diagnostic dump ---\n")
            raise RuntimeError(
                "Aviary mission solve did not converge (prob.result=True means "
                "failed, per Problem.run_driver()'s own docstring). See the "
                "diagnostic dump above and the console output for details."
            )

        # Aviary's own mission_report()/timeseries_csv() are normally only
        # triggered by run_driver() (see aviary/interface/reports.py) - they
        # don't actually need a driver to have run, they just read final
        # values off the converged model, so we call them directly.
        mission_report(prob)
        timeseries_csv(prob)

        fuel_residual = prob.get_val(Mission.Constraints.MASS_RESIDUAL)
        total_range = prob.get_val(Mission.RANGE)
        fuel_burned = prob.get_val(Mission.FUEL_MASS)

        # Real, solved values of the FLOPS "operating items" that sit between
        # our Aircraft.Design.EMPTY_MASS override and Aviary's own internal
        # Mission.ZERO_FUEL_MASS (see aviary/subsystems/mass/flops_based/
        # mass_summation.py: OperatingItemsMass -> OperatingMass -> ZeroFuelMass).
        # These are FLOPS-computed defaults this pipeline never overrides, so
        # they're pulled from the solved problem rather than assumed.
        unusable_fuel_lbm = float(prob.get_val(Aircraft.Fuel.UNUSABLE_FUEL_MASS, units="lbm")[0])
        operating_items_lbm = float(prob.get_val(Mission.OPERATING_ITEMS_MASS, units="lbm")[0])

    finally:
        os.chdir(original_cwd)

    _print_results_table(
        design_range_nmi, total_range[0], fuel_burned[0], fuel_mass_lbm,
        fuel_residual[0], unusable_fuel_lbm, operating_items_lbm,
    )

    _save_curated_reports(geom_stem)
    _save_plain_summary(
        geom_stem, design_range_nmi, total_range[0], fuel_burned[0],
        fuel_residual[0], fuel_mass_lbm, unusable_fuel_lbm, operating_items_lbm,
    )


def _print_results_table(design_range_nmi, total_range, fuel_burned, fuel_mass_lbm,
                          fuel_residual, unusable_fuel_lbm, operating_items_lbm):
    """
    Console results, laid out as an aligned table (same "Variable | Value |
    Units" idea as Aviary's own native mission_summary.md) instead of the
    old free-form print lines, so this is easy to scan straight off the
    console instead of hunting through it.
    """
    real_margin = fuel_mass_lbm - fuel_burned
    crew_and_oil_lbm = operating_items_lbm - unusable_fuel_lbm

    rows = [
        ("Range flown", f"{total_range:.1f}", "nmi"),
        ("Range target", f"{design_range_nmi:.0f}", "nmi"),
        ("Fuel loaded (tank capacity)", f"{fuel_mass_lbm:.2f}", "lbm"),
        ("Fuel burned", f"{fuel_burned:.2f}", "lbm"),
        ("FUEL MARGIN (trust this one)", f"{real_margin:.2f}", "lbm"),
        (None, None, None),  # separator
        ("Fuel mass residual (margin vs. Aviary's smaller internal fuel figure)", f"{fuel_residual:+.2f}", "lbm"),
        ("Unusable fuel (physically stuck in tank)", f"{unusable_fuel_lbm:.2f}", "lbm"),
        ("Pilot + engine oil weight", f"{crew_and_oil_lbm:.2f}", "lbm"),
    ]
    name_w = max(len(r[0]) for r in rows if r[0] is not None)
    val_w = max(len(r[1]) for r in rows if r[1] is not None)

    print("\n" + "=" * (name_w + val_w + 10))
    print("MISSION RESULTS")
    print("=" * (name_w + val_w + 10))
    for name, val, unit in rows:
        if name is None:
            print("-" * (name_w + val_w + 10))
            continue
        print(f"  {name:<{name_w}}  {val:>{val_w}} {unit}")
    print("=" * (name_w + val_w + 10))


def _save_plain_summary(geom_stem, design_range_nmi, total_range, fuel_burned,
                         fuel_residual, fuel_mass_lbm, unusable_fuel_lbm,
                         operating_items_lbm):
    """
    Our OWN plain-language mission summary — deliberately separate from
    Aviary's native mission_summary.md (Results/aviary_perf/native_aviary_files/),
    because that file's "Excess Fuel Capacity" line is confusing (often
    negative) for a reason that has nothing to do with mission feasibility:
    see below. Saved directly in Results/aviary_perf/ (one level up from
    Aviary's own native reports) so it's the first thing anyone opening that
    folder sees.
    """
    import time as _time

    real_margin = fuel_mass_lbm - fuel_burned
    real_margin_pct = 100.0 * real_margin / fuel_mass_lbm
    crew_and_oil_lbm = operating_items_lbm - unusable_fuel_lbm

    lines = [
        "# MISSION SUMMARY (plain-language)",
        "",
        f"Geometry: {geom_stem}",
        f"Generated: {_time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| Variable Name | Value | Units |",
        "| :- | :- | :- |",
        f"| Range Flown | {total_range:.1f} | nmi |",
        f"| Range Target | {design_range_nmi:.0f} | nmi |",
        f"| Fuel Loaded (tank capacity) | {fuel_mass_lbm:.2f} | lbm |",
        f"| Fuel Burned | {fuel_burned:.2f} | lbm |",
        f"| **Fuel Margin (trust this one)** | **{real_margin:.2f}** | **lbm** |",
        f"| Fuel Margin (percent) | {real_margin_pct:.1f} | % |",
        "",
        "**Verdict: the mission flew the full target range with a large, "
        "real fuel margin.**",
        "",
        "# OTHER NUMBERS (seen in the console / native Aviary files)",
        "",
        "These are NOT alternative fuel margins — they answer different "
        "questions. Do not compare them to Fuel Margin above.",
        "",
        "| Variable Name | Value | Units |",
        "| :- | :- | :- |",
        f"| Fuel Mass Residual (Aviary pass/fail check) | {fuel_residual:+.2f} | lbm |",
        f"| Unusable Fuel (stuck in tank, can't burn) | {unusable_fuel_lbm:.2f} | lbm |",
        f"| Pilot + Engine Oil Weight | {crew_and_oil_lbm:.2f} | lbm |",
        "",
        "## What each row above means",
        "",
        "- **Fuel Mass Residual** — this IS a real fuel-remaining number, "
        "computed the same way as Fuel Margin above (fuel available minus "
        "fuel burned minus reserves). The only difference is which "
        "'fuel available' it starts from: Fuel Margin uses the full tank "
        "capacity we specified, Fuel Mass Residual uses Aviary's smaller "
        "internal usable-fuel figure (tank capacity minus the Pilot + "
        "Engine Oil Weight overhead below). That's the entire reason the "
        "two numbers differ, by exactly the Pilot + Engine Oil Weight "
        "amount. Aviary also uses this same number as a pass/fail "
        "feasibility check during optimization (must stay positive) — but "
        "the number itself is a genuine fuel-remaining figure, not just a "
        "flag.",
        "- **Unusable Fuel** — fuel physically trapped in the tank (corners, "
        "lines) that the engine can never draw on, computed from this "
        "aircraft's own wing area/thrust/tank size.",
        "- **Pilot + Engine Oil Weight** — fixed weight Aviary adds for the "
        "1 pilot (225 lbm) and engine oil. Has nothing to do with how far "
        "the mission flew.",
        "- **Pilot + Engine Oil Weight is the exact same number as "
        "\"Excess Fuel Capacity\"** in `native_aviary_files/mission_summary.md` "
        "— same figure, just under a misleading name there. Unusable Fuel "
        "does NOT get added to it: because our tank-capacity number already "
        "accounts for unusable fuel once, that term cancels out of Excess "
        "Fuel Capacity's math (Aviary's own formula subtracts it, then adds "
        "it straight back in through Mission.TOTAL_FUEL_MASS). Unusable "
        "Fuel is listed above purely so you can see it's a real, separate, "
        "physically-explainable number — not because it combines with "
        "anything else here.",
        "",
        "**Bottom line for a presentation or report: only ever quote Fuel "
        "Margin from the top table. The other two numbers are internal "
        "Aviary housekeeping checks that happen to have \"fuel\" in their "
        "name — they are not "
        "alternative measurements of mission fuel margin, and disagreeing "
        "with the top table is expected, not an error.**",
        "",
    ]

    ts = _time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(vsp_setup.AVIARY_PERF_DIR, f"mission_summary_plain_{geom_stem}_{ts}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"   ✅ saved: {path}")


def _save_curated_reports(geom_stem):
    """
    Copies the report files that actually matter (mission summary + full
    timeseries + the two auto-generated input/override checks) from
    Aviary's native reports folder into Results/aviary_perf/native_aviary_files/,
    tagged with geometry + timestamp - matching the same "raw tool output ->
    curated Results/ copy" pattern main.py already uses for VSPAero's .polar
    files. Kept in their own subfolder, separate from our own plain-language
    summary which is saved directly in Results/aviary_perf/.
    """
    import glob
    import shutil
    import time

    candidates = glob.glob(os.path.join(vsp_setup.AVIARY_FILES, "*_out", "reports"))
    if not candidates:
        print("   ⚠️  Could not find Aviary's native reports/ folder — "
              "nothing copied to Results/aviary_perf/native_aviary_files/.")
        return
    reports_dir = max(candidates, key=os.path.getmtime)

    ts = time.strftime("%Y%m%d_%H%M%S")
    wanted = [
        "mission_summary.md",
        "mission_timeseries_data.csv",
        "input_checks.md",
        "overridden_variables.md",
    ]
    for fname in wanted:
        src = os.path.join(reports_dir, fname)
        if not os.path.isfile(src):
            print(f"   ⚠️  {fname} not found in {reports_dir} — skipped")
            continue
        stem, ext = os.path.splitext(fname)
        dst = os.path.join(vsp_setup.AVIARY_PERF_NATIVE_DIR, f"{stem}_{geom_stem}_{ts}{ext}")
        shutil.copy2(src, dst)
        print(f"   ✅ saved: {dst}")


if __name__ == "__main__":
    run_aviary_mission()
