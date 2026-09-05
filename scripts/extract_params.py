# -*- coding: utf-8 -*-
"""
Created on Sun Aug  2 15:05:52 2026

@author: KK
"""

import vsp_setup
from pathlib import Path
from pipeline_config import GEOMETRY_DIR, IMPORT_FILE

# IMPORT_FILE comes from pipeline_config.py — the same geometry main.py
# actually runs. Edit it there, not here, so this dump always matches
# what the pipeline is pointed at.
VSP3_FILE = Path(GEOMETRY_DIR) / IMPORT_FILE
OUT_FILE  = VSP3_FILE.parent / (VSP3_FILE.stem + "_params_dump.json")

vsp_setup.dump_geom_params(str(VSP3_FILE), str(OUT_FILE))