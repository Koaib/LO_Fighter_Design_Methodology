# -*- coding: utf-8 -*-

"""
Created on Thu Apr 16 20:24:37 2026

@author: KK
"""

"""
rcs_sweep_driver.py — RCS-only shaping-parameter sensitivity study.

For each shaping parameter, one at a time (one-at-a-time deltas from
baseline, NOT full-factorial across parameters simultaneously): applies
each delta to the baseline geometry, exports a CFD-mesh STL, runs it
through OpenRCS (azimuth + frontal-sector cuts, TE-z only), and — once
every delta for that parameter has finished — produces:
  1. mean azimuth RCS  vs. delta   (line plot)
  2. mean frontal RCS  vs. delta   (line plot)
  3. azimuth polar RCS, all deltas overlaid on one polar plot
  4. summary_<param>.csv — delta, means, and every raw output file path,
     so a later trade-off study can reuse this RCS data without
     re-running the (expensive) solver.

Mirrors sweep_driver.py/sweep_worker.py's proven subprocess-per-config +
manifest-based skip/resume pattern, stripped of every aero step — see
rcs_sweep_worker.py. Results land under Results/RCS_SensitivityStudy/,
kept separate from the existing Results/SensitivityStudy/ aero sweep.

Config choices below (pol="TE-z", cuts="azimuth+frontal", az_range="half")
were confirmed with the user; az_range="half" assumes every delta stays
left-right symmetric (both sides moved together) — a delta that breaks
symmetry (e.g. canting only one of two vertical tails) needs
az_range="full" for that specific parameter, or its azimuth mean will
only ever see one side of the aircraft.

Δ=0.0 (baseline) is run exactly ONCE, shared across every parameter —
call run_baseline() before any run_parameter() calls. Every parameter's
delta list should still list 0.0 (it's the anchor point on the plots),
but build_param_configs() skips spawning a worker for it — the shared
baseline manifest is spliced in later, at PLOT time, by the separate
rcs_compare_family.py script (not by this driver — see that file).
Applying "+0" to any parameter produces the identical untouched
geometry, so re-running the (expensive) RCS solve on it once per
parameter would be pure waste.

NOTE — plotting was deliberately pulled OUT of this file (used to live
here as _load_done_manifests/_plot_.../build_param_outputs). Two
problems with having it here: (1) it made re-plotting depend on
re-running this driver, so you couldn't just regenerate plots once
baseline finally finished without touching the run loop again; (2) the
polar-overlay plotter called run_openrcs._azimuth_to_full_circle(...),
but that function is defined NESTED inside run_openrcs_pipeline() in
run_openrcs.py, not at module level — that call would have raised
AttributeError the first time it actually ran. Both are fixed in
rcs_compare_family.py, which now owns all plotting: run it any time,
as often as you want, and it just reads whatever manifests are on disk.
"""
import subprocess, json, os, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_config import GEOMETRY_DIR, IMPORT_FILE

VSP3_FILE = str(Path(GEOMETRY_DIR) / IMPORT_FILE)
SETS_FILE = str(Path(GEOMETRY_DIR) / (Path(IMPORT_FILE).stem + "_sets.json"))
# Same "<geometry stem>_sweep_params.json" convention as the existing aero
# sweep_driver.py, but derived from pipeline_config.IMPORT_FILE instead of
# a hardcoded filename, so it always follows whatever geometry main.py is
# currently pointed at.
SWEEP_PARAMS_FILE = str(Path(GEOMETRY_DIR) / (Path(IMPORT_FILE).stem + "_sweep_params.json"))

with open(SWEEP_PARAMS_FILE) as f:
    SWEEP_PARAMS = json.load(f)

RESULTS_ROOT = ROOT_DIR / "Results" / "RCS_SensitivityStudy"
LOG_ROOT     = RESULTS_ROOT / "_logs"
LOG_ROOT.mkdir(parents=True, exist_ok=True)

TIMEOUT_SEC = None     # No wall-clock cap. Was 150 min (before that, 60 then 120)
                        # and each bump still risked killing a legitimate run
                        # mid-CFD-mesh — main.py's own CFD-mesh export on this same
                        # geometry has no timeout at all, so the mesh alone can
                        # legitimately outlast whatever number we guessed here.
                        # subprocess.run(timeout=None) never raises TimeoutExpired,
                        # so this matches main.py's own unbounded behaviour instead
                        # of guessing another arbitrary cap.
                        #
                        # Trade-off: this removes the only automatic protection
                        # against a genuinely HUNG worker (e.g. the Octave-GUI-hang
                        # failure mode noted elsewhere in this project). If a run
                        # looks stuck, check the matching file under
                        # Results/RCS_SensitivityStudy/_logs/<tag>.log — its
                        # last-modified time tells you whether OpenVSP/OpenRCS is
                        # still actively writing output or has actually frozen.
                        # If you'd rather keep an automatic safety net, set this
                        # back to a number (in seconds) generous enough for the
                        # single most expensive case (baseline, azimuth+frontal) —
                        # e.g. 4-6 hours — rather than the per-delta sweep points,
                        # which are far cheaper.

# Same CFD-mesh settings as main.py's USE_CFD_MESH block, TE-z-only /
# azimuth+frontal cuts per the confirmed sensitivity-study scope.
# frontal_delt=5.0 matches Touzopoulos 2017's own elevation resolution
# (theirs is 5 deg, ours is now the same) and cuts the frontal run's
# point count ~4.4x (31 theta rows -> 7); frontal_delp stays at 1.0
# (azimuth-direction) since narrow specular flashes are the concern
# there, same reasoning as keeping the azimuth cut itself at delp=1.0.
BASE = dict(
    vsp3=VSP3_FILE, sets_file=SETS_FILE,
    freq_ghz=12.0, pol="TE-z", cuts="azimuth+frontal",
    az_range="half", delp=1.0,
    frontal_delp=1.0, frontal_delt=5.0,
    min_edge_factor=3, max_edge_factor=1, max_gap_factor=3,
    growth_ratio=1.6, num_circle_segs=12.0,
)

# Delta=0.0 is the SAME physical geometry no matter which parameter's
# sweep it nominally belongs to — applying "+0" to VT_Cant vs. WingSweep
# vs. anything else all produce the untouched baseline aircraft. Running
# it once here and reusing the result as every parameter's Δ=0 anchor
# point avoids paying for the (expensive) RCS solve on the identical
# baseline geometry once per parameter. See run_baseline() /
# build_param_configs()'s d==0.0 skip / _load_done_manifests()'s splice.
BASELINE_ROOT = RESULTS_ROOT / "_baseline"


def build_baseline_config():
    return {
        **BASE, "tag": "baseline", "param": "baseline", "delta": 0.0,
        "parm_overrides": [],
        "results_root": str(BASELINE_ROOT),
        "manifest_dir": str(BASELINE_ROOT / "manifest"),
    }


def run_baseline():
    """
    Runs the shared Δ=0 baseline once (manifest-skip makes repeat calls free).

    Deliberately does NOT raise on failure/timeout. It used to — but that
    made every other parameter study wait on baseline succeeding first,
    even though none of them actually need baseline's RCS *result* to run
    their own (non-zero-delta) geometry variants. Baseline is only needed
    later, as the Δ=0 anchor point when rcs_compare_family.py builds plots
    — and that script already tolerates a missing baseline manifest fine
    (see its load_family()). So: best-effort here, loud warning if it
    fails, and the calling code carries on regardless.
    """
    (BASELINE_ROOT / "rcs").mkdir(parents=True, exist_ok=True)
    (BASELINE_ROOT / "stl").mkdir(parents=True, exist_ok=True)
    cfg = build_baseline_config()
    ok = run_one(cfg)
    if not ok:
        print(
            "[baseline] FAILED or still running — continuing WITHOUT it.\n"
            "  Every parameter study below will still run its own deltas.\n"
            "  Check Results/RCS_SensitivityStudy/_logs/baseline.log, then "
            "re-run run_baseline() (or just this whole script — manifest-skip "
            "makes finished deltas free) once it's fixed. Re-run "
            "rcs_compare_family.py afterwards to fill in the Δ=0 anchor point "
            "on every study's plots."
        )
    return cfg if ok else None


def _override(param_key, delta):
    spec = SWEEP_PARAMS[param_key]
    return [spec["geom"], spec["surf"], spec["section"], spec["parm"], spec["baseline"] + delta]


def build_param_configs(param_key, deltas, results_root, extra_param_keys=None, study_name=None):
    """
    param_key   : SWEEP_PARAMS lookup key for the PRIMARY override (and,
                  when study_name is omitted, also the tag/results-folder
                  name).
    study_name  : tag/results-folder name, if it needs to differ from
                  param_key — e.g. two studies that both sweep the same
                  WingSweep_sec1 parm but with different extra_param_keys
                  (aligned vs. misaligned HT) MUST pass distinct
                  study_name values, or their tags/manifests collide and
                  silently overwrite each other.
    """
    study_name = study_name or param_key
    configs = []
    for d in deltas:
        if d == 0.0:
            continue   # shared baseline covers this — see run_baseline()
        overrides = [_override(param_key, d)]
        for extra_key in (extra_param_keys or []):
            overrides.append(_override(extra_key, d))
        tag = f"{study_name}_{d:+.2f}"
        configs.append({
            **BASE, "tag": tag, "param": study_name, "delta": d,
            "parm_overrides": overrides,
            "results_root": str(results_root),
            "manifest_dir": str(results_root / "manifest"),
        })
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
    worker = str(SCRIPT_DIR / "rcs_sweep_worker.py")
    with open(log_path, "w", encoding="utf-8") as logf:
        try:
            subprocess.run([sys.executable, worker, json.dumps(cfg)],
                            stdout=logf, stderr=subprocess.STDOUT, timeout=TIMEOUT_SEC, check=True)
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT — {cfg['tag']} skipped (see {log_path})"); return False
        except subprocess.CalledProcessError:
            print(f"FAILED — {cfg['tag']}, see {log_path}"); return False

    if not manifest_file.exists():
        print(f"RAN BUT NO MANIFEST — {cfg['tag']}"); return False
    with open(manifest_file) as f:
        status = json.load(f).get("status")
    if status == "done":
        print(f"OK {cfg['tag']}"); return True

    if status == "rcs_failed" and retry:
        print(f"RETRYING (possible file-lock race) — {cfg['tag']}")
        manifest_file.unlink(missing_ok=True)
        return run_one(cfg, retry=False)   # one retry only, no infinite loop

    print(f"RAN BUT NOT DONE ({status}) — {cfg['tag']}, see {log_path}"); return False


# ── outputs note ─────────────────────────────────────────────────────────
# Plotting (mean-vs-delta lines, azimuth polar overlay, summary CSV) used
# to live in this file as _load_done_manifests/_plot_.../build_param_outputs,
# called automatically at the end of run_parameter(). It has moved to the
# standalone rcs_compare_family.py — run that separately, any time, to
# (re)build every study's plots from whatever manifests already exist on
# disk. See that file's docstring for why (git history / diff has the old
# version if you need to compare).


# ── orchestration ───────────────────────────────────────────────────────────

def run_parameter(param_key, deltas, extra_param_keys=None, study_name=None):
    """
    param_key   : SWEEP_PARAMS lookup key for the primary override.
    study_name  : results-folder/tag name, if it must differ from
                  param_key (see build_param_configs' docstring) —
                  defaults to param_key.

    Only RUNS the sweep (subprocess-per-delta, manifest-skip/resume) —
    no plotting here anymore. Call rcs_compare_family.py separately
    (once, after some/all studies below have run) to build plots.
    """
    study_name = study_name or param_key
    results_root = RESULTS_ROOT / study_name
    (results_root / "rcs").mkdir(parents=True, exist_ok=True)
    (results_root / "stl").mkdir(parents=True, exist_ok=True)

    configs = build_param_configs(param_key, deltas, results_root, extra_param_keys, study_name)
    results = {cfg["tag"]: run_one(cfg) for cfg in configs}
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    # Each param_key below must exist in SWEEP_PARAMS_FILE (same
    # geom/surf/section/parm/baseline schema the aero sweep already
    # uses) — that file lives on your machine, not in this repo, so
    # verify the keys/entries match before running.
    #
    # Every delta list is sorted ascending with 0.0 in its natural
    # position. 0.0 is deliberate in every one of them: it's the
    # shared baseline (run_baseline(), see module docstring) used as
    # every study's Δ=0 anchor point on the plots, NOT a per-parameter
    # run — build_param_configs() skips it, so listing it costs nothing
    # extra no matter how many studies reuse it.

    # All three angular sweeps (VT cant, VT sweep, wing sweep) standardized
    # to one common range: +-15 deg in 3 deg steps.
    DELTAS_VT_CANT    = [-15, -12, -9, -6, -3, 0.0, 3, 6, 9, 12, 15]  # deg
    DELTAS_VT_SWEEP   = [-15, -12, -9, -6, -3, 0.0, 3, 6, 9, 12, 15]  # deg
    DELTAS_WING_SWEEP = [-15, -12, -9, -6, -3, 0.0, 3, 6, 9, 12, 15]  # deg
    DELTAS_TC         = [-0.02, -0.01, 0.0, 0.01, 0.02]  # absolute t/c 0.02-0.06 around baseline 0.04

    run_baseline()   # once, shared, BEST-EFFORT — no longer blocks the studies
                     # below if it fails/is slow (see run_baseline() docstring).
                     # Its Δ=0 result gets picked up later by
                     # rcs_compare_family.py whenever it's actually done.

    run_parameter("VT_Cant", DELTAS_VT_CANT)

    # VT sweep (leading edge): key verified directly against the real
    # sweep_params.json — VT_Sweep_surf0sec1 (section1, baseline 22.5
    # deg) is the real LE sweep; section0 is a root stub at 0 deg, not
    # a design knob. Never given a friendly alias the way VT_Cant/
    # WingSweep_secN were, so this is the raw auto-generated key —
    # ready to run as-is, no sweep_params.json edit needed.
    run_parameter("VT_Sweep_surf0sec1", DELTAS_VT_SWEEP)

    # Wing sweep ALIGNED with HT — HT sweep moves together with the wing.
    run_parameter("WingSweep_sec1", DELTAS_WING_SWEEP,
                  extra_param_keys=["WingSweep_sec2", "HTSweep_sec1", "HTSweep_sec2"],
                  study_name="WingSweepAligned")

    # Wing sweep ONLY — HT stays put. Same param_key/deltas as above;
    # only extra_param_keys differs, so study_name keeps the two
    # studies' results/tags from colliding (see build_param_configs'
    # docstring).
    run_parameter("WingSweep_sec1", DELTAS_WING_SWEEP,
                  extra_param_keys=["WingSweep_sec2"],
                  study_name="WingSweepMisaligned")

    # Thickness-to-chord: parm verified directly against params_dump.json
    # (Main_Wing -> sections surf0_sec0/1/2 -> "ThickChord"), uniform at
    # ~0.04 across all three wing sections — moving t/c consistently
    # means moving all three together, same multi-section pattern as
    # wing sweep.
    #
    # ThickChord was also added to vsp_setup.py's dump_geom_params()
    # WING_SHAPE_PARMS whitelist, so any FUTURE fresh sweep_params.json
    # (a new geometry, or this one regenerated from scratch) will pick
    # it up as a sweep candidate automatically. That does NOT retroactively
    # touch an existing sweep_params.json — dump_geom_params() skips
    # writing the template if the file already exists (to avoid clobbering
    # your hand-curated aliases), so the three entries below still need
    # to be added by hand if not already done:
    #   "WingThickChord_sec0": {"geom":"Main_Wing","surf":0,"section":0,"parm":"ThickChord","baseline":0.04}
    #   "WingThickChord_sec1": {"geom":"Main_Wing","surf":0,"section":1,"parm":"ThickChord","baseline":0.04}
    #   "WingThickChord_sec2": {"geom":"Main_Wing","surf":0,"section":2,"parm":"ThickChord","baseline":0.04}
    run_parameter("WingThickChord_sec0", DELTAS_TC,
                  extra_param_keys=["WingThickChord_sec1", "WingThickChord_sec2"])

    print("\nAll studies dispatched. Run `python rcs_compare_family.py` "
          "(no args) to build/refresh plots for every study found under "
          f"{RESULTS_ROOT} — safe to re-run any time, including once "
          "baseline finishes later.")