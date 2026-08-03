# -*- coding: utf-8 -*-
"""
Created on Sun Aug  2 15:05:52 2026

@author: KK
"""

import vsp_setup
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VSP3_FILE  = SCRIPT_DIR.parent / "Geometry" / "test_case.vsp3"
OUT_FILE   = VSP3_FILE.parent / (VSP3_FILE.stem + "_params_dump.json")

vsp_setup.dump_geom_params(str(VSP3_FILE), str(OUT_FILE))