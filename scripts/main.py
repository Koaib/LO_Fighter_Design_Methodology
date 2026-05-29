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

# =========================
# INITIALIZE
# =========================

vsp.VSPCheckSetup()
vsp.ClearVSPModel()

# =========================
# FUSELAGE
# =========================

fuselage = vsp.AddGeom("FUSELAGE")
vsp.SetParmVal(fuselage, "Length", "Design", 10.0)

# =========================
# MAIN WING
# =========================

wing = vsp.AddGeom("WING")
vsp.SetParmVal(wing, "Span", "XSec_1", 12.0)
vsp.SetParmVal(wing, "Root_Chord", "XSec_1", 2.5)
vsp.SetParmVal(wing, "Tip_Chord", "XSec_1", 1.2)
vsp.SetParmVal(wing, "Sweep", "XSec_1", 25.0)
vsp.SetParmVal(wing, "Dihedral", "XSec_1", 5.0)

# Position wing
vsp.SetParmVal(wing, "X_Rel_Location", "XForm", 4.0)
vsp.SetParmVal(wing, "Z_Rel_Location", "XForm", 0.0)

# =========================
# HORIZONTAL TAIL
# =========================

htail = vsp.AddGeom("WING")
vsp.SetParmVal(htail, "Span", "XSec_1", 5.0)
vsp.SetParmVal(htail, "Root_Chord", "XSec_1", 1.2)
vsp.SetParmVal(htail, "Tip_Chord", "XSec_1", 0.6)
vsp.SetParmVal(htail, "Sweep", "XSec_1", 30.0)

# Position tail
vsp.SetParmVal(htail, "X_Rel_Location", "XForm", 8.5)
vsp.SetParmVal(htail, "Z_Rel_Location", "XForm", 0.2)

# =========================
# UPDATE MODEL
# =========================

vsp.Update()

# =========================
# SAVE FILE (VSP,STP,STL)
# =========================

# Option 1: Manual name
vsp.WriteVSPFile(vsp_setup.vsp_path("aircraft.vsp3"))
vsp.ExportFile(vsp_setup.stp_path("aircraft.stp"), vsp.SET_ALL, vsp.EXPORT_STEP)
vsp.ExportFile(vsp_setup.stl_path("aircraft.stl"), vsp.SET_ALL, vsp.EXPORT_STL)


# Option 2: Auto timestamped name
# vsp.WriteVSPFile(vsp_setup.vsp_path(vsp_setup.auto_name("aircraft")))

print("✅ Aircraft created and saved successfully!")


# =========================
# TRIGGER RCS PIPELINE
# =========================

# RCS SETTINGS — edit these to change the simulation without touching any
# other file.  These are the same defaults used in the old run_rcs.m script.
#
#   freq   : radar frequency in GHz
#   pol    : 'TE-z'  = phi-polarised   (matches old 'Phi' setting in POFACETS)
#            'TM-z'  = theta-polarised
#   pstart / pstop / delp  : phi sweep in degrees
#   tstart / tstop / delt  : theta sweep in degrees
#                            tstart == tstop → azimuth (phi) cut at fixed theta
# =============================================================================
 
vsp_setup.run_openrcs_rcs(
    stl_filename = "aircraft.stl",   # must match the STL exported above
    freq         = 12.0,             # GHz
    pol          = "TE-z",           # phi-polarised
    pstart       = 0.0,              # phi start  (deg)
    pstop        = 360.0,            # phi stop   (deg)
    delp         = 1.0,              # phi step   (deg)
    tstart       = 90.0,             # theta fixed at 90° (azimuth cut)
    tstop        = 90.0,
    delt         = 1.0,
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
