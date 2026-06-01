# -*- coding: utf-8 -*-
"""
Created on Thu Apr 16 20:24:37 2026

@author: KK
"""

"""
Single entry point for the LO Fighter Design Methodology pipeline.
 
Pipeline:
  1. OpenVSP  — parametric aircraft geometry generation
  2. Export   — VSP3 + STEP + STL files
  3. OpenRCS  — Physical Optics monostatic RCS computation (pure Python,
                no MATLAB, no Octave, no license required)
  4. Results  — Polar plot, RCS vs phi plot, 3D figure, .dat data file
                all saved to Results/RCS/
 
Usage:
    python scripts/main.py
 
To change design parameters, edit the geometry section below.
To change RCS settings (frequency, angles, polarisation), edit the
RCS SETTINGS section at the bottom or pass them into run_openrcs_rcs().
"""

import vsp_setup  
import openvsp as vsp
import os


"""
Single entry point for the LO Fighter Design Methodology pipeline.

INPUT_MODE options:
  "generate"   — build geometry from scratch using OpenVSP parameters below
  "import_stl" — skip geometry, load an existing STL from Geometry/
  "import_vsp3"— load an existing .vsp3 from Geometry/, then export STL
"""

# =========================
# INPUT MODE — edit this
# =========================

INPUT_MODE    = "import_vsp3"       # "generate" | "import_stl" | "import_vsp3"
IMPORT_FILE   = "F35A_subsonic_meters_simplified_OML_v3.vsp3"  # filename inside Geometry/ folder (for import modes)

# =========================
# GEOMETRY FOLDER PATH
# =========================

ROOT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOMETRY_DIR = os.path.join(ROOT_DIR, "Geometry")
os.makedirs(GEOMETRY_DIR, exist_ok=True)

# =========================
# BRANCH ON INPUT MODE
# =========================

if INPUT_MODE == "import_stl":
    stl_file = os.path.join(GEOMETRY_DIR, IMPORT_FILE)
    if not os.path.isfile(stl_file):
        raise FileNotFoundError(f"STL not found: {stl_file}")
    # Copy into STL_Files/ where run_openrcs expects it
    import shutil
    dest = vsp_setup.stl_path(IMPORT_FILE)
    shutil.copy2(stl_file, dest)
    print(f"✅ Imported STL: {IMPORT_FILE}")
    stl_for_rcs = IMPORT_FILE

elif INPUT_MODE == "import_vsp3":
    import openvsp as vsp
    vsp3_file = os.path.join(GEOMETRY_DIR, IMPORT_FILE)
    if not os.path.isfile(vsp3_file):
        raise FileNotFoundError(f"VSP3 not found: {vsp3_file}")
    vsp.VSPCheckSetup()
    vsp.ClearVSPModel()
    vsp.ReadVSPFile(vsp3_file)
    vsp.Update()
    # Derive STL name from the vsp3 filename
    stl_name = os.path.splitext(IMPORT_FILE)[0] + ".stl"
    vsp.ExportFile(vsp_setup.stl_path(stl_name), vsp.SET_ALL, vsp.EXPORT_STL)
    print(f"✅ Loaded VSP3 and exported STL: {stl_name}")
    stl_for_rcs = stl_name

else:  # "generate"
    import openvsp as vsp
    vsp.VSPCheckSetup()
    vsp.ClearVSPModel()

    # =====================
    # FUSELAGE
    # =====================
    fuselage = vsp.AddGeom("FUSELAGE")
    vsp.SetParmVal(fuselage, "Length", "Design", 10.0)

    # =====================
    # MAIN WING
    # =====================
    wing = vsp.AddGeom("WING")
    vsp.SetParmVal(wing, "Span",       "XSec_1", 12.0)
    vsp.SetParmVal(wing, "Root_Chord", "XSec_1",  2.5)
    vsp.SetParmVal(wing, "Tip_Chord",  "XSec_1",  1.2)
    vsp.SetParmVal(wing, "Sweep",      "XSec_1", 25.0)
    vsp.SetParmVal(wing, "Dihedral",   "XSec_1",  5.0)
    vsp.SetParmVal(wing, "X_Rel_Location", "XForm", 4.0)
    vsp.SetParmVal(wing, "Z_Rel_Location", "XForm", 0.0)

    # =====================
    # HORIZONTAL TAIL
    # =====================
    htail = vsp.AddGeom("WING")
    vsp.SetParmVal(htail, "Span",       "XSec_1",  5.0)
    vsp.SetParmVal(htail, "Root_Chord", "XSec_1",  1.2)
    vsp.SetParmVal(htail, "Tip_Chord",  "XSec_1",  0.6)
    vsp.SetParmVal(htail, "Sweep",      "XSec_1", 30.0)
    vsp.SetParmVal(htail, "X_Rel_Location", "XForm", 8.5)
    vsp.SetParmVal(htail, "Z_Rel_Location", "XForm", 0.2)

    vsp.Update()

    vsp.WriteVSPFile(vsp_setup.vsp_path("aircraft.vsp3"))
    vsp.ExportFile(vsp_setup.stp_path("aircraft.stp"), vsp.SET_ALL, vsp.EXPORT_STEP)
    vsp.ExportFile(vsp_setup.stl_path("aircraft.stl"), vsp.SET_ALL, vsp.EXPORT_STL)
    print("✅ Aircraft created and saved successfully!")
    stl_for_rcs = "aircraft.stl"

# =========================
# RCS PIPELINE
# =========================

vsp_setup.run_openrcs_rcs(
    stl_filename = stl_for_rcs,
    freq         = 12.0,
    pol          = "TE-z",
    cuts         = "azimuth",
)

# # =========================
# # AERO SETTINGS
# # =========================

# ALPHA_START  = -5.0
# ALPHA_END    = 15.0
# ALPHA_NPTS   = 21       # gives 1-deg steps
# MACH         = 0.4      # cruise approximation
# RE_CREF      = 1e6      # Reynolds based on ref chord
# WAKE_ITERS   = 3

# # =========================
# # TRIGGER AERO PIPELINE
# # =========================

# vsp_setup.run_vspaero_aero(
#     wing_id     = wing,        # the wing geom ID created earlier
#     alpha_start = ALPHA_START,
#     alpha_end   = ALPHA_END,
#     alpha_npts  = ALPHA_NPTS,
#     mach        = MACH,
#     re_cref     = RE_CREF,
#     wake_iters  = WAKE_ITERS,
# )
