# -*- coding: utf-8 -*-
"""
doe_config.py — single source of truth for the DoE variable set, ranges,
sample count, and Results/DoE/ paths. doe_generate.py and doe_run.py both
import from here instead of each keeping their own copy - same reasoning
as pipeline_config.py: two independently-hardcoded copies is how they
silently drift apart.
"""
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

DOE_ROOT = ROOT_DIR / "Results" / "DoE"
DOE_ROOT.mkdir(parents=True, exist_ok=True)
DESIGN_MATRIX_CSV = DOE_ROOT / "doe_design_matrix.csv"

N_POINTS = 150
SEED = 42   # fixed - keeps the design matrix reproducible byte-for-byte

# Each variable = a group of SWEEP_PARAMS keys moved together by the same
# delta (same primary+extra_param_keys pattern the OFAT drivers use).
# Wing sweep / HT sweep are INDEPENDENT here (unlike the OFAT
# WingSweepAligned/WingSweepMisaligned split).
DOE_VARS = {
    "VT_Cant":         {"keys": ["VT_Cant"],                          "range": (-20.0, 20.0)},
    "VT_Sweep":        {"keys": ["VT_Sweep_surf0sec1"],               "range": (-20.0, 20.0)},
    "Wing_Sweep":      {"keys": ["WingSweep_sec1", "WingSweep_sec2"], "range": (-20.0, 20.0)},
    "HT_Sweep":        {"keys": ["HTSweep_sec1", "HTSweep_sec2"],     "range": (-20.0, 20.0)},
    "Wing_ThickChord": {"keys": ["WingThickChord_sec0", "WingThickChord_sec1", "WingThickChord_sec2",
                                  "HT_ThickChord_surf0sec0", "HT_ThickChord_surf0sec1", "HT_ThickChord_surf0sec2",
                                  "VT_ThickChord_surf0sec0", "VT_ThickChord_surf0sec1"],
                        "range": (-0.02, 0.02)},
}
VAR_NAMES = list(DOE_VARS.keys())
