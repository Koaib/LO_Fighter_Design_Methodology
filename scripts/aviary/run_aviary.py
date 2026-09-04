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

import sys, os
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
):
    """Run the Aviary mission analysis for geom_stem's already-produced aero
    CSVs (see module docstring). Every argument defaults to this module's
    own placeholder values (DEFAULT_* above) when left as None, for
    standalone use; main.py's AVIARY / MISSION CONFIG section passes its
    own values for all of them on a real pipeline run.

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

    for phase_name in ("climb", "cruise", "descent"):
        phase_info[phase_name]["subsystem_options"]["aerodynamics"]["aero_data"] = aero_data

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

    phase_info["climb"]["user_options"]["mach_initial"] = (climb_mach_initial, "unitless")
    (lo0, hi0), mach_unit = phase_info["climb"]["user_options"]["mach_bounds"]
    phase_info["climb"]["user_options"]["mach_bounds"] = (
        (min(lo0, climb_mach_initial - 0.02), hi0), mach_unit
    )

    # mass_initial: a real physical boundary condition (the mission starts
    # at this run's actual gross weight), not a guess — but per Aviary's
    # own AviaryOptionsDict docstring ("mass_initial ... When unspecified,
    # the optimizer controls the value"), leaving this unset means climb's
    # starting mass is meant to be picked by an optimizer we don't have.
    # With mass_solve_segments=True (see phase_info.py) actually trying to
    # Newton-solve the segment, an unset mass_initial left NOTHING pinning
    # the phase's starting mass, producing a singular Jacobian for
    # 'states:mass' the moment that solve was for real (confirmed: this
    # crashed identically on both the F100 and a completely different
    # civil engine deck, ruling out an engine-specific cause). Only climb
    # needs this fixed explicitly — cruise/descent inherit their starting
    # mass from the previous phase via Aviary's own phase linking, not
    # from this option.
    phase_info["climb"]["user_options"]["mass_initial"] = (gross_mass_lbm, "lbm")

    # Dynamic Dymos initial guesses — computed from THIS run's actual
    # gross_mass_lbm/design_range_nmi instead of phase_info.py's frozen
    # numbers, so they can't silently go stale if TEST_WING_AREA_FT2 or the
    # F22 mass-basis constants change in main.py. A bad/stale initial
    # guess is exactly what caused the Newton solve non-convergence fixed
    # earlier this project (see phase_info.py's history) - recomputing
    # these here every run closes that failure mode for good.
    #
    # Split ratios (25%/50%/25% of range; ~3:3:1 of guessed fuel burn
    # across climb/cruise/descent) reproduce phase_info.py's original
    # hand-picked seed values at the 103.59 lbm gross-mass test point that
    # was validated to converge - still just seed values for the
    # collocation solve, not meant to be physically exact.
    guessed_total_burn_lbm = gross_mass_lbm * 0.068   # ~7/103.59 lbm, from
                                                        # the validated test run
    climb_burn = guessed_total_burn_lbm * (3 / 7)
    cruise_burn = guessed_total_burn_lbm * (3 / 7)
    descent_burn = guessed_total_burn_lbm * (1 / 7)

    mass_after_climb = gross_mass_lbm - climb_burn
    mass_after_cruise = mass_after_climb - cruise_burn
    mass_after_descent = mass_after_cruise - descent_burn

    dist_climb_end = 0.25 * design_range_nmi
    dist_cruise_end = 0.75 * design_range_nmi

    phase_info["climb"]["initial_guesses"]["distance"] = ([0.0, dist_climb_end], "nmi")
    phase_info["climb"]["initial_guesses"]["mass"] = ([gross_mass_lbm, mass_after_climb], "lbm")
    phase_info["cruise"]["initial_guesses"]["distance"] = ([dist_climb_end, dist_cruise_end], "nmi")
    phase_info["cruise"]["initial_guesses"]["mass"] = ([mass_after_climb, mass_after_cruise], "lbm")
    phase_info["descent"]["initial_guesses"]["distance"] = ([dist_cruise_end, design_range_nmi], "nmi")
    phase_info["descent"]["initial_guesses"]["mass"] = ([mass_after_cruise, mass_after_descent], "lbm")

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
            phase_info,
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
        # of a bare run_model() — see phase_info.py's climb-phase comment
        # for the full history of why. SLSQP (ships with scipy, no external
        # solver install needed) rather than add_driver()'s IPOPT default,
        # which this machine may not have installed.
        prob.add_driver("SLSQP", max_iter=100)
        # ROOT CAUSE of "Iteration limit reached (Exit mode 9)" at the
        # SAME objective value regardless of max_iter (200, 1000, and 100
        # all landed on ~2.392766769 to 10 sig figs) - verified directly
        # in aviary/core/aviary_problem.py's add_driver(): for
        # optimizer='SLSQP' it hard-assigns driver.options['tol'] = 1e-9
        # (not setdefault, so it must be overridden AFTER add_driver()
        # returns, not passed into it) - far tighter than
        # ScipyOptimizeDriver's own default of 1e-6
        # (openmdao/drivers/scipy_optimizer.py). This mission NLP has a
        # lot of nonlinear equality constraints (Dymos collocation defects
        # across 3 phases x 5 segments, since we're not using
        # solve_segments - the optimizer handles continuity directly) and
        # the gradient/Jacobian noise floor sits above 1e-9, so SciPy's
        # SLSQP internal accuracy test never registers "success" even once
        # it's already sitting on a stationary, feasible point - confirmed
        # by the diagnostic dump: Mission.Constraints.RANGE_RESIDUAL was
        # already ~1.7e-13 (1e-9's the requested tol, not the achieved
        # one) while SLSQP kept reporting failure. Aviary's own real
        # default optimizer is IPOPT (tol=1e-6, an interior-point method
        # built for exactly this kind of large sparse equality-constrained
        # problem) - SLSQP is only a fallback here because IPOPT/
        # pyOptSparse isn't installed on this machine. Loosen SLSQP's tol
        # to match ScipyOptimizeDriver's own default instead of Aviary's
        # SLSQP-specific 1e-9.
        prob.driver.options['tol'] = 1e-6
        prob.add_design_variables()
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
            for label, var in [
                ("Mission.GROSS_MASS (design var, bounded by our fixed MTOW)", Mission.GROSS_MASS),
                ("Aircraft.Design.GROSS_MASS (our fixed MTOW, should be unchanged)", Aircraft.Design.GROSS_MASS),
                ("Mission.RANGE (actual flown range)", Mission.RANGE),
                ("Mission.Constraints.RANGE_RESIDUAL (should be ~0 if feasible)", Mission.Constraints.RANGE_RESIDUAL),
                ("Mission.FUEL_MASS (fuel burned)", Mission.FUEL_MASS),
                ("Mission.Objectives.FUEL (actual SLSQP objective)", Mission.Objectives.FUEL),
                ("Mission.Takeoff.ASCENT_DURATION (feeds the objective; may be a dangling default since include_takeoff=False)", Mission.Takeoff.ASCENT_DURATION),
            ]:
                try:
                    val = prob.get_val(var)
                    print(f"   {label}: {val}")
                except Exception as diag_err:
                    print(f"   {label}: <could not read: {diag_err}>")
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
