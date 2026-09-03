# -*- coding: utf-8 -*-
"""
Single source of truth for the geometry file every pipeline stage and
utility script points at.

main.py (the pipeline itself), extract_params.py (parameter-dump /
classification-template generator), and print_wing_ref_params.py
(real-geometry sanity check for main.py's wing constants) all import
IMPORT_FILE/GEOMETRY_DIR/REF_WING_NAME from here instead of each
hardcoding their own copy — which is what previously let
extract_params.py silently point at a different geometry file than
main.py was actually running.

Edit IMPORT_FILE here — not in main.py, not in extract_params.py, not in
print_wing_ref_params.py — and every script picks it up.
"""

import os

ROOT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOMETRY_DIR = os.path.join(ROOT_DIR, "Geometry")

IMPORT_FILE   = "SSAM_final_geom_to_be_used_NOT_scaled_by_19_nozzle_mod.vsp3"  # filename inside Geometry/
REF_WING_NAME = "Main_Wing"   # only matters where REF_MODE = "auto" (SSAM run)
