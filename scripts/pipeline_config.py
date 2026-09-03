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

# Switched to the real full-scale SSAM-Gen5 geometry (19 m vehicle length,
# per Giannelis, Bykerk & Vio, Aerospace 2023, 10, 746) — "scaled_by_19"
# means the real 19 m vehicle, not "scaled by a factor of 19". The
# wind-tunnel-scale geometry (0.75 m, ~1:25 scale) is the
# "NOT_scaled_by_19" file used for the earlier placeholder-scale runs.
IMPORT_FILE   = "SSAM_final_geom_to_be_used_scaled_by_19_simplified.vsp3"  # filename inside Geometry/
REF_WING_NAME = "Main_Wing"   # only matters where REF_MODE = "auto" (SSAM run)
