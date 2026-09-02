# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:09:02 2026

@author: KK
"""

"""
Aviary mission-analysis stage of the pipeline. Normally called automatically
by main.py's RUN_AVIARY step at the end of a full run (geom_stem is passed
in from main.py's own IMPORT_FILE, so there's nothing to keep in sync by
hand). Can still be run standalone for testing against DEFAULT_GEOM_STEM
below.

Requires the aero stage (main.py) to have already produced a complete
9-file Mach x Altitude aero-polar grid (Results/Aero/aero_<geom_stem>_M#_
ALT#_*.csv) for the SAME geom_stem.

To change any OTHER Aviary-related input (mass basis, engine specs,
mission profile), edit the USER CONFIG block below.

Usage (standalone):
    python scripts/aviary/run_aviary.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # for vsp_setup

import vsp_setup
import aviary.api as av
from aviary.api import Aircraft, Mission, Settings
from aviary.variable_info.enums import EquationsOfMotion, LegacyCode
from aviary.interface.reports import mission_report, timeseries_csv

from phase_info import phase_info
from external_aero_builder import ExternalAeroBuilder
from build_engine_deck import build_deck

# =============================================================================
# USER CONFIG — edit this to change any Aviary-related input
# =============================================================================

# Only used when this file is run standalone (not via main.py, which passes
# its own geom_stem in directly - see run_aviary_mission()'s signature).
DEFAULT_GEOM_STEM = "SSAM_final_geom_to_be_used_NOT_scaled_by_19_nozzle_mod"

# This test geometry's actual wing planform — NOT a scaled-down F-16C value
# (see mass basis note below for why that distinction matters). Project
# notes flag that this "nozzle_mod" geometry may not be identical to
# whatever geometry these numbers were originally measured from — re-derive
# from the real .vsp3 (scripts/aviary/print_wing_ref_params.py) before
# trusting these for anything beyond plumbing validation.
TEST_WING_AREA_FT2 = 1.174343
TEST_WING_SPAN_FT = 1.755249
TEST_WING_ASPECT_RATIO = 3.46
TEST_WING_HAS_STRUT = False
TEST_WING_HAS_FOLD = False

# ── Mass basis ───────────────────────────────────────────────────────────
# Real F-16C published reference specs, used ONLY as a wing-loading basis to
# derive a physically self-consistent placeholder mass for this small test
# geometry — NOT a claim that this geometry IS an F-16C or a uniform scale
# of one. Dividing F-16C mass by a linear scale factor against this wing's
# actual (unrelated) area previously gave a wing loading of ~1187 lbm/ft^2
# (vs. the real F-16C's ~88 lbm/ft^2) - physically impossible, requiring
# CL~9.5 for level flight, which is why the mission's climb aerodynamics
# Newton solve couldn't converge until this was fixed. Still a placeholder
# pending the real full-scale run (real x19 geometry + true F-16C mass
# values, unscaled).
F16C_EMPTY_MASS_LBM = 18238.0   # published F-16C empty mass
F16C_GROSS_MASS_LBM = 26463.0   # published F-16C max gross takeoff mass
F16C_FUEL_MASS_LBM  = 6972.0    # published F-16C internal fuel capacity
F16C_WING_AREA_FT2  = 300.0     # published F-16C reference wing area

# ── Engine specs (simplified F100-PW-229-class deck — NOT real engine test
# data, see build_engine_deck.py) ──────────────────────────────────────────
ENGINE_T_SL_DRY_LBF = 17800.0   # published F100-PW-229 dry static thrust
ENGINE_T_SL_AB_LBF  = 29100.0   # published F100-PW-229 afterburner static thrust
ENGINE_TSFC_DRY     = 0.8       # lb/(lb*hr), typical for this engine class
ENGINE_TSFC_AB      = 2.0       # lb/(lb*hr), typical for this engine class

# ── Mission profile ────────────────────────────────────────────────────────
CRUISE_MACH = 0.6
CRUISE_ALTITUDE_FT = 35000.0
DESIGN_RANGE_NMI = 400.0

# ── Aero polar grid this run's Results/Aero CSVs must cover (must match
# main.py's MACH_LIST / ALTITUDE_LIST for this GEOM_STEM) ─────────────────
EXPECTED_MACHS = {0.2, 0.4, 0.6}
EXPECTED_ALTITUDES_FT = {0.0, 15000.0, 35000.0}

# ── Fixed architecture choices — NOT freely changeable, other files assume
# these exact values (phase_info.py's 'tabular_cruise' aero method is
# GASP-specific; the mass overrides above assume FLOPS's mass buildup) ────
EQUATIONS_OF_MOTION = EquationsOfMotion.ENERGY_STATE
MASS_METHOD = LegacyCode.FLOPS
AERODYNAMICS_METHOD = LegacyCode.GASP

# =============================================================================
# Derived mass values (wing-loading-scaled — see USER CONFIG note above)
# =============================================================================

_wing_loading_lbm_per_ft2 = F16C_GROSS_MASS_LBM / F16C_WING_AREA_FT2
GROSS_MASS_LBM = _wing_loading_lbm_per_ft2 * TEST_WING_AREA_FT2
EMPTY_MASS_LBM = GROSS_MASS_LBM * (F16C_EMPTY_MASS_LBM / F16C_GROSS_MASS_LBM)
FUEL_MASS_LBM  = GROSS_MASS_LBM * (F16C_FUEL_MASS_LBM / F16C_GROSS_MASS_LBM)


def _build_aircraft_inputs():
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
    aviary_inputs.set_val(Aircraft.Wing.AREA, TEST_WING_AREA_FT2, units="ft**2")
    aviary_inputs.set_val(Aircraft.Wing.SPAN, TEST_WING_SPAN_FT, units="ft")
    aviary_inputs.set_val(Aircraft.Wing.ASPECT_RATIO, TEST_WING_ASPECT_RATIO, units="unitless")
    aviary_inputs.set_val(Aircraft.Wing.HAS_STRUT, TEST_WING_HAS_STRUT)
    aviary_inputs.set_val(Aircraft.Wing.HAS_FOLD, TEST_WING_HAS_FOLD)
    aviary_inputs.set_val(Aircraft.Design.RANGE, DESIGN_RANGE_NMI, units="NM")
    aviary_inputs.set_val(Aircraft.Design.CRUISE_MACH, CRUISE_MACH, units="unitless")
    aviary_inputs.set_val(Aircraft.Design.CRUISE_ALTITUDE, CRUISE_ALTITUDE_FT, units="ft")
    return aviary_inputs


def run_aviary_mission(geom_stem=None):
    """Run the Aviary mission analysis for geom_stem's already-produced aero
    CSVs (see module docstring). geom_stem defaults to DEFAULT_GEOM_STEM for
    standalone use; main.py always passes its own geom_stem explicitly."""
    if geom_stem is None:
        geom_stem = DEFAULT_GEOM_STEM

    os.makedirs(vsp_setup.AVIARY_FILES, exist_ok=True)
    os.makedirs(vsp_setup.AVIARY_PERF_DIR, exist_ok=True)

    print(f"   [mass] wing-loading-scaled GROSS={GROSS_MASS_LBM:.2f} lbm, "
          f"EMPTY={EMPTY_MASS_LBM:.2f} lbm, FUEL={FUEL_MASS_LBM:.2f} lbm")

    engine_deck_path = build_deck(
        out_dir=os.path.join(vsp_setup.AVIARY_FILES, "engines"),
        deck_name="f100_pw229_simplified.deck",
        t_sl_dry=ENGINE_T_SL_DRY_LBF, t_sl_ab=ENGINE_T_SL_AB_LBF,
        tsfc_dry=ENGINE_TSFC_DRY, tsfc_ab=ENGINE_TSFC_AB,
    )

    from aviary.utils.named_values import NamedValues
    from build_aero_polar import reshape_to_grid

    external_aero = ExternalAeroBuilder(
        geom_stem=geom_stem,
        expected_machs=EXPECTED_MACHS,
        expected_altitudes=EXPECTED_ALTITUDES_FT,
    )

    aero_data = NamedValues()
    aero_data.set_val("altitude", external_aero._data["altitude"], "ft")
    aero_data.set_val("mach", external_aero._data["mach"], "unitless")
    aero_data.set_val("angle_of_attack", external_aero._data["alpha"], "deg")

    for phase_name in ("climb", "cruise", "descent"):
        phase_info[phase_name]["subsystem_options"]["aerodynamics"]["aero_data"] = aero_data

    # Run with AVIARY_FILES as the working directory so Aviary/OpenMDAO's own
    # native "<script>_out/" report folder lands there instead of cluttering
    # scripts/aviary/ (same os.chdir()-and-restore pattern vsp_setup.py
    # already uses around vspaero.exe).
    original_cwd = os.getcwd()
    os.chdir(vsp_setup.AVIARY_FILES)
    try:
        prob = av.AviaryProblem()
        prob.load_inputs(_build_aircraft_inputs(), phase_info)
        prob.load_external_subsystems([external_aero])

        # Fixed mass overrides — settings:mass_method stays FLOPS, but
        # since EMPTY_MASS is set here on aviary_inputs *before*
        # build_model()/setup(), Aviary's override-variable mechanism
        # disconnects FLOPS's own empirical EmptyMass computation and treats
        # this fixed value as the input instead (see
        # aviary/subsystems/premission.py:override_aviary_vars). GROSS_MASS
        # is already a plain input in FLOPS's mass buildup (never computed),
        # so setting it here is a normal input assignment, not an override.
        prob.aviary_inputs.set_val(Aircraft.Design.EMPTY_MASS, EMPTY_MASS_LBM, units="lbm")
        prob.aviary_inputs.set_val(Aircraft.Design.GROSS_MASS, GROSS_MASS_LBM, units="lbm")
        prob.aviary_inputs.set_val(Aircraft.Fuel.TOTAL_CAPACITY, FUEL_MASS_LBM, units="lbm")

        # Mission.Constraints.MAX_MACH defaults to 0.0 (Aviary's own metadata
        # has a "TODO: derived default value" comment acknowledging this) and
        # is read by FLOPS's PassengerServiceMass component as
        # (design_range / max_mach) ** 0.225 - with max_mach=0.0 that's a
        # division by zero that cascades into NaN mass results. Set to the
        # real cruise Mach.
        prob.aviary_inputs.set_val(Mission.Constraints.MAX_MACH, CRUISE_MACH, units="unitless")

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
        engine_options.set_val(Aircraft.Engine.REFERENCE_SLS_THRUST, ENGINE_T_SL_DRY_LBF, units="lbf")
        engine_deck = av.EngineDeck(name="f100", options=engine_options)
        av.preprocess_propulsion(aviary_options=prob.aviary_inputs, engine_models=[engine_deck])

        prob.check_and_preprocess_inputs()

        lift_grid, drag_grid = reshape_to_grid(external_aero._data)
        prob.aviary_inputs.set_val(Aircraft.Design.LIFT_POLAR, lift_grid, units="unitless")
        prob.aviary_inputs.set_val(Aircraft.Design.DRAG_POLAR, drag_grid, units="unitless")

        prob.check_and_preprocess_inputs()
        prob.build_model()

        # NO driver / design variables / objective - pure fixed-input analysis
        prob.setup()
        # Dymos collocation needs a real starting guess for trajectory
        # states/controls/phase durations even outside optimization -
        # without this, phase duration and the distance/mass states stay
        # near their degenerate defaults and the mission never actually
        # flies anywhere. set_phase_initial_guesses() (called via
        # prob.set_initial_guesses()) auto-defaults mass/altitude/mach/time,
        # but NOT distance - that's why phase_info.py provides an explicit
        # 'distance' (and 'mass', for the same reason) initial_guesses entry
        # per phase.
        prob.set_initial_guesses()
        prob.run_model()

        # Aviary's own mission_report()/timeseries_csv() are normally only
        # triggered by run_driver() (see aviary/interface/reports.py) - they
        # don't actually need a driver to have run, they just read final
        # values off the converged model, so we call them directly.
        mission_report(prob)
        timeseries_csv(prob)

        fuel_residual = prob.get_val(Mission.Constraints.MASS_RESIDUAL)
        total_range = prob.get_val(Mission.RANGE)
        fuel_burned = prob.get_val(Mission.FUEL_MASS)

    finally:
        os.chdir(original_cwd)

    print("\n--- RESULTS ---")
    print(f"   Range flown        : {total_range[0]:.1f} nmi  (target {DESIGN_RANGE_NMI:.0f} nmi)")
    print(f"   Fuel burned        : {fuel_burned[0]:.2f} lbm")
    print(f"   Fuel mass residual : {fuel_residual[0]:.2f} lbm  "
          f"(positive = margin, negative = infeasible)")

    _save_curated_reports(geom_stem)


def _save_curated_reports(geom_stem):
    """
    Copies the report files that actually matter (mission summary + full
    timeseries + the two auto-generated input/override checks) from
    Aviary's native reports folder into Results/aviary_perf/, tagged with
    geometry + timestamp - matching the same "raw tool output -> curated
    Results/ copy" pattern main.py already uses for VSPAero's .polar files.
    """
    import glob
    import shutil
    import time

    candidates = glob.glob(os.path.join(vsp_setup.AVIARY_FILES, "*_out", "reports"))
    if not candidates:
        print("   ⚠️  Could not find Aviary's native reports/ folder — "
              "nothing copied to Results/aviary_perf/.")
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
        dst = os.path.join(vsp_setup.AVIARY_PERF_DIR, f"{stem}_{geom_stem}_{ts}{ext}")
        shutil.copy2(src, dst)
        print(f"   ✅ saved: {dst}")


if __name__ == "__main__":
    run_aviary_mission()
