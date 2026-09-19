# -*- coding: utf-8 -*-
"""
doe_run.py — dispatches DoE configs (rows of doe_design_matrix.csv,
produced by doe_generate.py - run that first) through the existing
aero_stab_mission_driver.py / rcs_sweep_driver.py run_one() functions,
unchanged.

Usage (direct):
    python doe_run.py           # all rows in the design matrix
    python doe_run.py 0 40      # rows 0-39 only (Python slice: start
                                 # inclusive, end exclusive)

Usage (as a library, for per-machine launcher stubs - see make_batches.py):
    import doe_run
    doe_run.run_range(0, 10)
"""
import sys, json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import aero_stab_mission_driver as aero_drv
import rcs_sweep_driver as rcs_drv
import doe_config as cfg

DOE_LOG_ROOT = cfg.DOE_ROOT / "_logs"
DOE_LOG_ROOT.mkdir(parents=True, exist_ok=True)
aero_drv.LOG_ROOT = DOE_LOG_ROOT
rcs_drv.LOG_ROOT = DOE_LOG_ROOT

AERO_RESULTS_ROOT = cfg.DOE_ROOT / "aero_stab_mission"
AERO_MANIFEST_DIR = str(AERO_RESULTS_ROOT / "manifest")
RCS_RESULTS_ROOT = cfg.DOE_ROOT / "rcs"


def load_design():
    import csv
    if not cfg.DESIGN_MATRIX_CSV.exists():
        raise FileNotFoundError(f"{cfg.DESIGN_MATRIX_CSV} not found - run doe_generate.py first.")
    with open(cfg.DESIGN_MATRIX_CSV) as f:
        rows = list(csv.reader(f))[1:]
    return [(row[0], [float(x) for x in row[1:]]) for row in rows]


def _build_overrides(deltas):
    overrides = []
    for var_name, delta in zip(cfg.VAR_NAMES, deltas):
        for key in cfg.DOE_VARS[var_name]["keys"]:
            overrides.append(aero_drv._override(key, delta))
    return overrides


def run_point(tag, deltas, doe_index):
    overrides = _build_overrides(deltas)

    cfg_aero = {**aero_drv.BASE, "tag": tag, "study": "DoE", "delta": doe_index,
                "parm_overrides": overrides, "manifest_dir": AERO_MANIFEST_DIR}
    ok_aero = aero_drv.run_one(cfg_aero)

    cfg_rcs = {**rcs_drv.BASE, "tag": tag, "param": "DoE", "delta": doe_index,
               "parm_overrides": overrides,
               "results_root": str(RCS_RESULTS_ROOT), "manifest_dir": str(RCS_RESULTS_ROOT / "manifest")}
    ok_rcs = rcs_drv.run_one(cfg_rcs)

    return ok_aero, ok_rcs


def run_range(start=0, end=None):
    (RCS_RESULTS_ROOT / "rcs").mkdir(parents=True, exist_ok=True)
    (RCS_RESULTS_ROOT / "stl").mkdir(parents=True, exist_ok=True)
    Path(AERO_MANIFEST_DIR).mkdir(parents=True, exist_ok=True)

    design = load_design()
    end = len(design) if end is None else end

    aero_drv.run_baseline()
    rcs_drv.run_baseline()

    results = {}
    for i, (tag, deltas) in enumerate(design[start:end], start=start):
        print(f"\n=== {tag} ({i+1}/{len(design)}) — {dict(zip(cfg.VAR_NAMES, deltas))} ===")
        results[tag] = run_point(tag, deltas, i)

    print(json.dumps(results, indent=2))
    print(f"\nDone with {start}-{end-1}. Re-run any range any time - already-finished tags are skipped for free.")
    return results


if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end   = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run_range(start, end)
