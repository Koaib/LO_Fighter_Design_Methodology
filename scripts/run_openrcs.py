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


RUNS (if pol="both"):
  1  TE-z  Azimuth cut    θ=90°  φ=0→360°
  2  TM-z  Azimuth cut    θ=90°  φ=0→360°
  3  TE-z  Elevation cut  φ=0°   θ=0→180°
  4  TM-z  Elevation cut  φ=0°   θ=0→180°
  5  TE-z  Frontal 2-D    φ=−30→30°  θ=75→105°  (mean table only, no plot)
  6  TM-z  Frontal 2-D    φ=−30→30°  θ=75→105°  (mean table only, no plot)

OUTPUT FILES:
  Linear_Azimuth_Cut_90deg_<ts>.png          TE-z and/or TM-z co+cross-pol vs φ
  Polar_TE-z_Azimuth_Cut_90deg_<ts>.png      TE-z polar map (if TE-z run)
  Polar_TM-z_Azimuth_Cut_90deg_<ts>.png      TM-z polar map (if TM-z run)
  Linear_Elevation_Cut_0deg_<ts>.png         TE-z and/or TM-z vs elevation
  Polar_TE-z_Elevation_Cut_0deg_<ts>.png     TE-z elevation polar (if TE-z run)
  Polar_TM-z_Elevation_Cut_0deg_<ts>.png     TM-z elevation polar (if TM-z run)
  MeanRCS_Table_<ts>.png                     mean RCS table (runs that were done)
  aircraft_3D_<ts>.jpg                       3-D facet model (once only)
  <stem>_<TAG>_<ts>.dat                      raw data per run (AZ_TE, EL_TM, etc.)
  
POLARISATION CONVENTION:
  TE-z  (ipol=1, phi-polarised):   dominant co-pol scattered component = Sφ
  TM-z  (ipol=0, theta-polarised): dominant co-pol scattered component = Sθ
  Cross-pol is near zero for a bilaterally symmetric aircraft; it is still
  plotted (dashed, light colour) so the user can confirm low cross-pol.

AZIMUTH DISPLAY CONVENTION:
  Solver uses φ = 0→360°.  Linear plots display −180°→+180° so the aircraft
  nose (0°) is at the centre of the x-axis.  Polar maps keep 0° at the top
  (compass convention, same as POFACETS).

ELEVATION DISPLAY CONVENTION:
  Solver uses θ = 0→180° (0°=up, 90°=horizontal, 180°=down).
  Linear plots display elevation = 90°−θ, so 0° = horizontal (head-on level),
  +90° = directly above, −90° = directly below.

MEAN RCS (Touzopoulos 2017 methodology):
  Total scattered power per angle = Sθ_linear + Sφ_linear.
  Mean = average over all angles in linear domain → converted to dBsm.
  This gives ONE representative scalar per run.
  Frontal sector (runs 5+6) averages over az ±30° AND el ±15°.
"""

import os
import sys
import shutil
import warnings
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# =============================================================================
# PATHS
# =============================================================================

_SCRIPTS_DIR = os.path.abspath(os.path.dirname(__file__))
_ROOT_DIR    = os.path.abspath(os.path.join(_SCRIPTS_DIR, ".."))
_OPENRCS_DIR = os.path.join(_ROOT_DIR, "OpenRCS", "open-rcs")
_STL_DIR     = os.path.join(_ROOT_DIR, "STL_Files")
_RESULTS_DIR = os.path.join(_ROOT_DIR, "Results", "RCS")


def _ensure_openrcs_on_path():
    if not os.path.isdir(_OPENRCS_DIR):
        raise FileNotFoundError(f"\n❌ OpenRCS not found at: {_OPENRCS_DIR}")
    if _OPENRCS_DIR not in sys.path:
        sys.path.insert(0, _OPENRCS_DIR)


# =============================================================================
# .DAT FILE PARSER
#
# generateResultFiles() in rcs_functions.py writes each section like this:
#
#   Azimuth cut  (ip>1, it=1):  ip lines, each = str(array_shape_1) = "[v]"
#   Elevation cut (ip=1, it>1): 1 line   = str(array_shape_it) = "[v0 v1 ...]"
#   Frontal 2-D  (ip>1, it>1): ip lines, each = str(array_shape_it)
#
# The parser strips brackets, splits on whitespace, and collects all floats
# until the first blank line (which separates sections in the .dat file).
# This handles all three formats transparently.
# =============================================================================

def _parse_dat(dat_path: str) -> dict:
    """
    Parse an OpenRCS .dat result file.

    Returns a dict with flat 1-D numpy arrays:
        'phi_vals'   : phi angles in degrees
        'theta_vals' : theta angles in degrees
        'sth'        : RCS theta component (dBsm)
        'sph'        : RCS phi   component (dBsm)

    Array lengths:
        Azimuth cut  (ip=361, it=1)  → 361 values each
        Elevation cut (ip=1, it=181) → 181 values each
        Frontal 2-D  (ip=61, it=31)  → 1891 values each (61×31 flattened)
    """
    with open(dat_path) as fh:
        content = fh.read()

    def _extract(header: str) -> np.ndarray:
        """
        Find 'header\\n' in content, then read all floats until a blank line.
        Each data line may be a single value "[v]" or a full array "[v0 v1 ...]".
        Brackets are stripped; values are split on whitespace.
        """
        tag = header + "\n"
        idx = content.find(tag)
        if idx == -1:
            return np.array([])
        start = idx + len(tag)
        vals  = []
        for line in content[start:].splitlines():
            s = line.strip()
            if not s:                           # blank line = section boundary
                break
            clean = s.replace("[", "").replace("]", "")
            try:
                vals.extend(float(x) for x in clean.split())
            except ValueError:
                break                           # non-numeric = next header
        return np.array(vals)

    return {
        "phi_vals":   _extract("Phi (deg):"),
        "theta_vals": _extract("Theta (deg):"),
        "sth":        _extract("RCS Theta (dBsm):"),
        "sph":        _extract("RCS Phi (dBsm):"),
    }


# =============================================================================
# UNIT CONVERSION
# =============================================================================

def _lin(db_arr: np.ndarray) -> np.ndarray:
    """dBsm → linear (m²).  Clips at 1e-15 to prevent log(0)."""
    return np.clip(10.0 ** (db_arr / 10.0), 1e-15, None)


def _db(lin_val: float) -> float:
    """Linear (m²) → dBsm."""
    return 10.0 * np.log10(max(float(lin_val), 1e-15))


# =============================================================================
# MEAN RCS
#
# Total scattered power per angle = Sθ_linear + Sφ_linear.
# Mean = average over all angles in linear domain, then → dBsm.
# Works for any flat array (azimuth 361 pts, elevation 181 pts, frontal 1891 pts).
# =============================================================================

def _mean_total(sth: np.ndarray, sph: np.ndarray) -> float:
    """
    Mean total monostatic RCS (dBsm).

    Adds theta and phi scattered power in linear domain, averages, converts
    back to dBsm.  Gives one representative number per solver run.
    """
    return _db(float(np.mean(_lin(sth) + _lin(sph))))


# =============================================================================
# AZIMUTH DISPLAY TRANSFORM
#
# Solver outputs φ in [0°, 360°], including both 0° and 360° endpoints
# (same physical angle — duplicate).  For Cartesian linear plots we:
#   1. Remove the duplicate 360° endpoint.
#   2. Remap values > 180° to negative:  φ_disp = φ − 360  if  φ > 180°
#   3. Sort ascending so x-axis runs −180° → +180°, nose at 0°.
#
# Returns (x_display, reorder_index) so the caller can reorder RCS arrays.
# =============================================================================

def _phi_to_display(phi_arr: np.ndarray):
    """
    Map φ [0°, 360°] → [−180°, +180°] and sort ascending.

    Returns
    -------
    x_disp : 1-D array, φ in [−180°, +180°], ascending (nose at 0°)
    idx    : reorder indices — apply to Sth/Sph arrays to match x_disp
    """
    arr = phi_arr.copy()
    # remove duplicate endpoint (360° == 0°)
    if len(arr) > 1 and np.isclose(arr[-1], arr[0] + 360.0):
        arr = arr[:-1]
    disp = np.where(arr > 180.0, arr - 360.0, arr)
    idx  = np.argsort(disp)
    return disp[idx], idx


# =============================================================================
# PLOT A — Cartesian RCS vs angle  (one polarisation, two components)
#
# Shows:
#   co-pol  : dominant component (Sφ for TE-z, Sθ for TM-z) — solid, full colour
#   cross-pol: orthogonal component — dashed, lighter colour
#
# Y-axis is clipped to [max(co-pol) − 65, max(co-pol) + 5] dBsm.
# This prevents the near-zero cross-pol flat line at −100 dBsm from
# collapsing the useful portion of the plot.
# =============================================================================

def _plot_dual_linear(x_arr_te, copol_te, xpol_te,
                      x_arr_tm, copol_tm, xpol_tm,
                      output_path, *, title, subtitle, xlabel,
                      only_te=False, only_tm=False) -> None:
    """
    Cartesian RCS vs angle plot.

    If both polarisations are available: four curves (TE-z co+cross, TM-z co+cross).
    If only one polarisation was run: two curves (co-pol solid, cross-pol dashed).

    Parameters
    ----------
    only_te : True when TM-z was not run — plot TE-z only
    only_tm : True when TE-z was not run — plot TM-z only
    """
    fig, ax = plt.subplots(figsize=(11, 5), facecolor="white")
    ax.set_facecolor("white")

    if not only_tm:
        ax.plot(x_arr_te, copol_te, color="steelblue", lw=1.0,
                label="TE-z  Sφ  (co-pol)")
        ax.plot(x_arr_te, xpol_te, color="steelblue", lw=0.8,
                linestyle="--", alpha=0.5,
                label="TE-z  Sθ  (cross-pol)")

    if not only_te:
        ax.plot(x_arr_tm, copol_tm, color="crimson", lw=1.0,
                label="TM-z  Sθ  (co-pol)")
        ax.plot(x_arr_tm, xpol_tm, color="crimson", lw=0.8,
                linestyle="--", alpha=0.5,
                label="TM-z  Sφ  (cross-pol)")

    ymax = float(np.nanmax([np.nanmax(copol_te), np.nanmax(copol_tm)])) + 5.0
    #ymin = ymax - 65.0
    # changed min y so crosspol component also dispalys (-100 dBsm)
    ymin = -110.0
    ax.set_ylim(ymin, ymax)

    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel("RCS (dBsm)", fontsize=11)
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(True, linestyle="--", alpha=0.55)
    ax.axvline(0, color="black", lw=0.6, linestyle=":")

    fig.suptitle(f"{title}\n{subtitle}", fontsize=10)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"      saved → {os.path.basename(output_path)}")
    
# =============================================================================
# PLOT B — full-circle polar map  (azimuth cut, co-pol component only)
#
# Shows only the co-pol component (Sφ for TE-z, Sθ for TM-z) because the
# cross-pol is near zero for a symmetric aircraft and produces a blank map.
#
# Both TE-z and TM-z maps share the same rcs_min/rcs_max scale so they are
# directly visually comparable.
#
# Compass convention: 0° (nose) at top, angles increase clockwise.
# =============================================================================

def _rcs_to_r(rcs: np.ndarray, rcs_min: float, rcs_max: float) -> np.ndarray:
    """Normalise RCS (dBsm) to polar radius in [0, 1]."""
    return np.clip((rcs - rcs_min) / (rcs_max - rcs_min), 0.0, 1.0)

def _plot_polar(phi_arr, copol_arr, xpol_arr, output_path, *,
                title, subtitle, color, rcs_min, rcs_max,
                spoke_override=None) -> None:
    """
    Full-circle polar RCS map with two curves for one polarisation:
      co-pol  — solid, full colour
      cross-pol — dashed, same colour at 40% opacity

    Both curves share the same normalised radius scale (rcs_min → rcs_max)
    so they are directly comparable.  Cross-pol will hug near the centre
    for a symmetric aircraft, visually confirming low depolarisation.

    Parameters
    ----------
    phi_arr   : φ angles in degrees, 0→359° (duplicate 360° removed)
    copol_arr : co-pol RCS (dBsm) — same length as phi_arr
    xpol_arr  : cross-pol RCS (dBsm) — same length as phi_arr
    title     : first title line
    subtitle  : remaining title lines
    color     : base colour (used for both curves; cross-pol gets alpha=0.4)
    rcs_min   : lower dBsm bound of shared scale
    rcs_max   : upper dBsm bound of shared scale
    spoke_override : optional dict {angle_deg: label} to replace default spokes
    """
    ring_vals   = np.linspace(rcs_min, rcs_max, 7)
    ring_angles = np.linspace(0, 2 * np.pi, 361)

    fig = plt.figure(figsize=(7, 7), facecolor="#e8e8e8")
    ax  = fig.add_subplot(111, polar=True, facecolor="#e8e8e8")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    # concentric dBsm rings
    for rv in ring_vals:
        rr = _rcs_to_r(rv, rcs_min, rcs_max)
        ax.plot(ring_angles, np.full_like(ring_angles, rr),
                color="grey", lw=0.5, zorder=2)
        if rr > 0.05:
            ax.text(np.deg2rad(105), rr, f"{rv:.0f}",
                    ha="left", va="center", fontsize=7.5,
                    color="dimgrey", zorder=6)

    # spokes every 30°
    for sd in range(0, 360, 30):
        ax.plot([np.deg2rad(sd), np.deg2rad(sd)], [0, 1],
                color="grey", lw=0.5, zorder=2)

    # co-pol curve — close back to start
    r_co = _rcs_to_r(copol_arr, rcs_min, rcs_max)
    tc   = np.append(np.deg2rad(phi_arr), np.deg2rad(phi_arr[0]))
    rc   = np.append(r_co, r_co[0])
    ax.plot(tc, rc, color=color, lw=1.0, zorder=5,
            label="co-pol")

    # cross-pol curve
    r_xp  = _rcs_to_r(xpol_arr, rcs_min, rcs_max)
    rx    = np.append(r_xp, r_xp[0])
    ax.plot(tc, rx, color=color, lw=0.8, linestyle="--",
            alpha=0.4, zorder=4, label="cross-pol")

    # legend inside polar axes
    ax.legend(loc="lower left", bbox_to_anchor=(0.02, 0.02),
              fontsize=8, framealpha=0.6)

    spokes = spoke_override if spoke_override is not None else {
        0: "0°\n(nose)", 30: "30°", 60: "60°", 90: "90°",
        120: "120°", 150: "150°", 180: "180°\n(tail)",
        210: "210°", 240: "240°", 270: "270°", 300: "300°", 330: "330°",
    }
    ax.set_xticks(np.deg2rad(list(spokes.keys())))
    ax.set_xticklabels(list(spokes.values()), fontsize=8)
    ax.set_yticks([])
    ax.grid(False)
    ax.spines["polar"].set_visible(False)
    ax.set_ylim(0, 1)

    fig.suptitle(f"{title}\n{subtitle}", fontsize=9, y=1.02)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#e8e8e8")
    plt.close(fig)
    print(f"      saved → {os.path.basename(output_path)}")
    

# =============================================================================
# TABLE — mean RCS summary (PNG image)
#
# 6 rows, one per solver run.  Column = mean total RCS (dBsm).
# Row colours: blue = azimuth, green = elevation, orange = frontal.
#
# Frontal sector row is the most important stealth metric:
#   it averages az ±30° AND el ±15°, exactly as Touzopoulos 2017.
# =============================================================================

def _save_mean_table(rows, output_path, freq, stl_name) -> None:
    """
    Save mean RCS summary as a PNG table image.

    Parameters
    ----------
    rows : list of (run_label: str, mean_rcs: float)
          Expected order: AZ_TE, AZ_TM, EL_TE, EL_TM, FR_TE, FR_TM
    """
    fig, ax = plt.subplots(figsize=(9, 3.5), facecolor="white")
    ax.set_facecolor("white")
    ax.axis("off")

    col_labels = ["Run", "Mean Total RCS  (dBsm)"]
    cell_data  = [
        [label, f"{val:.2f}" if np.isfinite(val) else "N/A"]
        for label, val in rows
    ]
    row_colors = [
        ["#dce9f7", "#dce9f7"],   # azimuth TE-z  — blue
        ["#dce9f7", "#dce9f7"],   # azimuth TM-z  — blue
        ["#d5ecd5", "#d5ecd5"],   # elevation TE-z — green
        ["#d5ecd5", "#d5ecd5"],   # elevation TM-z — green
        ["#fde9cc", "#fde9cc"],   # frontal TE-z  — orange
        ["#fde9cc", "#fde9cc"],   # frontal TM-z  — orange
    ]

    tbl = ax.table(
        cellText    = cell_data,
        colLabels   = col_labels,
        cellLoc     = "center",
        loc         = "center",
        cellColours = row_colors,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.scale(1.2, 2.0)

    ax.set_title(
        f"Mean RCS Summary  —  {stl_name}    f = {freq:.1f} GHz\n"
        "Mean = average total scattered power (Sθ + Sφ) in linear domain",
        fontsize=11, pad=14,
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"      saved → {os.path.basename(output_path)}")


# =============================================================================
# SOLVER HELPER
# =============================================================================

def _run_single_pol(param_base: list, coord_list: list, ipol: int):
    """
    Call rcs_monostatic() with a specific polarisation.

    param_base : 13-element list (see _make_params below); index 4 is ipol.
    coord_list : mesh arrays from extractCoordinatesData().
    ipol       : 1 = TE-z (phi-polarised),  0 = TM-z (theta-polarised).

    Returns (plot_path, fig_path, dat_path) from rcs_monostatic().
    """
    from rcs_monostatic import rcs_monostatic
    pl    = list(param_base)  # copy — never mutate the shared base list
    pl[4] = ipol
    return rcs_monostatic(pl, coord_list)


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_openrcs_pipeline(
    stl_path    : str,
    results_dir : str   = _RESULTS_DIR,
    freq        : float = 12.0,
    pol         : str   = "both",
    cuts        : str   = "all",
    corr        : float = 0.0,
    delstd      : float = 0.0,
    rs          : int   = 0,
) -> dict:
    """
    End-to-end OpenRCS monostatic RCS pipeline.

    Parameters
    ----------
    stl_path    : absolute path to the STL file exported by OpenVSP
    results_dir : output folder
    freq        : radar frequency in GHz
    pol         : "TE-z", "TM-z", or "both" (default)
    corr        : surface roughness correlation length m (0 = smooth PEC)
    delstd      : surface roughness std deviation m     (0 = smooth PEC)
    rs          : 0 = Perfect Electric Conductor

    Returns
    -------
    dict with output file paths keyed by descriptive names
    """
    print("\n" + "=" * 60)
    print("  OpenRCS Monostatic RCS Pipeline")
    print("=" * 60)
    print(f"  STL        : {stl_path}")
    print(f"  Frequency  : {freq} GHz    Polarisation: {pol}")
    print(f"  Cuts       : Azimuth θ=90°  |  Elevation φ=0°  |  Frontal 2-D")
    print("=" * 60 + "\n")

    if not os.path.isfile(stl_path):
        raise FileNotFoundError(f"STL not found: {stl_path}")

    _ensure_openrcs_on_path()
    os.makedirs(results_dir, exist_ok=True)

    try:
        from stl_module    import stl_converter
        from rcs_functions import extractCoordinatesData
    except ImportError as exc:
        raise ImportError(
            f"Cannot import OpenRCS modules from {_OPENRCS_DIR}.\n{exc}"
        ) from exc

    original_cwd = os.getcwd()
    os.chdir(_OPENRCS_DIR)

    out = {
        "linear_az":   None,
        "polar_az_te": None, "polar_az_tm": None,
        "linear_el":   None,
        "polar_el_te": None, "polar_el_tm": None,
        "mean_table":  None,
        "fig_3d":      None,
        "results_dir": results_dir,
    }
    
    try:
        os.makedirs("stl_models", exist_ok=True)
        os.makedirs("results",    exist_ok=True)

        # ── copy STL into OpenRCS working directory ───────────────────────────
        stl_filename = os.path.basename(stl_path)
        stl_dest     = os.path.abspath(os.path.join("stl_models", stl_filename))
        if os.path.abspath(stl_path) != stl_dest:
            shutil.copy2(stl_path, stl_dest)

        # ── convert STL → coordinates.txt + facets.txt ───────────────────────
        print("[1/3] Converting STL → mesh files ...")
        stl_converter(stl_dest)

        # ── load mesh arrays (done ONCE for all 6 runs) ───────────────────────
        print("[2/3] Loading mesh ...")
        coord_list = extractCoordinatesData(rs)

        # ── build param_list factory ──────────────────────────────────────────
        # rcs_monostatic() expects a 13-element list:
        #   [0] stl_filename  str
        #   [1] freq          float  Hz  (not GHz)
        #   [2] corr          float  surface correlation length
        #   [3] delstd        float  surface std deviation
        #   [4] ipol          int    0=TM-z, 1=TE-z  ← overridden per call
        #   [5] rs            int    0=PEC
        #   [6] pstart        float  phi start   (deg)
        #   [7] pstop         float  phi stop    (deg)
        #   [8] delp          float  phi step    (deg)
        #   [9] tstart        float  theta start (deg)
        #  [10] tstop         float  theta stop  (deg)
        #  [11] delt          float  theta step  (deg)
        #  [12] matrlpath     str    path to material file
        matrlpath = os.path.join(_OPENRCS_DIR, "matrl.txt")
        freq_hz   = freq * 1e9

        def _make_params(pstart, pstop, delp, tstart, tstop, delt):
            """
            Build a base param_list.  ipol (index 4) is 0 here and gets
            overridden by _run_single_pol() before each solver call.
            """
            return [
                stl_filename, freq_hz, corr, delstd,
                0,                              # ipol placeholder
                rs,
                pstart, pstop, delp,
                tstart, tstop, delt,
                matrlpath,
            ]

        # ── three cut configurations ──────────────────────────────────────────

        # Azimuth cut: full phi sweep at fixed theta=90° (radar at same altitude).
        # ip = (360-0)/1 + 1 = 361,  it = 1
        params_az = _make_params(
            pstart=0.0, pstop=360.0, delp=1.0,
            tstart=90.0, tstop=90.0, delt=1.0,
        )

        # Elevation cut: fixed phi=0° (nose direction), full theta sweep.
        # ip = 1,  it = (180-0)/1 + 1 = 181
        params_el = _make_params(
            pstart=0.0, pstop=0.0, delp=1.0,
            tstart=0.0, tstop=180.0, delt=1.0,
        )

        # Frontal 2-D: az ±30° and el ±15° (theta 75°→105°).
        # Used only for mean frontal sector RCS — no plot generated.
        # ip = (-30 to 30)/1 + 1 = 61,  it = (75 to 105)/1 + 1 = 31
        params_fr = _make_params(
            pstart=-30.0, pstop=30.0, delp=1.0,
            tstart=75.0, tstop=105.0, delt=1.0,
        )

        pol_upper  = pol.upper()
        run_te     = pol_upper in ("TE-Z", "BOTH")
        run_tm     = pol_upper in ("TM-Z", "BOTH")

        # decide which cuts to run based on the cuts parameter
        cuts_lower = cuts.lower().replace(" ", "")
        do_az  = any(c in cuts_lower for c in ("azimuth",  "all"))
        do_el  = any(c in cuts_lower for c in ("elevation","all"))
        do_fr  = any(c in cuts_lower for c in ("frontal",  "all"))

        # count total runs for progress labelling
        total = sum([
            do_az and run_te, do_az and run_tm,
            do_el and run_te, do_el and run_tm,
            do_fr and run_te, do_fr and run_tm,
        ])
        run_n = 0

        def _run(tag, params, ipol, label):
            nonlocal run_n
            run_n += 1
            print(f"  Run {run_n}/{total}  {label} ...")
            raw[tag] = _run_single_pol(params, coord_list, ipol=ipol)

        print("[3/3] Running Physical Optics solver ...")
        warnings.filterwarnings("ignore")
        
        raw = {}
        
        if do_az and run_te: _run("AZ_TE", params_az, 1, "TE-z  Azimuth   cut")
        if do_az and run_tm: _run("AZ_TM", params_az, 0, "TM-z  Azimuth   cut")
        if do_el and run_te: _run("EL_TE", params_el, 1, "TE-z  Elevation cut")
        if do_el and run_tm: _run("EL_TM", params_el, 0, "TM-z  Elevation cut")
        if do_fr and run_te: _run("FR_TE", params_fr, 1, "TE-z  Frontal   2-D")
        if do_fr and run_tm: _run("FR_TM", params_fr, 0, "TM-z  Frontal   2-D")
        
        # ── copy dat files to results folder ─────────────────────────────────
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = os.path.splitext(stl_filename)[0]

        def _cp(src, dst):
            if src and os.path.isfile(src):
                shutil.copy2(src, dst)
                return dst
            return None

        dat_paths = {}
        for tag, tup in raw.items():
            if tup:
                dst = os.path.join(results_dir, f"{stem}_{tag}_{ts}.dat")
                dat_paths[tag] = _cp(tup[2], dst)

        # ── save 3-D figure once (from the first available run) ───────────────
        for tag in ("AZ_TE", "AZ_TM", "EL_TE", "EL_TM"):
            if tag in raw and raw[tag] and raw[tag][1] and os.path.isfile(raw[tag][1]):
                dst = os.path.join(results_dir, f"aircraft_3D_{ts}.jpg")
                out["fig_3d"] = _cp(raw[tag][1], dst)
                break

        # ── parse all dat files ───────────────────────────────────────────────
        parsed = {}
        for tag, path in dat_paths.items():
            if path:
                parsed[tag] = _parse_dat(path)

        # ── shared polar scale ────────────────────────────────────────────────
        # Both azimuth polar maps use the same dBsm range so TE-z and TM-z
        # are directly comparable at a glance.
        # TE-z co-pol = Sφ,  TM-z co-pol = Sθ
        copol_for_scale = []
        if "AZ_TE" in parsed and len(parsed["AZ_TE"]["sph"]):
            copol_for_scale.append(parsed["AZ_TE"]["sph"])
        if "AZ_TM" in parsed and len(parsed["AZ_TM"]["sth"]):
            copol_for_scale.append(parsed["AZ_TM"]["sth"])

        if copol_for_scale:
            gmax = np.ceil(max(np.nanmax(a) for a in copol_for_scale) / 10) * 10
            gmin = gmax - 60.0
        else:
            gmax, gmin = 20.0, -40.0

        wl = 0.3 / freq   # wavelength in metres

        # ── AZIMUTH LINEAR PLOT (both polarisations, one figure) ──────────────
        # TE-z dominant output = Sph.  TM-z dominant output = Sth.
        # Cross-pol (~0 for symmetric aircraft) is not shown — it adds no info.
        if "AZ_TE" in parsed or "AZ_TM" in parsed:
            only_te_az = "AZ_TE" in parsed and "AZ_TM" not in parsed
            only_tm_az = "AZ_TM" in parsed and "AZ_TE" not in parsed
            d_te = parsed.get("AZ_TE")
            d_tm = parsed.get("AZ_TM")
            if d_te is None: d_te = d_tm
            if d_tm is None: d_tm = d_te
            x_te, idx_te = _phi_to_display(d_te["phi_vals"])
            x_tm, idx_tm = _phi_to_display(d_tm["phi_vals"])
            fname = f"Linear_Azimuth_Cut_90deg_{ts}.png"
            fpath = os.path.join(results_dir, fname)
            _plot_dual_linear(
                x_te, d_te["sph"][idx_te], d_te["sth"][idx_te],
                x_tm, d_tm["sth"][idx_tm], d_tm["sph"][idx_tm],
                fpath,
                title    = "Monostatic RCS — Azimuth Cut",
                subtitle = (f"θ = 90°    f = {freq:.1f} GHz    "
                            f"λ = {wl:.4f} m    "
                            f"nose at 0°,  tail at ±180°"),
                xlabel   = "Azimuth Angle  φ (deg)",
                only_te  = only_te_az,
                only_tm  = only_tm_az,
            )
            out["linear_az"] = fpath
            
            
        # ── AZIMUTH POLAR MAPS ────────────────────────────────────────────────
        # Co-pol only.  Cross-pol is not plotted here (near zero → blank map).
        if "AZ_TE" in parsed and len(parsed["AZ_TE"]["sph"]):
            d = parsed["AZ_TE"]
            phi_arr = d["phi_vals"].copy()
            # remove duplicate 360° endpoint if present
            if len(phi_arr) > 1 and np.isclose(phi_arr[-1], phi_arr[0] + 360.0):
                phi_arr = phi_arr[:-1]
            sph_arr = d["sph"][:len(phi_arr)]
            fname = f"Polar_TE-z_Azimuth_Cut_90deg_{ts}.png"
            fpath = os.path.join(results_dir, fname)
            _plot_polar(
                phi_arr, sph_arr, d["sth"][:len(phi_arr)], fpath,
                title   = "Polar RCS Map — TE-z polarisation",
                subtitle= (f"Azimuth cut  θ = 90°    "
                           f"f = {freq:.1f} GHz    λ = {wl:.4f} m\n"
                           f"scale: {gmin:.0f} dBsm (centre) → {gmax:.0f} dBsm (rim)"),
                color   = "steelblue",
                rcs_min = gmin,
                rcs_max = gmax,
            )
            out["polar_az_te"] = fpath

        if "AZ_TM" in parsed and len(parsed["AZ_TM"]["sth"]):
            d = parsed["AZ_TM"]
            phi_arr = d["phi_vals"].copy()
            if len(phi_arr) > 1 and np.isclose(phi_arr[-1], phi_arr[0] + 360.0):
                phi_arr = phi_arr[:-1]
            sth_arr = d["sth"][:len(phi_arr)]
            fname = f"Polar_TM-z_Azimuth_Cut_90deg_{ts}.png"
            fpath = os.path.join(results_dir, fname)
            _plot_polar(
                phi_arr, sth_arr, d["sph"][:len(phi_arr)], fpath,
                title   = "Polar RCS Map — TM-z polarisation",
                subtitle= (f"Azimuth cut  θ = 90°    "
                           f"f = {freq:.1f} GHz    λ = {wl:.4f} m\n"
                           f"scale: {gmin:.0f} dBsm (centre) → {gmax:.0f} dBsm (rim)"),
                color   = "crimson",
                rcs_min = gmin,
                rcs_max = gmax,
            )
            out["polar_az_tm"] = fpath

        # ── ELEVATION LINEAR PLOT (both polarisations, one figure) ────────────
        # x-axis: elevation = 90° − θ
        #   θ=0°   → elevation=+90° (directly above)
        #   θ=90°  → elevation=0°   (horizontal, head-on)
        #   θ=180° → elevation=−90° (directly below)
        if "EL_TE" in parsed or "EL_TM" in parsed:
            only_te_el = "EL_TE" in parsed and "EL_TM" not in parsed
            only_tm_el = "EL_TM" in parsed and "EL_TE" not in parsed
            d_te = parsed.get("EL_TE")
            d_tm = parsed.get("EL_TM")
            if d_te is None: d_te = d_tm
            if d_tm is None: d_tm = d_te
            el_te = 90.0 - d_te["theta_vals"]
            el_tm = 90.0 - d_tm["theta_vals"]
            idx_te = np.argsort(el_te)
            idx_tm = np.argsort(el_tm)
            fname = f"Linear_Elevation_Cut_0deg_{ts}.png"
            fpath = os.path.join(results_dir, fname)
            _plot_dual_linear(
                el_te[idx_te], d_te["sph"][idx_te], d_te["sth"][idx_te],
                el_tm[idx_tm], d_tm["sth"][idx_tm], d_tm["sph"][idx_tm],
                fpath,
                title    = "Monostatic RCS — Elevation Cut (nose direction)",
                subtitle = (f"φ = 0°    f = {freq:.1f} GHz    "
                            f"λ = {wl:.4f} m    "
                            f"0° = horizontal,  +90° = above,  −90° = below"),
                xlabel   = "Elevation Angle (deg)",
                only_te  = only_te_el,
                only_tm  = only_tm_el,
            )
            out["linear_el"] = fpath
            
        # ── ELEVATION POLAR PLOTS ─────────────────────────────────────────────
        # The aircraft is symmetric so the elevation cut at φ=0° (nose) is
        # mirrored to create a full-circle polar: right half = above-to-below
        # going clockwise, left half = mirror.
        # Polar angle mapping: el_polar = 90° − elevation
        #   elevation=+90° → polar=0°   (top = directly above)
        #   elevation= 0°  → polar=90°  (right = horizontal)
        #   elevation=−90° → polar=180° (bottom = directly below)
        # Mirror for left side: angle_left = 360° − angle_right

        def _elevation_to_polar_circle(el_deg, rcs_dBsm):
            """
            Map elevation [-90,+90] to a full 360° polar circle by mirroring.
            Returns (phi_full, rcs_full) suitable for _plot_polar().
            """
            idx       = np.argsort(el_deg)           # sort low to high
            el_sorted = el_deg[idx]
            rc_sorted = rcs_dBsm[idx]
            # right half: el → polar angle
            phi_right = 90.0 - el_sorted             # -90→180°, 0→90°, 90→0°
            # left half: mirror (360 - phi_right), reversed so it flows continuously
            phi_left  = 360.0 - phi_right[-2:0:-1]
            rc_left   = rc_sorted[-2:0:-1]
            phi_full  = np.concatenate([phi_right, phi_left])
            rcs_full  = np.concatenate([rc_sorted, rc_left])
            return phi_full, rcs_full

        # shared scale for the two elevation polar maps
        el_copol = []
        if "EL_TE" in parsed and len(parsed["EL_TE"]["sph"]):
            el_copol.append(parsed["EL_TE"]["sph"])
        if "EL_TM" in parsed and len(parsed["EL_TM"]["sth"]):
            el_copol.append(parsed["EL_TM"]["sth"])
        if el_copol:
            el_gmax = np.ceil(max(np.nanmax(a) for a in el_copol) / 10) * 10
            el_gmin = el_gmax - 60.0
        else:
            el_gmax, el_gmin = 20.0, -40.0

        el_spokes = {
            0:   "above\n+90°",  45: "+45°",  90:  "horiz\n0°",
            135: "−45°",        180: "below\n−90°",
            225: "−45°",        270: "horiz\n0°",  315: "+45°",
        }

        if "EL_TE" in parsed and len(parsed["EL_TE"]["theta_vals"]):
            d    = parsed["EL_TE"]
            el   = 90.0 - d["theta_vals"]
            ph_c, rc_c = _elevation_to_polar_circle(el, d["sph"])
            fname = f"Polar_TE-z_Elevation_Cut_0deg_{ts}.png"
            fpath = os.path.join(results_dir, fname)
            ph_xp_te, rx_xp_te = _elevation_to_polar_circle(el, d["sth"])
            _plot_polar(
                ph_c, rc_c, rx_xp_te, fpath,
                title    = "Polar RCS Map — TE-z polarisation",
                subtitle = (f"Elevation cut  φ = 0° (nose)    "
                            f"f = {freq:.1f} GHz    λ = {wl:.4f} m\n"
                            f"scale: {el_gmin:.0f} dBsm (centre) "
                            f"→ {el_gmax:.0f} dBsm (rim)"),
                color    = "steelblue",
                rcs_min  = el_gmin,
                rcs_max  = el_gmax,
                spoke_override = el_spokes,
            )
            out["polar_el_te"] = fpath

        if "EL_TM" in parsed and len(parsed["EL_TM"]["theta_vals"]):
            d    = parsed["EL_TM"]
            el   = 90.0 - d["theta_vals"]
            ph_c, rc_c = _elevation_to_polar_circle(el, d["sth"])
            fname = f"Polar_TM-z_Elevation_Cut_0deg_{ts}.png"
            fpath = os.path.join(results_dir, fname)
            ph_xp_tm, rx_xp_tm = _elevation_to_polar_circle(el, d["sph"])
            _plot_polar(
                ph_c, rc_c, rx_xp_tm, fpath,
                title    = "Polar RCS Map — TM-z polarisation",
                subtitle = (f"Elevation cut  φ = 0° (nose)    "
                            f"f = {freq:.1f} GHz    λ = {wl:.4f} m\n"
                            f"scale: {el_gmin:.0f} dBsm (centre) "
                            f"→ {el_gmax:.0f} dBsm (rim)"),
                color    = "crimson",
                rcs_min  = el_gmin,
                rcs_max  = el_gmax,
                spoke_override = el_spokes,
            )
            out["polar_el_tm"] = fpath
        # ── MEAN RCS TABLE ────────────────────────────────────────────────────
        # 6 rows in fixed order.  Each value = mean total RCS (dBsm).
        # Frontal sector rows (FR_TE, FR_TM) use the 2-D grid
        # az ±30° / el ±15° — the most important stealth metric.
        mean_rows = []
        for tag, label in [
            ("AZ_TE", "Azimuth Cut  θ=90°           TE-z"),
            ("AZ_TM", "Azimuth Cut  θ=90°           TM-z"),
            ("EL_TE", "Elevation Cut  φ=0° (nose)   TE-z"),
            ("EL_TM", "Elevation Cut  φ=0° (nose)   TM-z"),
            ("FR_TE", "Frontal ±30° az / ±15° el    TE-z"),
            ("FR_TM", "Frontal ±30° az / ±15° el    TM-z"),
        ]:
            if tag in parsed and len(parsed[tag]["sth"]):
                d = parsed[tag]
                mean_rows.append((label, _mean_total(d["sth"], d["sph"])))
            else:
                mean_rows.append((label, float("nan")))

        if any(np.isfinite(v) for _, v in mean_rows):
            fname = f"MeanRCS_Table_{ts}.png"
            fpath = os.path.join(results_dir, fname)
            _save_mean_table(mean_rows, fpath, freq, stl_filename)
            out["mean_table"] = fpath


        # ── clean up OpenRCS internal results folder ──────────────────────────
        # The solver writes temp files to ./results/ inside the OpenRCS dir.
        # We have already copied everything we need to results_dir above,
        # so the OpenRCS results folder can be wiped clean after each run.
        
        openrcs_results = os.path.join(_OPENRCS_DIR, "results")
        if os.path.isdir(openrcs_results):
            for f in os.listdir(openrcs_results):
                fpath_temp = os.path.join(openrcs_results, f)
                try:
                    if os.path.isfile(fpath_temp):
                        os.remove(fpath_temp)
                except Exception as e:
                    print(f"  Warning: could not delete temp file {f} — {e}")

        # ── summary ───────────────────────────────────────────────────────────
        print(f"\n  All results saved to: {results_dir}")
        for k, v in out.items():
            if v and k != "results_dir":
                print(f"    {k:<18}: {os.path.basename(v)}")

    finally:
        os.chdir(original_cwd)

    print("\n✅ OpenRCS pipeline complete.\n")
    return out


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    run_openrcs_pipeline(stl_path=os.path.join(_STL_DIR, "aircraft.stl"))
