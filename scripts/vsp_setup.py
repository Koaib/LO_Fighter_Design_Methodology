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

def export_stl_cfdmesh(
    out_stl_path    : str,
    freq_ghz        : float,
    min_edge_factor : float = 6.0,    # fine bound:   edge = lambda / min_edge_factor
    max_edge_factor : float = 6.0,    # coarse bound: edge = lambda / max_edge_factor
    max_gap_factor  : float = 5.0,    # max_gap = lambda / max_gap_factor
    growth_ratio    : float = 1.3,    # OpenVSP default -- was 10.0 (effectively "off")
    num_circle_segs : float = 16.0,   # OpenVSP default -- was 0.00001 (effectively "off")
) -> str:
    """
    Export SET_ALL geometry to STL via OpenVSP's CFDMesh engine, with
    independent, wavelength-scaled control over min/max edge length and
    max gap, and real curvature-grading settings (growth_ratio, num_circle_segs)
    instead of the "off" values used for uniform-mesh validation shapes.

    growth_ratio/num_circle_segs defaults match OpenVSP's own GUI defaults
    (Growth Ratio=1.3, Num Circle Segments=16) rather than arbitrary picks.

    Setting min_edge_factor == max_edge_factor still reproduces uniform mesh
    if that's what a given run needs (e.g. matching the validation shapes).
    """
    import openvsp as vsp

    c   = 3e8
    wl  = c / (freq_ghz * 1e9)
    max_edge = wl / max_edge_factor
    min_edge = wl / min_edge_factor
    max_gap  = wl / max_gap_factor

    if min_edge > max_edge:
        print(f"⚠️  min_edge > max_edge — swapping so min <= max.")
        min_edge, max_edge = max_edge, min_edge

    vsp.SetCFDMeshVal(vsp.CFD_MAX_EDGE_LEN, max_edge)
    vsp.SetCFDMeshVal(vsp.CFD_MIN_EDGE_LEN, min_edge)
    vsp.SetCFDMeshVal(vsp.CFD_GROWTH_RATIO, growth_ratio)
    vsp.SetCFDMeshVal(vsp.CFD_MAX_GAP,      max_gap)
    vsp.SetCFDMeshVal(vsp.CFD_NUM_CIRCLE_SEGS, num_circle_segs)
    vsp.DeleteAllCFDSources()

    vsp.SetComputationFileName(vsp.CFD_STL_TYPE, out_stl_path)
    vsp.ComputeCFDMesh(vsp.SET_ALL, vsp.SET_NONE, vsp.CFD_STL_TYPE)

    print(f"✅ CFD-mesh STL exported: {out_stl_path}")
    print(f"   min_edge={min_edge*1000:.2f}mm (lambda/{min_edge_factor}), "
          f"max_edge={max_edge*1000:.2f}mm (lambda/{max_edge_factor}), "
          f"max_gap={max_gap*1000:.2f}mm (lambda/{max_gap_factor}), "
          f"growth_ratio={growth_ratio}, num_circle_segs={num_circle_segs}")
    return out_stl_path

# =============================================================================
# OPENRCS RCS LAUNCHER  (replaces run_matlab_rcs())
# =============================================================================
 
def run_openrcs_rcs(
    stl_filename : str = "aircraft.stl",
    freq         : float = 12.0,
    pol          : str = "both",
    cuts         : str = "all",
    az_range     : str = "full",   # "full" or "half" — pass through to solver
    delp         : float = 1.0,
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
            az_range    = az_range,
            delp        = delp,
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
        
def dump_geom_params(vsp3_path: str, out_json_path: str) -> dict:
    import openvsp as vsp
    import json

    vsp.VSPCheckSetup(); vsp.ClearVSPModel()
    vsp.ReadVSPFile(vsp3_path); vsp.Update()

    dump = {}
    sweep_candidates = {}   # collects every section parm for the template

    for gid in vsp.FindGeoms():
        gname = vsp.GetGeomName(gid)
        gtype = vsp.GetGeomTypeName(gid) if hasattr(vsp, "GetGeomTypeName") else "?"
        entry = {"id": gid, "type": gtype, "parms": {}, "sections": {}}

        entry["parms"] = {vsp.GetParmName(pid): vsp.GetParmVal(pid)
                           for pid in vsp.GetGeomParmIDs(gid)}

        WING_SHAPE_PARMS = {"Sweep", "Sweep_Location", "Dihedral", "Twist", "Root_Chord", "Tip_Chord"}
        FUSELAGE_SHAPE_PARMS = {
            "Width", "Height", "MaxWidthLoc", "CornerRad",
            "TopLAngle", "TopLStrength", "TopRAngle", "TopRStrength",
            "BottomLAngle", "BottomLStrength", "BottomRAngle", "BottomRStrength",
            "LeftLAngle", "LeftLStrength", "RightLAngle", "RightLStrength",
        }
        shape_filter = WING_SHAPE_PARMS if gtype == "Wing" else FUSELAGE_SHAPE_PARMS

        n_surf = vsp.GetNumXSecSurfs(gid) if hasattr(vsp, "GetNumXSecSurfs") else 0
        for si in range(n_surf):
            xsec_surf_id = vsp.GetXSecSurf(gid, si)
            n_xsec = vsp.GetNumXSec(xsec_surf_id)
            for xi in range(n_xsec):
                xsec_id = vsp.GetXSec(xsec_surf_id, xi)
                sec_parms = {}
                for pid in vsp.GetXSecParmIDs(xsec_id):
                    pname = vsp.GetParmName(pid)
                    pval  = vsp.GetParmVal(pid)
                    sec_parms[pname] = pval
                    if pname in shape_filter:
                        key = f"{gname}_{pname}_surf{si}sec{xi}"
                        sweep_candidates[key] = {
                            "geom": gname, "surf": si, "section": xi,
                            "parm": pname, "baseline": pval,
                        }
                entry["sections"][f"surf{si}_sec{xi}"] = sec_parms
                

        dump[gname] = entry

    with open(out_json_path, "w") as f:
        json.dump(dump, f, indent=2)

    geom_names = list(dump.keys())
    print(f"Dumped params for {len(geom_names)} geoms -> {out_json_path}")

    vsp3_dir  = os.path.dirname(vsp3_path)
    vsp3_stem = os.path.splitext(os.path.basename(vsp3_path))[0]

    # ── existing _sets.json template logic — unchanged ──────────────────
    sets_path = os.path.join(vsp3_dir, f"{vsp3_stem}_sets.json")
    if not os.path.exists(sets_path):
        with open(sets_path, "w") as f:
            json.dump({"lifting": [], "non_lifting": [], "_available_geoms": geom_names}, f, indent=2)
        print(f"📝 Classification template created -> {sets_path}")
    else:
        with open(sets_path, "r") as f:
            existing = json.load(f)
        old_names, new_names = set(existing.get("_available_geoms", [])), set(geom_names)
        added, removed = new_names - old_names, old_names - new_names
        if added or removed:
            print(f"⚠️  Geometry changed since {sets_path} was classified — file NOT overwritten.")
        else:
            print(f"   Classification file up to date: {sets_path}")

    # ── NEW: _sweep_params.json template, same pattern ──────────────────
    sweep_path = os.path.join(vsp3_dir, f"{vsp3_stem}_sweep_params.json")
    if not os.path.exists(sweep_path):
        with open(sweep_path, "w") as f:
            json.dump(sweep_candidates, f, indent=2)
        print(f"📝 Sweep-params template created -> {sweep_path}")
        print("   Delete entries you don't need; rename keys to short, meaningful names.")
        print("   Baseline values are pre-filled from the current geometry — verify, don't guess.")
    else:
        print(f"   Sweep-params file already exists, not overwritten: {sweep_path}")

    return dump

def apply_geom_sets(sets_json_path: str) -> tuple:
    """
    Reads the lifting/non_lifting classification JSON and assigns every
    geom in the currently loaded model to the corresponding VSP Set.

    Always force-creates fresh sets at two fixed, pipeline-reserved slot
    indices (the last two of OpenVSP's 20 set slots) -- regardless of
    what sets may already exist in the vsp3 (hand-built or otherwise).
    This makes pipeline behavior independent of prior GUI/session state,
    which is what caused the earlier Set_0/Actual_Geom collision bug.

    DO NOT use the last two set slots for anything else in the GUI --
    the pipeline will overwrite them on every run.

    Returns (thin_set_idx, thick_set_idx) for use as ThinGeomSet/GeomSet
    in VSPAERO analysis inputs.
    """
    import openvsp as vsp
    import json

    with open(sets_json_path, "r") as f:
        cfg = json.load(f)

    lifting     = set(cfg.get("lifting", []))
    non_lifting = set(cfg.get("non_lifting", []))

    num_sets  = vsp.GetNumSets()
    thin_set  = num_sets - 2   # reserved, pipeline-owned
    thick_set = num_sets - 1   # reserved, pipeline-owned

    vsp.SetSetName(thin_set,  "Lifting")
    vsp.SetSetName(thick_set, "Non-Lifting")

    all_geoms    = {vsp.GetGeomName(gid): gid for gid in vsp.FindGeoms()}
    unclassified = set(all_geoms) - lifting - non_lifting
    if unclassified:
        raise ValueError(
            f"Unclassified geoms — add to {sets_json_path}: {sorted(unclassified)}"
        )

    # Clear both reserved slots completely before assigning -- guarantees
    # no leftover flags from a previous run or previous geometry survive.
    for gid in all_geoms.values():
        vsp.SetSetFlag(gid, thin_set,  False)
        vsp.SetSetFlag(gid, thick_set, False)

    for name in lifting:
        vsp.SetSetFlag(all_geoms[name], thin_set, True)
    for name in non_lifting:
        vsp.SetSetFlag(all_geoms[name], thick_set, True)

    vsp.Update()
    print(f"✅ Sets applied — Lifting({len(lifting)})→Set{thin_set}, "
          f"Non-Lifting({len(non_lifting)})→Set{thick_set}")
    return thin_set, thick_set

        
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
    alpha_start    = -5.0,
    alpha_end      = 15.0,
    alpha_npts     = 21,
    beta_start     = 0.0,
    beta_end       = 0.0,
    beta_npts      = 1,
    mach_start     = 0.4,
    mach_end       = 0.4,
    mach_npts      = 1,
    re_cref_start  = 1e6,
    re_cref_end    = 1e6,
    re_cref_npts   = 1,
    wake_iters     = 3,
    thin_geom_set  = 0,
    thick_geom_set = 0,
    ref_mode       = "auto",
    sref = None, bref = None, cref = None,
    run_name       = "aircraft",
):
    
    import openvsp as vsp
    
    # DEBUGGING
    print("   [DEBUG] function entered")          # ← add this
    print("   [DEBUG] wing_id =", wing_id)        # ← add this

    print("\n🔄 Running VSPAero VLM analysis...")
    print(f"   Alpha : {alpha_start}° → {alpha_end}°  ({alpha_npts} points)")
    print(f"   Mach  : {mach_start}   Re: {re_cref_start:.2e}\n")

    # ── 1. SET REFERENCE WING ────────────────────────────────────────────────
    
    # DEBUGGING
    print("   [DEBUG] calling SetVSPAERORefWingID...")
    if ref_mode == "auto":
        vsp.SetVSPAERORefWingID(wing_id)
        print("   [DEBUG] Ref values from wing planform (auto)")
    elif ref_mode == "manual":
        if None in (sref, bref, cref):
            raise ValueError("ref_mode='manual' requires sref, bref, cref.")
        print(f"   [DEBUG] Ref values manual: Sref={sref}, bref={bref}, cref={cref}")
    else:
        raise ValueError("ref_mode must be 'auto' or 'manual'.")
    vsp.PrintAnalysisInputs("VSPAERODegenGeom")
    vsp.PrintAnalysisInputs("DegenGeom")

    # ── 2. SAVE VSP3 ─────────────────────────────────────────────────────────
    vsp_file = os.path.join(VSP_FILES, f"{run_name}.vsp3")
    vsp.WriteVSPFile(vsp_file)
    print(f"   VSP3 saved : {vsp_file}")
    
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
        vsp.SetIntAnalysisInput("VSPAEROComputeGeometry", "GeomSet",     [thick_geom_set])
        vsp.SetIntAnalysisInput("VSPAEROComputeGeometry", "ThinGeomSet", [thin_geom_set])

        geoms_before = set(vsp.FindGeoms())
        geom_rid = vsp.ExecAnalysis("VSPAEROComputeGeometry")
        for gid in set(vsp.FindGeoms()) - geoms_before:
            vsp.DeleteGeom(gid)
        vsp.Update()
        
        if not geom_rid:
            print("❌ VSPAEROComputeGeometry failed — check model geometry.")
            return None, None, None, None
        print(f"   Geometry done. RID: {geom_rid}")

        vspgeom_file = os.path.join(VSP_FILES, f"{run_name}.vspgeom")
        poll_timeout, poll_interval, waited = 30, 0.5, 0.0
        while not os.path.exists(vspgeom_file) and waited < poll_timeout:
            time.sleep(poll_interval)
            waited += poll_interval
        if not os.path.exists(vspgeom_file):
            print(f"❌ .vspgeom not created after waiting {waited}s. Cannot proceed.")
            print(f"   VSP_Files contents: {os.listdir(VSP_FILES)}")
            return None, None, None, None
        print(f"   .vspgeom exists ✅ (waited {waited}s)")

        # ── Auto Re from actual wing planform cref (replaces fixed re_cref) ──
        ATMO_ALT_M = 0.0
        GAMMA, R_AIR = 1.4, 287.05
        T = 288.15 - 0.0065 * ATMO_ALT_M
        RHO = 1.225 * (T / 288.15) ** 4.2561
        MU  = 1.458e-6 * T**1.5 / (T + 110.4)
        a_sound = (GAMMA * R_AIR * T) ** 0.5

        try:
            cref_actual = vsp.GetParmVal(wing_id, "TotalChord", "WingGeom")
        except Exception as e:
            print(f"   ⚠️  Could not read TotalChord off wing_id: {e}")
            cref_actual = None

        if cref_actual:
            V = mach_start * a_sound
            re_cref_start = re_cref_end = (RHO * V * cref_actual) / MU
            print(f"   [DEBUG] auto Re: cref={cref_actual:.4f}m, V={V:.1f}m/s, "
                  f"rho={RHO:.4f}, mu={MU:.3e} -> Re={re_cref_start:.3e}")
        else:
            print("   ⚠️  Falling back to passed-in re_cref_start")

        
        
        # ── 5. VSPAEROSweep — alpha sweep ─────────────────────────────────────
        vsp.SetAnalysisInputDefaults("VSPAEROSweep")

        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "AlphaStart", [alpha_start])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "AlphaEnd",   [alpha_end])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "AlphaNpts",  [alpha_npts])

        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "BetaStart", [beta_start])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "BetaEnd",   [beta_end])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "BetaNpts",  [beta_npts])

        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "MachStart", [mach_start])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "MachEnd",   [mach_end])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "MachNpts",  [mach_npts])

        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "ReCref",      [re_cref_start])
        vsp.SetDoubleAnalysisInput("VSPAEROSweep", "ReCrefEnd",   [re_cref_end])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "ReCrefNpts",  [re_cref_npts])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "WakeNumIter", [wake_iters])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "GeomSet",     [thick_geom_set])
        vsp.SetIntAnalysisInput(   "VSPAEROSweep", "ThinGeomSet", [thin_geom_set])

        if ref_mode == "manual":
            vsp.SetIntAnalysisInput(   "VSPAEROSweep", "RefFlag", [0])
            vsp.SetDoubleAnalysisInput("VSPAEROSweep", "Sref",    [sref])
            vsp.SetDoubleAnalysisInput("VSPAEROSweep", "bref",    [bref])
            vsp.SetDoubleAnalysisInput("VSPAEROSweep", "cref",    [cref])

        print("   Executing VSPAEROSweep...")
        rid = vsp.ExecAnalysis("VSPAEROSweep")
        for gid in set(vsp.FindGeoms()) - geoms_before:
            vsp.DeleteGeom(gid)
        vsp.Update()
        if not rid:
            print("❌ VSPAEROSweep failed.")
            return None, None, None, None
        print(f"   Sweep finished. RID: {rid}")

    finally:
        os.chdir(original_cwd)

    # ── 6. LOCATE .polar FILE ─────────────────────────────────────────────────
    # ExecAnalysis("VSPAEROSweep") appears to return before vspaero.exe has
    # actually finished writing the .polar file (solve continues after RID
    # comes back). Poll instead of checking once — a single immediate check
    # randomly "fails" runs that are still solving, unrelated to sweep angle.
    poll_timeout  = 1800   # sec, generous vs. the 13-20 min solves seen so far
    poll_interval = 5
    waited = 0
    polar_files = glob.glob(os.path.join(VSP_FILES, f"{run_name}.polar"))
    while not polar_files and waited < poll_timeout:
        time.sleep(poll_interval)
        waited += poll_interval
        polar_files = glob.glob(os.path.join(VSP_FILES, f"{run_name}.polar"))

    if not polar_files:
        print(f"⚠️  No {run_name}.polar found in VSP_Files/ after waiting {waited}s")
        print(f"   Contents: {os.listdir(VSP_FILES)}")
        return None, None, None, None
    polar_src = polar_files[0]
    print(f"   Polar file found: {polar_src} (waited {waited}s)")

    # ── 7. COPY TO RESULTS FOLDER ─────────────────────────────────────────────
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    polar_dst = os.path.join(AERO_RESULTS_DIR, f"aero_{run_name}_{timestamp}.polar")    
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
    cl_path = os.path.join(AERO_RESULTS_DIR, f"cl_alpha_{run_name}_{timestamp}.png")
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
    polar_path = os.path.join(AERO_RESULTS_DIR, f"drag_polar_{run_name}_{timestamp}.png")
    fig.savefig(polar_path, dpi=150)
    plt.close(fig)
    print(f"   ✅ Drag polar    : {polar_path}")

    print("\n✅ VSPAero analysis complete.\n")

    # ── 12. L/D vs AoA PLOT ───────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(alpha, LD, 'g-o', markersize=4, linewidth=1.5)
    ax.set_xlabel("Angle of Attack α (deg)", fontsize=12)
    ax.set_ylabel("L/D", fontsize=12)
    ax.set_title(f"L/D vs Alpha — VSPAero VLM (M={mach_start:.2f})", fontsize=13)
    ax.grid(True, linestyle='--', alpha=0.6)
    fig.tight_layout()
    ld_path = os.path.join(AERO_RESULTS_DIR, f"ld_alpha_{run_name}_{timestamp}.png")
    fig.savefig(ld_path, dpi=150)
    plt.close(fig)
    print(f"   ✅ L/D-alpha plot: {ld_path}")

    # ── 13. CD0/K DRAG POLAR FIT (skip cleanly if data is NaN/degenerate) ────
    CD0 = K = r2 = None
    valid = ~(np.isnan(CL) | np.isnan(CDtot))
    if valid.sum() >= 3:
        cl2 = CL[valid]**2
        K, CD0 = np.polyfit(cl2, CDtot[valid], 1)
        fit = CD0 + K*cl2
        ss_res = np.sum((CDtot[valid]-fit)**2)
        ss_tot = np.sum((CDtot[valid]-CDtot[valid].mean())**2)
        r2 = 1 - ss_res/ss_tot if ss_tot > 0 else np.nan
        print(f"   Drag polar fit: CD0={CD0:.5f}  K={K:.4f}  R²={r2:.4f}  (M={mach_start:.2f})")
    else:
        print(f"   ⚠️  Not enough valid points to fit CD0/K (M={mach_start:.2f}) — likely diverged run.")

    print("\n✅ VSPAero analysis complete.\n")
    return polar_dst, CD0, K, r2   # now returning fit params too — update main.py's unpacking accordingly