# -*- coding: utf-8 -*-
"""
Created on Thu Apr 16 20:19:24 2026

@author: KK
"""

"""
Portable OpenVSP Setup

Portable path configuration and tool launchers for the LO Fighter Design
Methodology pipeline.
 
Responsibilities:
  • Resolves all folder paths relative to the project root (portable — works
    on any machine regardless of where the repo is cloned).
  • Adds the OpenVSP DLL directory and Python bindings to sys.path so that
    'import openvsp' works.
  • Exposes helper functions: vsp_path(), stp_path(), stl_path(), auto_name().
  • Exposes run_openrcs_rcs() — the MATLAB-free RCS launcher that replaces
    the old run_matlab_rcs() function.
"""


import os
import sys
import time
import subprocess
import glob
import shutil
import numpy as np
import matplotlib.pyplot as plt

# =============================================================================
# ROOT DIRECTORY (PORTABLE - works wherever the repo is cloned)
# =============================================================================

# This file lives at:  <root>/scripts/vsp_setup.py
# So one level up  →   <root>/

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# =========================
# PATH DEFINITIONS
# =========================

VSP_INSTALL = os.path.join(ROOT_DIR, "OpenVSP", "OpenVSP-3.49.0-win64")
VSP_FILES   = os.path.join(ROOT_DIR, "VSP_Files")
STP_FILES   = os.path.join(ROOT_DIR, "STP_Files")
STL_FILES = os.path.join(ROOT_DIR, "STL_Files")
RESULTS_DIR  = os.path.join(ROOT_DIR, "Results",  "RCS")
OPENRCS_DIR  = os.path.join(ROOT_DIR, "OpenRCS",  "open-rcs")
AERO_RESULTS_DIR = os.path.join(ROOT_DIR, "Results", "Aero")
VSPAERO_EXE = os.path.join(VSP_INSTALL, "vspaero.exe")


# Path to our bridge script (scripts/ folder, same folder as this file)
RUN_OPENRCS_SCRIPT = os.path.join(ROOT_DIR, "scripts", "run_openrcs.py")

# =========================
# SAFETY CHECKS
# =========================

if not os.path.exists(VSP_INSTALL):
    raise FileNotFoundError(
        f"\n❌ OpenVSP folder NOT found.\nExpected at:\n{VSP_INSTALL}\n"
        "\n👉 Make sure your folder structure is:\n"
        "Design_Methodology/OpenVSP/OpenVSP-3.49.0-win64"
    )
    
if not os.path.exists(OPENRCS_DIR):
    raise FileNotFoundError(
        f"\n❌ OpenRCS folder NOT found.\nExpected at:\n{OPENRCS_DIR}\n"
        "\n👉 Make sure your folder structure is:\n"
        "   LO_Fighter_Design_Methodology/OpenRCS/open-rcs\n"
        "   (clone from: https://github.com/comp-ime-eb-br/open-rcs)"
    )

if not os.path.exists(VSPAERO_EXE):
    print(f"⚠️  vspaero.exe not found at: {VSPAERO_EXE}")
    print("   VSPAero analysis will fail.")
else:
    print(f"✅ vspaero.exe found.")    


# Create output folder automatically
os.makedirs(VSP_FILES, exist_ok=True)
os.makedirs(STP_FILES,   exist_ok=True)
os.makedirs(STL_FILES,   exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(AERO_RESULTS_DIR, exist_ok=True)

# =========================
# OPENVSP INITIALIZATION
# =========================

os.add_dll_directory(VSP_INSTALL)

OPENVSP_CONFIG = os.path.join(VSP_INSTALL, "python", "openvsp_config")
OPENVSP_PYTHON = os.path.join(VSP_INSTALL, "python", "openvsp")
OPENVSP_INNER  = os.path.join(VSP_INSTALL, "python", "openvsp", "openvsp")

sys.path.insert(0, OPENVSP_INNER)
sys.path.insert(0, OPENVSP_PYTHON)
sys.path.insert(0, OPENVSP_CONFIG)
sys.path.insert(0, VSP_INSTALL)

# =============================================================================
# PATH HELPER FUNCTIONS
# =============================================================================
 
def vsp_path(filename: str) -> str:
    """Returns the full path for a file inside VSP_Files/."""
    return os.path.join(VSP_FILES, filename)
 
def stp_path(filename: str) -> str:
    """Returns the full path for a file inside STP_Files/."""
    return os.path.join(STP_FILES, filename)
 
def stl_path(filename: str) -> str:
    """Returns the full path for a file inside STL_Files/."""
    return os.path.join(STL_FILES, filename)
 
def auto_name(prefix: str = "case") -> str:
    """Returns a timestamped filename string, e.g. 'aircraft_20260513_142301.vsp3'."""
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.vsp3"


# =============================================================================
# OPENRCS RCS LAUNCHER  (replaces run_matlab_rcs())
# =============================================================================
 
def run_openrcs_rcs(
    stl_filename : str = "aircraft.stl",
    freq         : float = 12.0,
    pol          : str = "both",   # "TE-z", "TM-z", or "both"
    cuts         : str = "all",    # see options below
) -> None:
    """
    Launch the OpenRCS pipeline.

    pol options:
        "TE-z"  — phi-polarised only
        "TM-z"  — theta-polarised only
        "both"  — run both (recommended)

    cuts options:
        "azimuth"            — azimuth cut only     (θ=90°, φ=0→360°)
        "elevation"          — elevation cut only   (φ=0°,  θ=0→180°)
        "frontal"            — frontal 2-D only     (mean table only, no plots)
        "azimuth+elevation"  — azimuth + elevation
        "azimuth+frontal"    — azimuth + frontal mean
        "elevation+frontal"  — elevation + frontal mean
        "all"                — all three (default)

    Outputs depend on which cuts are selected:
        azimuth   → 1 linear plot, 2 polar maps, means for azimuth runs
        elevation → 1 linear plot, 2 polar maps, means for elevation runs
        frontal   → mean table only (no plots)
        mean table is only generated when at least one cut has been run
    """
    stl_full = os.path.join(STL_FILES, stl_filename)
    print("\n🔄 Launching OpenRCS ...")
    print(f"   STL       : {stl_full}")
    print(f"   Frequency : {freq} GHz    Pol: {pol}    Cuts: {cuts}\n")

    try:
        import run_openrcs
        result_dict = run_openrcs.run_openrcs_pipeline(
            stl_path    = stl_full,
            results_dir = RESULTS_DIR,
            freq        = freq,
            pol         = pol,
            cuts        = cuts,
        )
        if result_dict:
            print("✅ OpenRCS finished.")
            for k, v in result_dict.items():
                if v and k != "results_dir":
                    print(f"   {k:<18}: {os.path.basename(v)}")
        else:
            print("❌ OpenRCS returned no results.")

    except Exception as e:
        import traceback
        print(f"❌ OpenRCS error: {e}")
        traceback.print_exc()
        
def run_matlab_rcs():
    """
    Deprecated.  MATLAB is no longer required.
    This shim redirects any legacy call to run_openrcs_rcs() automatically.
    """
    print("⚠️  run_matlab_rcs() is deprecated.  Redirecting to run_openrcs_rcs().")
    run_openrcs_rcs()


# =============================================================================
# VSPAERO AERO LAUNCHER
# =============================================================================

def run_vspaero_aero(
    wing_id,
    alpha_start  = -5.0,
    alpha_end    = 15.0,
    alpha_npts   = 21,
    mach         = 0.4,
    re_cref      = 1e6,
    wake_iters   = 3,
):
    import openvsp as vsp
    
    # DEBUGGING
    print("   [DEBUG] function entered")          # ← add this
    print("   [DEBUG] wing_id =", wing_id)        # ← add this

    print("\n🔄 Running VSPAero VLM analysis...")
    print(f"   Alpha : {alpha_start}° → {alpha_end}°  ({alpha_npts} points)")
    print(f"   Mach  : {mach}   Re: {re_cref:.2e}\n")

    # ── 1. SET REFERENCE WING ────────────────────────────────────────────────
    
    # DEBUGGING
    print("   [DEBUG] calling SetVSPAERORefWingID...")
    vsp.SetVSPAERORefWingID(wing_id)
    print("   [DEBUG] SetVSPAERORefWingID done")
    vsp.PrintAnalysisInputs("VSPAERODegenGeom")
    vsp.PrintAnalysisInputs("DegenGeom")

    # ── 2. SAVE VSP3 ─────────────────────────────────────────────────────────
    vsp_file = os.path.join(VSP_FILES, "aircraft.vsp3")
    vsp.WriteVSPFile(vsp_file)
    vsp.ReadVSPFile(vsp_file)   
    print(f"   VSP3 saved and reloaded : {vsp_file}")
    print(f"   Internal VSP path : {vsp.GetVSPFileName()}")
    
    # Change working dir so vspaero.exe writes .polar/.history/.lod here
    original_cwd = os.getcwd()
    os.chdir(VSP_FILES)

    try:
        # ── 3. VSPAEROComputeGeometry — builds VLM mesh + .vspgeom ──────────
        # Do NOT call VSPAERODegenGeom separately — ComputeGeometry runs it
        # internally. VSPAERODegenGeom uses "Set" not "GeomSet" as its input
        # name, so the old calls were silently ignored → empty RID → early exit.
        print("   Running VSPAEROComputeGeometry...")
        vsp.SetAnalysisInputDefaults("VSPAEROComputeGeometry")
        vsp.SetIntAnalysisInput("VSPAEROComputeGeometry", "GeomSet",     [-1])
        vsp.SetIntAnalysisInput("VSPAEROComputeGeometry", "ThinGeomSet", [0])
        geom_rid = vsp.ExecAnalysis("VSPAEROComputeGeometry")
        if not geom_rid:
            print("❌ VSPAEROComputeGeometry failed — check model geometry.")
            return None
        print(f"   Geometry done. RID: {geom_rid}")

        vspgeom_file = os.path.join(VSP_FILES, "aircraft.vspgeom")
        if not os.path.exists(vspgeom_file):
            print("❌ .vspgeom not created. Cannot proceed.")
            print(f"   VSP_Files contents: {os.listdir(VSP_FILES)}")
            return None
        print("   .vspgeom exists ✅")

        # ── 4. VSPAEROSweep ──────────────────────────────────────────────────
        vsp.SetAnalysisInputDefaults("VSPAEROSweep")
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "AlphaStart", [alpha_start])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "AlphaEnd",   [alpha_end])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "AlphaNpts",  [alpha_npts])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "BetaStart",  [0.0])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "BetaEnd",    [0.0])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "BetaNpts",   [1])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "MachStart",  [mach])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "MachEnd",    [mach])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "MachNpts",   [1])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "ReCref",      [re_cref])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "WakeNumIter", [wake_iters])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "GeomSet",     [-1])
        print("   Executing VSPAEROSweep (1–3 min)...")
        rid = vsp.ExecAnalysis("VSPAEROSweep")
        if not rid:
            print("❌ VSPAEROSweep failed.")
            return None
        print(f"   Sweep finished. RID: {rid}")
        
        # ── 5. VSPAEROSweep — alpha sweep ─────────────────────────────────────
        vsp.SetAnalysisInputDefaults("VSPAEROSweep")

        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "AlphaStart", [alpha_start])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "AlphaEnd",   [alpha_end])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "AlphaNpts",  [alpha_npts])

        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "BetaStart", [0.0])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "BetaEnd",   [0.0])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "BetaNpts",  [1])

        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "MachStart", [mach])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "MachEnd",   [mach])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "MachNpts",  [1])

        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "ReCref",      [re_cref])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "WakeNumIter", [wake_iters])

        print("   Executing VSPAEROSweep (1-3 min)...")
        rid = vsp.ExecAnalysis("VSPAEROSweep")
        if not rid:
            print("❌ VSPAEROSweep failed.")
            return None
        print(f"   Sweep finished. RID: {rid}")

    finally:
        os.chdir(original_cwd)

    # ── 6. LOCATE .polar FILE ─────────────────────────────────────────────────
    polar_files = glob.glob(os.path.join(VSP_FILES, "*.polar"))
    if not polar_files:
        print("⚠️  No .polar file found in VSP_Files/")
        print(f"   Contents: {os.listdir(VSP_FILES)}")
        return None
    polar_src = max(polar_files, key=os.path.getmtime)
    print(f"   Polar file found: {polar_src}")

    # ── 7. COPY TO RESULTS FOLDER ─────────────────────────────────────────────
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    polar_dst = os.path.join(AERO_RESULTS_DIR, f"aero_{timestamp}.polar")
    shutil.copy2(polar_src, polar_dst)
    print(f"   Polar file saved : {polar_dst}")

    # ── 8. PARSE POLAR FILE ───────────────────────────────────────────────────
    import pandas as pd

    with open(polar_dst, "r") as f:
        raw_lines = f.readlines()

    # Find header: first line containing 'AoA' or 'Beta'
    header_line = None
    data_start  = 0
    for i, line in enumerate(raw_lines):
        if "AoA" in line or "Beta" in line and "Mach" in line:
            header_line = line.strip()
            data_start  = i + 1
            break

    if header_line is None:
        print("   Raw polar file (first 5 lines):")
        for l in raw_lines[:5]: print("   |", repr(l[:120]))
        raise RuntimeError(f"Header not found in: {polar_dst}")

    headers = header_line.split()
    print(f"   Polar headers ({len(headers)}): {headers[:8]}...")

    data = np.genfromtxt(polar_dst, skip_header=data_start, filling_values=np.nan)
    if data.ndim == 1:
        data = data.reshape(1, -1)

    col    = {name: i for i, name in enumerate(headers)}
    alpha  = data[:, col["AoA"]]
    CL     = data[:, col["CLtot"]]
    CDtot  = data[:, col["CDtot"]]
    CDi    = data[:, col["CDi"]]
    CDo    = data[:, col["CDo"]]
    LD     = data[:, col["L/D"]] if "L/D" in col else np.where(CDtot > 1e-9, CL/CDtot, 0.0)        

    # interpolate NaNs in L/D only
    from scipy.interpolate import interp1d
    nan_mask = np.isnan(LD)
    if nan_mask.any() and (~nan_mask).sum() >= 2:
        f_interp = interp1d(alpha[~nan_mask], LD[~nan_mask],
                            bounds_error=False, fill_value="extrapolate")
        LD[nan_mask] = f_interp(alpha[nan_mask])

    # export CSV
    import csv
    csv_path = polar_dst.replace(".polar", ".csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Alpha", "CL", "CDtot", "CDi", "CDo", "L/D"])
        for i in range(len(alpha)):
            writer.writerow([alpha[i], CL[i], CDtot[i], CDi[i], CDo[i], LD[i]])
    print(f"   ✅ CSV saved: {csv_path}")
    
    
    # ── 9. SUMMARY TABLE ──────────────────────────────────────────────────────
    print("\n   Alpha(°)    CL      CDtot     L/D")
    print("   " + "-" * 38)
    for i in range(len(alpha)):
        print(f"   {alpha[i]:6.1f}   {CL[i]:6.4f}   {CDtot[i]:6.4f}   {LD[i]:6.2f}")

    # ── 10. CL-ALPHA PLOT ─────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(alpha, CL, 'b-o', markersize=4, linewidth=1.5)
    ax.set_xlabel("Angle of Attack α (deg)", fontsize=12)
    ax.set_ylabel("Lift Coefficient CL", fontsize=12)
    ax.set_title("CL vs Alpha — VSPAero VLM", fontsize=13)
    ax.grid(True, linestyle='--', alpha=0.6)
    ax.axhline(0, color='k', linewidth=0.8)
    ax.axvline(0, color='k', linewidth=0.8)
    fig.tight_layout()
    cl_path = os.path.join(AERO_RESULTS_DIR, f"cl_alpha_{timestamp}.png")
    fig.savefig(cl_path, dpi=150)
    plt.close(fig)
    print(f"\n   ✅ CL-alpha plot : {cl_path}")

    # ── 11. DRAG POLAR PLOT ───────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(CDtot, CL, 'r-o', markersize=4, linewidth=1.5, label='CDtot')
    ax.plot(CDi,   CL, 'b--', markersize=3, linewidth=1.0, label='CDi (induced)')
    ax.plot(CDo,   CL, 'g--', markersize=3, linewidth=1.0, label='CDo (parasite)')
    ax.set_xlabel("Drag Coefficient CD", fontsize=12)
    ax.set_ylabel("Lift Coefficient CL", fontsize=12)
    ax.set_title("Drag Polar — VSPAero VLM", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, linestyle='--', alpha=0.6)
    fig.tight_layout()
    polar_path = os.path.join(AERO_RESULTS_DIR, f"drag_polar_{timestamp}.png")
    fig.savefig(polar_path, dpi=150)
    plt.close(fig)
    print(f"   ✅ Drag polar    : {polar_path}")

    print("\n✅ VSPAero analysis complete.\n")
    return polar_dst