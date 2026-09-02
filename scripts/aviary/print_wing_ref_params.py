# -*- coding: utf-8 -*-
"""
One-off: prints the real wing reference parms (area/span/AR) for a given
geometry file, so ssam_aircraft.csv's placeholder values can be replaced
with numbers verified against the actual geometry instead of copied over
from a different (possibly non-identically-scaled) dump.

Usage (Spyder): edit VSP3_NAME below if needed, then run this file.
"""

import os
import openvsp as vsp

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GEOMETRY_DIR = os.path.join(SCRIPT_DIR, "..", "..", "Geometry")
VSP3_NAME = "SSAM_final_geom_to_be_used_NOT_scaled_by_19_nozzle_mod.vsp3"
REF_WING_NAME = "Main_Wing"

vsp3_path = os.path.join(GEOMETRY_DIR, VSP3_NAME)

vsp.VSPCheckSetup()
vsp.ClearVSPModel()
vsp.ReadVSPFile(vsp3_path)
vsp.Update()

matches = [gid for gid in vsp.FindGeoms() if vsp.GetGeomName(gid) == REF_WING_NAME]
if not matches:
    raise ValueError(f"'{REF_WING_NAME}' not found in {VSP3_NAME}")
wing_id = matches[0]

print(f"\nAll area/span/chord/AR-like parms on '{REF_WING_NAME}':\n")
for pid in vsp.GetGeomParmIDs(wing_id):
    name = vsp.GetParmName(pid)
    if any(key in name.lower() for key in ("area", "span", "chord", "ar")):
        print(f"   {name:30s} = {vsp.GetParmVal(pid)}")

print("\nLook for TotalArea / TotalSpan / TotalAR (or TotalChord) above — those")
print("are the computed planform values VSPAero itself uses in 'auto' ref mode.")
print("Paste this output back so ssam_aircraft.csv can be corrected.")
