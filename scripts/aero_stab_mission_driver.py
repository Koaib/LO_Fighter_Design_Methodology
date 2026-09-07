# -*- coding: utf-8 -*-
"""
aero_stab_mission_driver.py — combined aero + stability + mission-
feasibility shaping-parameter sensitivity study.

Sweeps the SAME 5 studies, same parameter keys, same deltas, and same
tag convention as rcs_sweep_driver.py (VT_Cant, VT_Sweep_surf0sec1,
WingSweepAligned, WingSweepMisaligned, WingThickChord) so this study's
results can be joined with the RCS study's results by identical
(study, delta) tags in a later trade-off study - see that file for the
authoritative parameter/delta definitions this one is meant to match.

Unlike sweep_driver.py/sweep_worker.py's own aero-only screening (Stage
1: one flight condition, Mach 0.6/sea level, per config), this study
runs the FULL Mach x Altitude aero grid per config - same as main.py's
normal single-geometry run - so each swept configuration gets a real
Raymer (Ch 19) mission-feasibility number, not a single-point proxy.
That is a deliberate cost trade-off (roughly 9x the VSPAero calls per
config vs. the Stage-1 screening sweep) accepted because the deliverable
needs real per-config mission numbers, not an approximation.

Mirrors rcs_sweep_driver.py's own proven subprocess-per-config +
manifest-based skip/resume pattern exactly (see that file for the
detailed rationale) - one JSON config per delta, spawned as
aero_stab_mission_worker.py, one manifest JSON per config recording
status + every metric a later compare/trade-off script needs. No
baseline special-casing here the way the RCS driver has one: unlike an
RCS solve, a full aero+mission run at delta=0.0 is not pure waste to
repeat once per study (it's the SAME per-config cost as any other
delta, and gives every study's plot its own explicit Delta=0 anchor
point without a separate splice-in step) - so, unlike
rcs_sweep_driver.py, every non-empty delta list here is run AS-IS,
0.0 included.
"""
import subprocess, json, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_config import GEOMETRY_DIR, IMPORT_FILE, REF_WING_NAME

VSP3_FILE = str(Path(GEOMETRY_DIR) / IMPORT_FILE)
SETS_FILE = str(Path(GEOMETRY_DIR) / (Path(IMPORT_FILE).stem + "_sets.json"))
# Same sidecar file rcs_sweep_driver.py/sweep_driver.py already read -
# lives on your machine only (gitignored), built by
# vsp_setup.dump_geom_params(), hand-curated.
SWEEP_PARAMS_FILE = str(Path(GEOMETRY_DIR) / (Path(IMPORT_FILE).stem + "_sweep_params.json"))

with open(SWEEP_PARAMS_FILE) as f:
    SWEEP_PARAMS = json.load(f)

RESULTS_ROOT = ROOT_DIR / "Results" / "AeroStabMissionStudy"
LOG_ROOT     = RESULTS_ROOT / "_logs"
LOG_ROOT.mkdir(parents=True, exist_ok=True)

TIMEOUT_SEC = None   # Same reasoning as rcs_sweep_driver.py's own TIMEOUT_SEC=None:
                     # a full 9-point aero grid can legitimately run long, and a
                     # wrong guess here risks killing a real, still-progressing
                     # run. Check Results/AeroStabMissionStudy/_logs/<tag>.log's
                     # last-modified time if a run looks stuck.

# ── Fixed inputs, held IDENTICAL across every swept configuration ──────────
# These mirror main.py's own ENGINE & MISSION CONFIG / AERO SETTINGS /
# STABILITY SETTINGS values as of this study's creation - main.py isn't
# imported directly (it executes its whole OpenVSP pipeline on import,
# not just definitions), so these are a deliberate, explicit duplicate.
# Re-check against main.py's current values before trusting this file's
# results if either has changed since.
#
# GROSS_MASS_LBM/FUEL_CAPACITY_LBM in particular are the SAME frozen,
# MASS_BASIS_REFERENCE_WING_AREA_FT2-derived values main.py uses - held
# constant across every shape variant on purpose (see main.py's own
# comment on that constant): this study is asking "how does shaping
# affect performance for the SAME aircraft weight/fuel", not letting a
# shape-driven planform-area change silently also change the assumed
# aircraft weight.
ALPHA_START, ALPHA_END, ALPHA_NPTS = -10.0, 22.0, 17
MACH_LIST     = [0.2, 0.4, 0.6]
ALTITUDE_LIST = [0.0, 15000.0, 35000.0]
RE_CREF       = 1e6
WAKE_ITERS    = 8

X_CG, Y_CG, Z_CG = 10.33, 0.0, 0.0

F22_GROSS_MASS_LBM, F22_FUEL_MASS_LBM, F22_WING_AREA_FT2 = 83500.0, 18000.0, 840.0
MASS_BASIS_REFERENCE_WING_AREA_FT2 = 843.018026816014
GROSS_MASS_LBM    = (F22_GROSS_MASS_LBM / F22_WING_AREA_FT2) * MASS_BASIS_REFERENCE_WING_AREA_FT2
FUEL_CAPACITY_LBM = (F22_FUEL_MASS_LBM / F22_WING_AREA_FT2) * MASS_BASIS_REFERENCE_WING_AREA_FT2

ENGINE_T_SL_DRY_LBF, ENGINE_T_SL_AB_LBF = 17800.0, 29100.0
ENGINE_THROTTLE_RATIO = 1.07
ENGINE_TYPE = "low_bypass_mixed_flow_turbofan"
NUM_ENGINES = 2
CUSTOM_ENGINE_DECK_PATH = None

CRUISE_MACH, CRUISE_ALTITUDE_FT, DESIGN_RANGE_NMI = 0.6, 35000.0, 400.0

BASE = dict(
    vsp3=VSP3_FILE, sets_file=SETS_FILE, ref_wing=REF_WING_NAME,
    alpha_start=ALPHA_START, alpha_end=ALPHA_END, alpha_npts=ALPHA_NPTS,
    mach_list=MACH_LIST, altitude_list=ALTITUDE_LIST,
    re_cref=RE_CREF, wake_iters=WAKE_ITERS,
    x_cg=X_CG, y_cg=Y_CG, z_cg=Z_CG,
    gross_mass_lbm=GROSS_MASS_LBM, fuel_capacity_lbm=FUEL_CAPACITY_LBM,
    engine_t_sl_dry_lbf=ENGINE_T_SL_DRY_LBF, engine_t_sl_ab_lbf=ENGINE_T_SL_AB_LBF,
    engine_throttle_ratio=ENGINE_THROTTLE_RATIO, engine_type=ENGINE_TYPE,
    num_engines=NUM_ENGINES, custom_engine_deck_path=CUSTOM_ENGINE_DECK_PATH,
    cruise_mach=CRUISE_MACH, cruise_altitude_ft=CRUISE_ALTITUDE_FT,
    design_range_nmi=DESIGN_RANGE_NMI,
    manifest_dir=str(RESULTS_ROOT / "manifest"),
)


def _override(param_key, delta):
    spec = SWEEP_PARAMS[param_key]
    return [spec["geom"], spec["surf"], spec["section"], spec["parm"], spec["baseline"] + delta]


def build_study_configs(param_key, deltas, study_name, extra_param_keys=None):
    configs = []
    for d in deltas:
        overrides = [_override(param_key, d)]
        for extra_key in (extra_param_keys or []):
            overrides.append(_override(extra_key, d))
        # .2f tag precision matches rcs_sweep_driver.py's own tags exactly
        # (and this study's own aero-only counterpart, sweep_driver.py,
        # after its recent fix) - a later trade-off script joins rows by
        # this exact string.
        tag = f"{study_name}_{d:+.2f}"
        configs.append({**BASE, "tag": tag, "study": study_name, "delta": d,
                         "parm_overrides": overrides})
    return configs


def run_one(cfg, retry=True):
    manifest_dir = Path(cfg["manifest_dir"])
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_dir / f"{cfg['tag']}.json"
    if manifest_file.exists():
        with open(manifest_file) as f:
            if json.load(f).get("status") == "done":
                print(f"skip {cfg['tag']} — already done"); return True

    log_path = LOG_ROOT / f"{cfg['tag']}.log"
    worker = str(SCRIPT_DIR / "aero_stab_mission_worker.py")
    crashed = False
    with open(log_path, "w", encoding="utf-8") as logf:
        try:
            subprocess.run([sys.executable, worker, json.dumps(cfg)],
                            stdout=logf, stderr=subprocess.STDOUT, timeout=TIMEOUT_SEC, check=True)
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT — {cfg['tag']} skipped (see {log_path})"); return False
        except subprocess.CalledProcessError:
            # Same reasoning as rcs_sweep_driver.py's own run_one(): fall
            # through to the manifest-based retry below instead of
            # bailing out here, so a real worker exception still gets one
            # automatic retry.
            crashed = True

    if not manifest_file.exists():
        print(f"RAN BUT NO MANIFEST — {cfg['tag']}"); return False
    with open(manifest_file) as f:
        status = json.load(f).get("status")
    if status == "done":
        print(f"OK {cfg['tag']}"); return True

    if status in ("aero_failed", "aero_diverged", "error") and retry:
        print(f"RETRYING ({status}) — {cfg['tag']}")
        # Deliberately NOT unlinking the manifest here (unlike
        # rcs_sweep_driver.py's own retry, whose worker checkpoints via
        # per-stage output files on disk and so doesn't need the manifest
        # to survive). aero_stab_mission_worker.py's checkpointing keys
        # off THIS manifest's own "aero_points" list - deleting it before
        # the retry would throw away every already-completed aero point
        # (up to 9 VSPAero calls) and force a full redo. Leaving it in
        # place lets the retried worker resume from whichever point it
        # crashed/diverged on.
        return run_one(cfg, retry=False)   # one retry only, no infinite loop

    if crashed:
        print(f"FAILED — {cfg['tag']}, see {log_path}"); return False
    print(f"RAN BUT NOT DONE ({status}) — {cfg['tag']}, see {log_path}"); return False


def run_study(param_key, deltas, extra_param_keys=None, study_name=None):
    study_name = study_name or param_key
    configs = build_study_configs(param_key, deltas, study_name, extra_param_keys)
    results = {cfg["tag"]: run_one(cfg) for cfg in configs}
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    # Identical parameter keys/deltas/study split to rcs_sweep_driver.py's
    # own __main__ - see that file if these ever need to change, and
    # change both together so the two studies stay comparable.
    DELTAS_ANGLE = [-15, -12, -9, -6, -3, 0.0, 3, 6, 9, 12, 15]  # deg
    DELTAS_TC    = [-0.02, -0.01, 0.0, 0.01, 0.02]  # absolute t/c, 0.02-0.06 around baseline 0.04

    run_study("VT_Cant", DELTAS_ANGLE)
    run_study("VT_Sweep_surf0sec1", DELTAS_ANGLE)
    run_study("WingSweep_sec1", DELTAS_ANGLE,
              extra_param_keys=["WingSweep_sec2", "HTSweep_sec1", "HTSweep_sec2"],
              study_name="WingSweepAligned")
    run_study("WingSweep_sec1", DELTAS_ANGLE,
              extra_param_keys=["WingSweep_sec2"],
              study_name="WingSweepMisaligned")
    run_study("WingThickChord_sec0", DELTAS_TC,
              extra_param_keys=["WingThickChord_sec1", "WingThickChord_sec2",
                                "HT_ThickChord_surf0sec0", "HT_ThickChord_surf0sec1", "HT_ThickChord_surf0sec2",
                                "VT_ThickChord_surf0sec0", "VT_ThickChord_surf0sec1"],
              study_name="WingThickChord")

    print(f"\nAll studies dispatched. Run `python aero_stab_mission_compare_family.py` "
          f"to build a combined summary CSV + plots for every study found under "
          f"{RESULTS_ROOT} - safe to re-run any time.")
