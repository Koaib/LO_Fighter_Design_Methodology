# -*- coding: utf-8 -*-
"""
Created on Thu Apr 16 20:24:37 2026

@author: KK
"""

"""
Main script to generate aircraft in OpenVSP
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
vsp.SetParmVal(fuselage, "MaxWidth", "Design", 1.2)
vsp.SetParmVal(fuselage, "MaxHeight", "Design", 1.4)

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
# TRIGGER MATLAB RCS PIPELINE
# =========================

vsp_setup.run_matlab_rcs()