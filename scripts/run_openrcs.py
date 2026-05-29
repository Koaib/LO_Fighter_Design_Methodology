# -*- coding: utf-8 -*-
"""
run_openrcs.py
==============
Python replacement for run_rcs.m — drives the OpenRCS Physical Optics RCS
computation engine directly, with zero MATLAB / Octave dependency.

How it fits in the pipeline
----------------------------
main.py
  └─ vsp_setup.run_openrcs_rcs()
        └─ run_openrcs.run_openrcs_pipeline()   ← this file
              ├─ stl_module.stl_converter()       STL → coordinates.txt + facets.txt
              ├─ rcs_functions.extractCoordinatesData()  load mesh into memory
              └─ rcs_monostatic.rcs_monostatic()  Physical Optics angle loop → plots + .dat

Source-code tracing (what came from where in OpenRCS)
------------------------------------------------------
stl_module.py  →  stl_converter(file_path)
    Reads the STL mesh using numpy-stl.
    Extracts unique vertex coordinates and saves → coordinates.txt
    Builds face connectivity (node1/node2/node3) + illumination flag (1=closed
    surface, 0=open surface) + Rs=0 (PEC) and saves → facets.txt
    These two text files are the interface between the STL importer and the
    Physical Optics solver.

rcs_functions.py  →  extractCoordinatesData(rs)
    Reads coordinates.txt and facets.txt into numpy arrays:
      x, y, z          vertex coordinates
      node1/2/3        face-vertex indices
      ilum             per-face illumination flag
      Rs               per-face surface resistivity
      vind[ntria,3]    index array for the angle loop
      r[nverts,3]      vertex position array

rcs_functions.py  →  getStandardDeviation(delstd, corel, wave)
    Computes wave-number bk = 2pi/lambda, scattering correction factors
    cfac1 and cfac2 for surface roughness (both = 1 for smooth PEC).

rcs_functions.py  →  getPolarization(ipol)
    Maps ipol integer to complex (Et, Ep) incident field amplitudes:
      ipol=1  TE-z (phi-polarised):   Et=0, Ep=1
      ipol=0  TM-z (theta-polarised): Et=1, Ep=0

rcs_functions.py  →  calculate_values(...)
    Allocates per-facet working arrays and computes total phi steps (ip)
    and theta steps (it).

rcs_functions.py  →  productVector(...)
    Computes face normals via cross-product of edge vectors, normalises them.
    Also computes each triangle area (Heron's formula) and the local spherical
    angles alpha (azimuth of normal) and beta (elevation of normal) used in
    the rotation matrices T1, T2.

rcs_monostatic.py  →  rcs_monostatic(param_list, coord_list)
    Outer loop over all (phi, theta) angle pairs:
      globalAngles()              direction cosines u,v,w; unit vectors uu,vv,ww
      incidentFieldCartesian()    cartesian E-field components e0
      -- inner loop over ntria facets --
        ndot = N[m] dot R  (illumination: skip facet if ndot < 1e-5)
        diretionCosines()         rotation matrices T1, T2  global to local
        sphericalAngles()         local spherical angles th2, phi2
        phaseVerticeTriangle()    Dp=2bk*v1*k, Dq=2bk*v2*k, Do=2bk*v3*k
        incidentFieldSphericalCoordinates()  local Et2, Ep2
        reflectionCoefficients()  Fresnel perp/para (= 1 and -1 for PEC)
        surface currents Jx2, Jy2
        areaIntegral()            DD, expDo, expDp, expDq (exponential terms)
        calculate_Ic()            Taylor-series area integral Ic, 4 special
                                  cases handle near-zero DD arguments
        calculaCampos()           accumulate scattered field sumt, sump
      calculateSth_Sph()          RCS = 10 log10(4*pi*|sum|^2 / lambda^2) dBsm
    After loop:
      generateResultFiles()       writes .dat text file with angle/RCS columns
      plot_triangle_model()       saves JPEG of 3D wire-frame faceted model
      finalPlot()                 saves PNG of RCS vs angle (linear/contour)
    Returns (plot_path, fig_path, dat_path) all under OpenRCS ./results/
"""

import os
import sys
import shutil
import warnings
from datetime import datetime

import matplotlib
matplotlib.use("Agg")   # non-interactive backend — no display needed

# =============================================================================
# RESOLVE PATHS
# =============================================================================
# Layout assumed:
#   <ROOT>/
#     scripts/
#       run_openrcs.py     <- this file
#     OpenRCS/
#       open-rcs/          <- OpenRCS repo clone
#     STL_Files/
#     Results/RCS/

_SCRIPTS_DIR = os.path.abspath(os.path.dirname(__file__))
_ROOT_DIR    = os.path.abspath(os.path.join(_SCRIPTS_DIR, ".."))
_OPENRCS_DIR = os.path.join(_ROOT_DIR, "OpenRCS", "open-rcs")
_STL_DIR     = os.path.join(_ROOT_DIR, "STL_Files")
_RESULTS_DIR = os.path.join(_ROOT_DIR, "Results", "RCS")


def _ensure_openrcs_on_path():
    """Add the OpenRCS source folder to sys.path if not already present."""
    if not os.path.isdir(_OPENRCS_DIR):
        raise FileNotFoundError(
            f"\n❌ OpenRCS source folder not found at:\n   {_OPENRCS_DIR}\n"
            "\n👉 Clone it with:\n"
            "   cd LO_Fighter_Design_Methodology/OpenRCS\n"
            "   git clone https://github.com/comp-ime-eb-br/open-rcs\n"
        )
    if _OPENRCS_DIR not in sys.path:
        sys.path.insert(0, _OPENRCS_DIR)


# =============================================================================
# DEFAULT RCS SETTINGS  (matching old run_rcs.m defaults)
# =============================================================================

DEFAULTS = dict(
    freq   = 12.0,    # GHz
    pol    = "TE-z",  # phi-polarised (Et=0, Ep=1)
    pstart = 0.0,     # phi start  (deg)
    pstop  = 360.0,   # phi stop   (deg)
    delp   = 1.0,     # phi step   (deg)
    tstart = 90.0,    # theta fixed at 90 deg — azimuth (phi) cut
    tstop  = 90.0,
    delt   = 1.0,
    corr   = 0.0,     # surface correlation length (m) — 0 = smooth PEC
    delstd = 0.0,     # surface std deviation (m)     — 0 = no roughness
    rs     = 0,       # 0 = PEC,  1 = specific material
)

# =============================================================================
# FUNCTION TO GENERATE POLAR PLOT
# =============================================================================

def _generate_polar_plot(dat_path, output_path, freq=12.0, theta=90.0, stl_name="aircraft.stl"):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with open(dat_path, "r") as fh:
        lines = fh.readlines()

    def _extract_section(lines, header):
        vals = []
        in_section = False
        for line in lines:
            if header in line:
                in_section = True
                continue
            if in_section:
                stripped = line.strip()
                if not stripped:
                    break
                try:
                    vals.append(float(stripped.strip("[]")))
                except ValueError:
                    break
        return vals

    phi_deg  = np.array(_extract_section(lines, "Phi (deg):"))
    rcs_dbsm = np.array(_extract_section(lines, "RCS Phi (dBsm):"))
    
    # DEBUG
    print(f"  [DEBUG] phi points: {len(phi_deg)}, rcs points: {len(rcs_dbsm)}")
    print(f"  [DEBUG] phi range: {phi_deg[0]} to {phi_deg[-1]}")
    
    if len(phi_deg) == 0 or len(rcs_dbsm) == 0:
        raise ValueError(f"Could not parse Phi/RCS sections in {dat_path}")

    rcs_max   = np.ceil(np.nanmax(rcs_dbsm) / 10) * 10
    rcs_min   = rcs_max - 60
    ring_vals = np.linspace(rcs_min, rcs_max, 7)

    def rcs_to_r(rcs):
        return np.clip((rcs - rcs_min) / (rcs_max - rcs_min), 0, 1)

    r_data     = rcs_to_r(rcs_dbsm)
    theta_plot = np.deg2rad(phi_deg)

    fig = plt.figure(figsize=(9, 9), facecolor="#d0d0d0")
    ax  = fig.add_subplot(111, polar=True, facecolor="#d0d0d0")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    ring_angles = np.linspace(0, 2*np.pi, 361)
    for rv in ring_vals:
        ax.plot(ring_angles, np.full_like(ring_angles, rcs_to_r(rv)),
                color="black", linewidth=0.6, zorder=2)

    for sd in range(0, 360, 30):
        ax.plot([np.deg2rad(sd), np.deg2rad(sd)], [0, 1],
                color="black", linewidth=0.6, zorder=2)

    tc = np.append(theta_plot, theta_plot[0])
    rc = np.append(r_data, r_data[0])
    ax.plot(tc, rc, color="navy", linewidth=0.8, zorder=5)

    for rv in ring_vals:
        rr = rcs_to_r(rv)
        if rr > 0.02:
            ax.text(np.deg2rad(100), rr, f"{rv:.0f}",
                    ha="left", va="center", fontsize=7.5, color="black", zorder=6)

    spoke_labels = {
        0: "0°\n(nose)", 30: "30°", 60: "60°", 90: "90°",
        120: "120°", 150: "150°", 180: "180°\n(tail)",
        210: "210°", 240: "240°", 270: "270°", 300: "300°", 330: "330°",
    }
    ax.set_xticks(np.deg2rad(list(spoke_labels.keys())))
    ax.set_xticklabels(list(spoke_labels.values()), fontsize=8.5)

    ax.set_yticks([])
    ax.grid(False)
    ax.spines["polar"].set_visible(False)
    ax.set_ylim(0, 1)

    wl = 0.3 / freq
    fig.suptitle(
        f"RCS Polar Plot — Monostatic\n"
        f"target: {stl_name}    θ = {theta:.0f}°    f = {freq:.1f} GHz    λ = {wl:.4f} m",
        fontsize=10, y=1.01
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#d0d0d0")
    plt.close(fig)
    print(f"      Polar plot saved → {output_path}")

# =============================================================================
# MAIN PIPELINE FUNCTION
# =============================================================================

def run_openrcs_pipeline(
    stl_path    : str,
    results_dir : str   = _RESULTS_DIR,
    freq        : float = DEFAULTS["freq"],
    pol         : str   = DEFAULTS["pol"],
    pstart      : float = DEFAULTS["pstart"],
    pstop       : float = DEFAULTS["pstop"],
    delp        : float = DEFAULTS["delp"],
    tstart      : float = DEFAULTS["tstart"],
    tstop       : float = DEFAULTS["tstop"],
    delt        : float = DEFAULTS["delt"],
    corr        : float = DEFAULTS["corr"],
    delstd      : float = DEFAULTS["delstd"],
    rs          : int   = DEFAULTS["rs"],
) -> dict:
    """
    End-to-end OpenRCS monostatic RCS pipeline.

    Called directly (in-process) from vsp_setup.run_openrcs_rcs() so that
    every error and print statement appears immediately in the Spyder console.

    Parameters
    ----------
    stl_path    : Absolute path to the STL file exported by OpenVSP.
    results_dir : Folder where final result files are saved.
    freq        : Radar frequency in GHz.
    pol         : 'TE-z' (phi-pol) or 'TM-z' (theta-pol).
    pstart / pstop / delp  : Phi angle sweep in degrees.
    tstart / tstop / delt  : Theta angle sweep in degrees.
    corr / delstd          : Surface roughness parameters (0 = smooth PEC).
    rs                     : 0 = PEC,  1 = specific material (needs matrl.txt).

    Returns
    -------
    dict with keys 'plot', 'fig', 'dat', 'results_dir'
    """

    print("\n" + "=" * 60)
    print("  OpenRCS Monostatic RCS Pipeline")
    print("=" * 60)
    print(f"  STL file   : {stl_path}")
    print(f"  Frequency  : {freq} GHz")
    print(f"  Pol        : {pol}")
    print(f"  Phi        : {pstart} to {pstop} deg  step {delp} deg")
    print(f"  Theta      : {tstart} deg (fixed azimuth cut)")
    print(f"  Results    : {results_dir}")
    print("=" * 60 + "\n")

    # ── sanity checks ──────────────────────────────────────────────────────────
    if not os.path.isfile(stl_path):
        raise FileNotFoundError(
            f"STL file not found: {stl_path}\n"
            "Make sure main.py ran successfully and aircraft.stl was exported."
        )

    _ensure_openrcs_on_path()
    os.makedirs(results_dir, exist_ok=True)

    # ── import OpenRCS modules ─────────────────────────────────────────────────
    # Done here (not at module top level) so that if _OPENRCS_DIR does not
    # exist yet, the import error message is clear and descriptive.
    try:
        from stl_module    import stl_converter
        from rcs_functions import extractCoordinatesData, MATERIALESPECIFICO
        from rcs_monostatic import rcs_monostatic
    except ImportError as exc:
        raise ImportError(
            f"Could not import OpenRCS modules from:\n  {_OPENRCS_DIR}\n"
            f"Original error: {exc}\n\n"
            "Check that:\n"
            "  1. The OpenRCS repo was cloned into OpenRCS/open-rcs/\n"
            "  2. All OpenRCS requirements are installed in the .venv\n"
            "     (numpy-stl, matplotlib, customtkinter, pillow)\n"
        ) from exc

    # ── STEP 1: switch working directory to OpenRCS root ──────────────────────
    # OpenRCS writes and reads these paths relative to its own root:
    #   ./coordinates.txt     written by stl_converter()
    #   ./facets.txt          written by stl_converter()
    #   ./results/<ts>/       written by rcs_monostatic()
    # We must cd there so all relative paths resolve correctly.
    original_cwd = os.getcwd()
    os.chdir(_OPENRCS_DIR)
    print(f"[1/5] Working directory:\n      {_OPENRCS_DIR}\n")

    # out_plot/fig/dat declared here so the finally block can always reference them
    out_plot = out_fig = out_dat = None

    try:
        os.makedirs("stl_models", exist_ok=True)
        os.makedirs("results",    exist_ok=True)

        # ── STEP 2: copy STL into OpenRCS stl_models/ ─────────────────────────
        stl_filename = os.path.basename(stl_path)          # "aircraft.stl"
        stl_dest     = os.path.abspath(
                           os.path.join("stl_models", stl_filename))

        if os.path.abspath(stl_path) != stl_dest:
            shutil.copy2(stl_path, stl_dest)
        print(f"[2/5] STL copied to:\n      {stl_dest}\n")

        # ── STEP 3: STL → coordinates.txt + facets.txt ────────────────────────
        # stl_converter() (stl_module.py):
        #   mesh.Mesh.from_file(path) opens the STL
        #   unique vertices extracted → np.savetxt("coordinates.txt")
        #   face connectivity + ilum + Rs=0 → np.savetxt("facets.txt")
        print("[3/5] Converting STL to coordinates.txt + facets.txt ...")
        stl_converter(stl_dest)
        print("      Done.\n")

        # ── STEP 4: build param_list for rcs_monostatic() ─────────────────────
        # Exact order required — mirrors getParamsFromFile('monostatic'):
        #   [0] input_model  str   filename only (no path)
        #   [1] freq         float Hz  (not GHz — the PO solver expects Hz)
        #   [2] corr         float surface correlation length (m)
        #   [3] delstd       float surface std deviation (m)
        #   [4] ipol         int   0=TM-z, 1=TE-z
        #   [5] rs           int   0=PEC, 1=specific material
        #   [6] pstart       float phi start (deg)
        #   [7] pstop        float phi stop  (deg)
        #   [8] delp         float phi step  (deg)
        #   [9] tstart       float theta start (deg)
        #   [10] tstop       float theta stop  (deg)
        #   [11] delt        float theta step  (deg)
        #   [12] matrlpath   str   path to matrl file (only used when rs==1)
        ipol      = 1 if pol.upper() == "TE-Z" else 0
        freq_hz   = freq * 1e9
        matrlpath = os.path.join(_OPENRCS_DIR, "matrl.txt")

        param_list = [
            stl_filename, freq_hz, corr, delstd, ipol, rs,
            pstart, pstop, delp,
            tstart, tstop, delt,
            matrlpath,
        ]

        # ── STEP 5: load mesh arrays ───────────────────────────────────────────
        # extractCoordinatesData(rs) reads coordinates.txt + facets.txt and
        # returns a 17-element list:
        #   x,y,z,xpts,ypts,zpts,nverts,nfc,node1,node2,node3,
        #   iflag,ilum,Rs,ntria,vind,r
        print("[4/5] Loading mesh data ...")
        coord_list = extractCoordinatesData(rs)
        print("      Done.\n")

        # ── STEP 6: Physical Optics RCS computation ────────────────────────────
        print("[5/5] Running Physical Optics RCS computation ...")
        print("      (may take a few minutes for high-resolution meshes)\n")
        warnings.filterwarnings("ignore")
        plot_name, fig_name, file_name = rcs_monostatic(param_list, coord_list)
        print(f"\n      plot → {plot_name}")
        print(f"      fig  → {fig_name}")
        print(f"      dat  → {file_name}\n")

        # ── STEP 7: copy results to project Results/RCS/ ──────────────────────
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem      = os.path.splitext(stl_filename)[0]   # "aircraft"
        base      = f"rcs_{stem}_{timestamp}"

        out_plot = os.path.join(results_dir, base + "_plot.png")
        out_fig  = os.path.join(results_dir, base + "_3d.jpg")
        out_dat  = os.path.join(results_dir, base + "_results.dat")

        if os.path.isfile(plot_name):
            shutil.copy2(plot_name, out_plot)
        else:
            print(f"  Warning: plot file not found at {plot_name}")
            out_plot = None

        if os.path.isfile(fig_name):
            shutil.copy2(fig_name, out_fig)
        else:
            print(f"  Warning: fig file not found at {fig_name}")
            out_fig = None

        if os.path.isfile(file_name):
            shutil.copy2(file_name, out_dat)
        else:
            print(f"  Warning: data file not found at {file_name}")
            out_dat = None

        print(f"Results saved to: {results_dir}")
        if out_plot: print(f"  RCS plot  : {out_plot}")
        if out_fig:  print(f"  3D figure : {out_fig}")
        if out_dat:  print(f"  Data file : {out_dat}")
        
        
        
        # ── STEP 8: polar plot ─────────────────────────────────────────────────
        out_polar = None
        if out_dat and os.path.isfile(out_dat):
            out_polar = os.path.join(results_dir, base + "_polar.png")
            try:
                _generate_polar_plot(
                    dat_path    = out_dat,
                    output_path = out_polar,
                    freq        = freq,
                    theta       = tstart,
                    stl_name    = stl_filename,
                )
                print(f"  Polar plot: {out_polar}")
            except Exception as e:
                import traceback
                print(f"  Warning: polar plot failed — {e}")
                traceback.print_exc()
                out_polar = None
    finally:
        # Restore working directory even if an exception was raised.
        # If we don't do this, any code after a crash would operate from
        # inside the OpenRCS directory and break other relative paths.
        os.chdir(original_cwd)

    print("\n✅ OpenRCS pipeline complete.\n")
    return {
        "plot":        out_plot,
        "fig":         out_fig,
        "dat":         out_dat,
        "polar":        out_polar,
        "results_dir": results_dir,
    }


# =============================================================================
# CLI / STANDALONE ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # When run directly, use the default STL file and default RCS settings.
    # Useful for testing the RCS pipeline independently of OpenVSP.
    default_stl = os.path.join(_STL_DIR, "aircraft.stl")
    run_openrcs_pipeline(stl_path=default_stl)