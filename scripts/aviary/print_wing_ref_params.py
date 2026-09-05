# -*- coding: utf-8 -*-
"""
One-off sanity check: prints the real wing reference parms (area/span/AR)
straight off the .vsp3 geometry, so main.py's TEST_WING_AREA_FT2/
TEST_WING_SPAN_FT/TEST_WING_ASPECT_RATIO (AVIARY / MISSION CONFIG section)
can be checked against the actual CAD model instead of trusted blind.

Geometry file comes from pipeline_config.py — the same one main.py runs —
so this always checks the geometry the pipeline is actually pointed at.

Usage (Spyder): just run this file.
"""

import os
import sys
import openvsp as vsp

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pipeline_config import GEOMETRY_DIR, IMPORT_FILE, REF_WING_NAME

vsp3_path = os.path.join(GEOMETRY_DIR, IMPORT_FILE)

vsp.VSPCheckSetup()
vsp.ClearVSPModel()
vsp.ReadVSPFile(vsp3_path)
vsp.Update()

matches = [gid for gid in vsp.FindGeoms() if vsp.GetGeomName(gid) == REF_WING_NAME]
if not matches:
    raise ValueError(f"'{REF_WING_NAME}' not found in {IMPORT_FILE}")
wing_id = matches[0]

print(f"\nAll area/span/chord/AR-like parms on '{REF_WING_NAME}':\n")
for pid in vsp.GetGeomParmIDs(wing_id):
    name = vsp.GetParmName(pid)
    if any(key in name.lower() for key in ("area", "span", "chord", "ar")):
        print(f"   {name:30s} = {vsp.GetParmVal(pid)}")

print("\nLook for TotalArea / TotalSpan / TotalAR (or TotalChord) above — those")
print("are the computed planform values VSPAero itself uses in 'auto' ref mode.")
print("Compare against TEST_WING_AREA_FT2/TEST_WING_SPAN_FT/TEST_WING_ASPECT_RATIO")
print("in main.py's AVIARY / MISSION CONFIG section and update those if they differ.")
