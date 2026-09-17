# -*- coding: utf-8 -*-
"""
Created on Sun Aug  2 15:05:52 2026

@author: KK
"""

import vsp_setup
import sys, os, json, glob

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vsp_setup
# --- Headless & Non-Circular Import Shim (User-Space) ---
import types
if "openvsp_config" not in sys.modules:
    _cfg = types.ModuleType("openvsp_config")
    _cfg.LOAD_GRAPHICS = False
    _cfg.LOAD_FACADE = False
    _cfg.LOAD_MULTI_FACADE = False
    _cfg._IGNORE_IMPORTS = True
    _cfg.FACADE_PORT = -1
    sys.modules["openvsp_config"] = _cfg

if "./OpenVSP/python/utilities" not in sys.path:
    sys.path.insert(0, "./OpenVSP/python/utilities")
try:
    import utilities
    sys.modules["utilities"] = utilities
except Exception:
    pass
# --------------------------------------------------------
from pathlib import Path
from pipeline_config import GEOMETRY_DIR, IMPORT_FILE

# IMPORT_FILE comes from pipeline_config.py — the same geometry main.py
# actually runs. Edit it there, not here, so this dump always matches
# what the pipeline is pointed at.
VSP3_FILE = Path(GEOMETRY_DIR) / IMPORT_FILE
OUT_FILE  = VSP3_FILE.parent / (VSP3_FILE.stem + "_params_dump.json")

vsp_setup.dump_geom_params(str(VSP3_FILE), str(OUT_FILE))
