# -*- coding: utf-8 -*-
"""
Created on Thu Aug  6 12:10:49 2026

@author: KK
"""

import subprocess, json, os, sys
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
ROOT_DIR     = SCRIPT_DIR.parent
GEOMETRY_DIR = ROOT_DIR / "Geometry"

VSP3_FILE    = str(GEOMETRY_DIR / "SSAM_final_geom_to_be_used_scaled_by_19_simplified.vsp3")
SETS_FILE    = str(GEOMETRY_DIR / "SSAM_final_geom_to_be_used_scaled_by_19_simplified_sets.json")
SWEEP_PARAMS_FILE = str(GEOMETRY_DIR / "SSAM_final_geom_to_be_used_scaled_by_19_simplified_sweep_params.json")

with open(SWEEP_PARAMS_FILE) as f:
    SWEEP_PARAMS = json.load(f)

SWEEP_ROOT   = ROOT_DIR / "Results" / "SensitivityStudy" / "Sweeps"
MANIFEST_DIR = ROOT_DIR / "Results" / "SensitivityStudy" / "Manifest"
LOG_DIR      = ROOT_DIR / "Results" / "SensitivityStudy" / "SweepLogs"
for d in (SWEEP_ROOT, MANIFEST_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

TIMEOUT_SEC = 70 * 60

BASE = dict(
    vsp3=VSP3_FILE, sets_file=SETS_FILE, ref_wing="Main_Wing",
    manifest_dir=str(MANIFEST_DIR), sweep_dir=str(SWEEP_ROOT),
    alpha_start=-8.0, alpha_end=14.0, alpha_npts=12,
    mach=0.6, re_cref=1e6, wake_iters=6,
    run_rcs=False,
    freq_ghz=12.0, pol="both", cuts="azimuth", az_range="half", delp=1.0,
    min_edge_factor=3, max_edge_factor=1, max_gap_factor=3,
    growth_ratio=1.6, num_circle_segs=12.0,
)


def _override(param_key, delta):
    spec = SWEEP_PARAMS[param_key]
    return [spec["geom"], spec["surf"], spec["section"], spec["parm"], spec["baseline"] + delta]


def build_sweep(param_key, deltas, family_tag, extra_param_keys=None):
    configs = []
    for d in deltas:
        overrides = [_override(param_key, d)]
        for extra_key in (extra_param_keys or []):
            overrides.append(_override(extra_key, d))
        configs.append({**BASE, "tag": f"{family_tag}_{d:+.1f}", "parm_overrides": overrides})
    return configs


def run_one(cfg, retry=True):
    manifest_file = MANIFEST_DIR / f"{cfg['tag']}.json"
    if manifest_file.exists():
        with open(manifest_file) as f:
            if json.load(f).get("status") == "done":
                print(f"skip {cfg['tag']} — already done"); return True

    log_path = LOG_DIR / f"{cfg['tag']}.log"
    worker = str(SCRIPT_DIR / "sweep_worker.py")
    with open(log_path, "w", encoding="utf-8") as logf:
        try:
            import time
            time.sleep(5)
            subprocess.run([sys.executable, worker, json.dumps(cfg)],
                            stdout=logf, stderr=subprocess.STDOUT, timeout=TIMEOUT_SEC, check=True)
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT — {cfg['tag']} skipped"); return False
        except subprocess.CalledProcessError:
            print(f"FAILED — {cfg['tag']}, see {log_path}"); return False

    if not manifest_file.exists():
        print(f"RAN BUT NO MANIFEST — {cfg['tag']}"); return False
    with open(manifest_file) as f:
        status = json.load(f).get("status")
    if status == "done":
        print(f"OK {cfg['tag']}"); return True

    if status == "aero_failed" and retry:
        print(f"RETRYING (possible file-lock race) — {cfg['tag']}")
        import time; time.sleep(5)
        manifest_file.unlink(missing_ok=True)
        return run_one(cfg, retry=False)   # one retry only, no infinite loop

    print(f"RAN BUT NOT DONE ({status}) — {cfg['tag']}"); return False
    

if __name__ == "__main__":
    STAGE = "S1"

    if STAGE == "S1":
        DELTAS_WING_SWEEP = [0.0, -15, -10, -5, 5, 10, 15]
        DELTAS_VT_CANT    = [0.0, -20, -10, -5, 5, 10, 20]
        DELTAS_WING_TWIST = [0.0, -3, -2, -1, 1, 2, 3]
        RUN_RCS = False
    else:
        DELTAS_WING_SWEEP = [0.0, -12, -8, -4, 4, 8, 12]
        DELTAS_VT_CANT    = [0.0, -15, -8, 8, 15]
        DELTAS_WING_TWIST = [0.0, -2, -1, 1, 2]
        RUN_RCS = True

    def tagged(base_tag):
        return f"{base_tag}_{STAGE}"

    configs  = build_sweep("WingSweep_sec1", DELTAS_WING_SWEEP, tagged("WingSweep_aligned"),
                        extra_param_keys=["WingSweep_sec2", "HTSweep_sec1", "HTSweep_sec2"])
    configs += build_sweep("WingSweep_sec1", DELTAS_WING_SWEEP, tagged("WingSweep_misaligned"),
                        extra_param_keys=["WingSweep_sec2"])   # wing moves, HT stays put
    configs += build_sweep("VTCant",         DELTAS_VT_CANT,    tagged("VTCant"))
    # configs += build_sweep("WingTwist_sec1", DELTAS_WING_TWIST, tagged("WingTwist"))

    for c in configs:
        c["run_rcs"] = RUN_RCS

    results = {cfg["tag"]: run_one(cfg) for cfg in configs}
    print(json.dumps(results, indent=2))