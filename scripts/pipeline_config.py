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

# Switched to the larger-scale SSAM-Gen5 geometry. "scaled_by_19" is
# confirmed (via both .vsp3 dumps: span ratio 19.000000, area ratio
# 361=19^2, identical aspect ratio to 12 decimal places) to be this
# project's own "NOT_scaled_by_19" geometry scaled up by an exact factor
# of 19 — it is NOT directly tied to the SSAM-Gen5 source paper's
# separately-stated "19 m full-scale vehicle" length (Giannelis, Bykerk &
# Vio, Aerospace 2023, 10, 746); that's a different number, and this
# project's "NOT_scaled_by_19" base geometry is itself a locally modified
# ("nozzle_mod") variant, not dimensionally identical to the paper's
# published wind-tunnel model. The "NOT_scaled_by_19" file is the smaller
# geometry used for the earlier placeholder-scale runs.
IMPORT_FILE   = "SSAM_final_geom_to_be_used_scaled_by_19_simplified.vsp3"  # filename inside Geometry/
REF_WING_NAME = "Main_Wing"   # only matters where REF_MODE = "auto" (SSAM run)
