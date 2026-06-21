

# -*- coding: utf-8 -*-
"""
nasa_almond_validation.py

Two output figures:

  Figure 1 — All reference data on one plot:
    - Woo et al. 1993 HH + VV  (measured, high-freq range 8-16 GHz)
    - HFSS IE 9.92 GHz HH + VV (full-wave reference)
    - MathWorks/MATLAB PO       (7 GHz, polarization-independent)

  Figure 2 — OpenRCS PO convergence at 7 GHz vs MathWorks PO reference:
    - MathWorks PO (light green, 7 GHz) as the reference line
    - OpenRCS PO mesh convergence family 
    
OpenRCS uses pure Physical Optics. Per Barile (1984), monostatic PO RCS
is polarization-independent — one solver run per mesh is sufficient.

Reference CSVs (place in same folder as this script):
    H-H_polarization_Woo_High.csv       (Woo 1993, 8-16 GHz, HH)
    V-V_polarization_Woo_High.csv       (Woo 1993, 8-16 GHz, VV)
    H-H_polarization_HFSS_9.92_GHz.csv (HFSS IE, 9.92 GHz, HH)
    V-V_polarization_HFSS_9.92_GHz.csv (HFSS IE, 9.92 GHz, VV)
    NASA_Almond_PO.csv                  (MathWorks MATLAB PO, 7 GHz)
    Format: angle_deg, RCS_dBsm  (no header, comma-separated)
"""

import sys, os, shutil, importlib
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

# ============================================================
# USER INPUTS
# ============================================================
# Plot 2 solver frequency — match MathWorks PO reference at 7 GHz
freq = 7e9         # Hz  (change to 9.92e9 to match HFSS instead)

D_INCHES = 9.936
D_METRES = D_INCHES * 0.0254          # 0.252374 m

# lambda/2 excluded — too few tris, curves not informative
mesh_factors = [1.0, 1/3, 1/4, 1/5, 1/6, 1/8]
mesh_labels  = ["lambda", "lambda_3", "lambda_4",
                "lambda_5", "lambda_6", "lambda_8"]

OPENRCS_DIR   = "../../OpenRCS/open-rcs"
TEMPLATE_PATH = os.path.abspath("NASA_Almond_template.vsp3")
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))

# Reference CSVs
REF_CSV = {
    # Woo 1993 measured — high-freq range defined as 8-16 GHz in the paper
    "HH_Woo":  "H-H_polarization_Woo_High.csv",
    "VV_Woo":  "V-V_polarization_Woo_High.csv",
    # HFSS Integral Equation solver at exactly 9.92 GHz
    "HH_HFSS": "H-H_polarization_HFSS_9.92_GHz.csv",
    "VV_HFSS": "V-V_polarization_HFSS_9.92_GHz.csv",
    # MathWorks MATLAB Antenna Toolbox PO solver at 7 GHz
    "PO_MATLAB": "NASA_Almond_PO.csv",
}
# Make all paths absolute relative to script location
REF_CSV = {k: os.path.join(SCRIPT_DIR, v) for k, v in REF_CSV.items()}

# ============================================================
# Derived quantities
# ============================================================
c  = 3e8
wl = c / freq
k  = 2 * np.pi / wl

print("=" * 55)
print(f"Solver frequency  = {freq/1e9:.3f} GHz")
print(f"Wavelength lambda = {wl*1000:.3f} mm")
print(f"Almond length d   = {D_METRES*1000:.2f} mm  ({D_INCHES} in)")
print(f"d / lambda        = {D_METRES/wl:.2f}")
print("=" * 55)
for factor, label in zip(mesh_factors, mesh_labels):
    print(f"  {label:12s}: edge = {factor*wl*1000:.3f} mm")
print("=" * 55)

# ============================================================
# Output folders
# ============================================================
for folder in ("stl", "vsp3", "results", "plots"):
    os.makedirs(folder, exist_ok=True)

# ============================================================
# Helper — load and clean WebPlotDigitizer CSV
# ============================================================
def load_ref_csv(path, angle_min=0.0, angle_max=180.0, bin_deg=0.5):
    if not os.path.exists(path):
        print(f"  INFO: not found: {os.path.basename(path)}")
        return None, None
    try:
        data   = np.loadtxt(path, delimiter=',')
        angles = np.clip(data[:, 0], angle_min, angle_max)
        rcs    = data[:, 1]
        idx    = np.argsort(angles)
        angles, rcs = angles[idx], rcs[idx]
        bins    = np.arange(angle_min, angle_max + bin_deg, bin_deg)
        centres = 0.5 * (bins[:-1] + bins[1:])
        avg_rcs = np.full(len(centres), np.nan)
        for j, (lo, hi) in enumerate(zip(bins[:-1], bins[1:])):
            m = (angles >= lo) & (angles < hi)
            if m.any():
                avg_rcs[j] = rcs[m].mean()
        valid = ~np.isnan(avg_rcs)
        return centres[valid], avg_rcs[valid]
    except Exception as e:
        print(f"  WARNING: could not load {os.path.basename(path)}: {e}")
        return None, None

# Pre-load all reference data
print("\nLoading reference data...")
ref_data = {}
for key, fpath in REF_CSV.items():
    a, r = load_ref_csv(fpath)
    ref_data[key] = (a, r)
    if a is not None:
        print(f"  {key:12s}: {len(a)} pts, "
              f"angle [{a.min():.1f}, {a.max():.1f}], "
              f"RCS [{r.min():.1f}, {r.max():.1f}] dBsm")

# ============================================================
# STEP 1 — Generate almond STLs via OpenVSP
# ============================================================
try:
    import openvsp as vsp
    HAVE_VSP = True
except ImportError:
    HAVE_VSP = False
    print("\nWARNING: openvsp not importable — skipping STL generation.")

mesh_info = {}

if HAVE_VSP and not os.path.exists(TEMPLATE_PATH):
    print(f"ERROR: template not found at {TEMPLATE_PATH}")
    HAVE_VSP = False

if HAVE_VSP:
    print("\nGenerating STLs...")
    for factor, label in zip(mesh_factors, mesh_labels):
        target_edge = factor * wl

        vsp.VSPRenew()
        vsp.ReadVSPFile(TEMPLATE_PATH)

        geom_id      = vsp.FindGeoms()[0]
        parm_by_name = {vsp.GetParmName(pid): pid
                        for pid in vsp.GetGeomParmIDs(geom_id)}

        def pset(name, val):
            pid = parm_by_name.get(name)
            if pid is None:
                raise KeyError(f"Parm '{name}' not found. "
                               f"Available: {sorted(parm_by_name.keys())}")
            vsp.SetParmVal(pid, val)

        pset("Length", D_METRES)
        vsp.Update()

        vsp.SetCFDMeshVal(vsp.CFD_MAX_EDGE_LEN,    target_edge)
        vsp.SetCFDMeshVal(vsp.CFD_MIN_EDGE_LEN,    target_edge)
        vsp.SetCFDMeshVal(vsp.CFD_GROWTH_RATIO,    10.0)
        vsp.SetCFDMeshVal(vsp.CFD_MAX_GAP,         target_edge)
        vsp.SetCFDMeshVal(vsp.CFD_NUM_CIRCLE_SEGS, 0.00001)
        vsp.DeleteAllCFDSources()

        stl_path  = os.path.abspath(f"stl/almond_{label}.stl")
        vsp3_path = os.path.abspath(f"vsp3/almond_{label}.vsp3")

        vsp.SetComputationFileName(vsp.CFD_STL_TYPE, stl_path)
        vsp.ComputeCFDMesh(vsp.SET_ALL, vsp.SET_NONE, vsp.CFD_STL_TYPE)

        vsp.SetVSP3FileName(vsp3_path)
        vsp.WriteVSPFile(vsp3_path, vsp.SET_ALL)

        tri_count = 0
        if os.path.exists(stl_path):
            with open(stl_path) as fh:
                tri_count = sum(1 for ln in fh
                                if ln.strip().startswith("facet normal"))

        mesh_info[label] = dict(edge_mm=target_edge * 1000,
                                n_tri=tri_count,
                                stl_path=stl_path,
                                vsp3_path=vsp3_path,
                                dat_path=None)
        print(f"  {label}: edge={target_edge*1000:.3f}mm, tris={tri_count}")

# ============================================================
# STEP 2 — Run OpenRCS PO solver
#
# Pure PO monostatic RCS is polarization-independent (Barile 1984).
# One TE-z run per mesh — result is the same for TM-z.
# CWD switched to OPENRCS_DIR to fix stale-file bug.
# ============================================================
importlib.invalidate_caches()
sys.path_importer_cache.clear()
sys.path.insert(0, os.path.abspath(OPENRCS_DIR))

try:
    from rcs_functions import extractCoordinatesData, stl_converter
    from rcs_monostatic import rcs_monostatic
    HAVE_OPENRCS = True
except ImportError as e:
    HAVE_OPENRCS = False
    print(f"\nWARNING: could not import OpenRCS ({e}). Skipping solver.")

if HAVE_OPENRCS:
    print("\nRunning OpenRCS solver...")
    original_cwd = os.getcwd()
    os.chdir(os.path.abspath(OPENRCS_DIR))

    for factor, label in zip(mesh_factors, mesh_labels):
        stl_path = mesh_info[label]["stl_path"]

        if not os.path.exists(stl_path):
            print(f"  {label}: STL not found, skipping")
            continue

        stl_converter(stl_path)

        f_size = os.path.getsize("facets.txt")
        c_size = os.path.getsize("coordinates.txt")
        print(f"  {label}: facets={f_size}B, coords={c_size}B", end="")

        Rs         = 0
        coord_list = extractCoordinatesData(Rs)

        params = [
            f"almond_{label}",
            freq,          # 7 GHz — matches MathWorks PO reference
            0, 0,
            1,             # TE-z (pol-independent under pure PO)
            Rs,
            0, 180, 1,     # phi 0->180, step 1 deg
            90, 90, 1,     # theta fixed at 90 (elevation = 0)
            None
        ]
        plot_name, fig_name, file_name = rcs_monostatic(params, coord_list)
        print(f"  {label}: solver done -> {file_name}")

        if file_name and os.path.exists(file_name):
            dst = os.path.join(original_cwd, "results", f"almond_{label}.dat")
            shutil.move(file_name, dst)
            mesh_info[label]["dat_path"] = dst
            print(f"    .dat -> {os.path.basename(dst)}")
        else:
            print(f"    WARNING: .dat not found at '{file_name}'")

        if plot_name and os.path.exists(plot_name):
            ext = os.path.splitext(plot_name)[1]
            dst_plot = os.path.join(original_cwd, "results",
                                    f"almond_{label}_plot{ext}")
            shutil.move(plot_name, dst_plot)
            print(f"    plot -> {os.path.basename(dst_plot)}")

        if fig_name and os.path.exists(fig_name):
            ext = os.path.splitext(fig_name)[1]
            dst_fig = os.path.join(original_cwd, "results",
                                   f"almond_{label}_fig{ext}")
            shutil.move(fig_name, dst_fig)
            print(f"    fig  -> {os.path.basename(dst_fig)}")

    os.chdir(original_cwd)
    
# ============================================================
# STEP 3 — Parse .dat files
# ============================================================
def parse_dat(dat_path):
    HEADERS = ["Theta (deg):", "RCS Theta (dBsm):",
               "Phi (deg):",   "RCS Phi (dBsm):"]
    with open(dat_path) as fh:
        content = fh.read()

    def _extract(header):
        idx = content.find(header)
        if idx == -1:
            return np.array([])
        start = idx + len(header)
        stop  = len(content)
        for other in HEADERS:
            if other == header:
                continue
            oi = content.find(other, start)
            if oi != -1 and oi < stop:
                stop = oi
        vals = []
        for line in content[start:stop].splitlines():
            s = line.strip().replace("[", "").replace("]", "")
            if not s:
                continue
            try:
                vals.extend(float(x) for x in s.split())
            except ValueError:
                continue
        return np.array(vals)

    return {
        "phi": _extract("Phi (deg):"),
        "sth": _extract("RCS Theta (dBsm):"),
        "sph": _extract("RCS Phi (dBsm):"),
    }

# ============================================================
# STEP 4 — Plots
# ============================================================
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# Convergence plot colors
conv_colors = ['tab:red', 'tab:green', 'tab:blue',
               'tab:purple', 'tab:brown', 'tab:pink']

# ── Figure 1: All reference data ────────────────────────────
# Woo HH + VV (8-16 GHz measured)
# HFSS HH + VV (9.92 GHz IE)
# MathWorks PO (7 GHz, pol-independent)
print("\nGenerating plots...")
fig1, ax1 = plt.subplots(figsize=(12, 5))

ref1_cfg = [
    ("HH_Woo",   "black",      "-",   2.0,
     "Woo et al. 1993 — HH  (measured, 8–16 GHz)"),
    ("VV_Woo",   "black",      "--",  2.0,
     "Woo et al. 1993 — VV  (measured, 8–16 GHz)"),
    ("HH_HFSS",  "tab:blue",   "-",   1.5,
     "HFSS IE — HH  (9.92 GHz, full-wave)"),
    ("VV_HFSS",  "tab:orange", "-",   1.5,
     "HFSS IE — VV  (9.92 GHz, full-wave)"),
    ("PO_MATLAB","limegreen",  "-",   2.0,
     "MATLAB Antenna Toolbox PO  (7 GHz, pol-independent)"),
]

for key, color, ls, lw, lbl in ref1_cfg:
    a, r = ref_data[key]
    if a is not None:
        ax1.plot(a, r, color=color, ls=ls, lw=lw, label=lbl)
    else:
        print(f"  Figure 1: skipping {key} (file not found)")

ax1.set_xlabel('Azimuth angle (deg)   [0° = nose-on, 90° = broadside]',
               fontsize=11)
ax1.set_ylabel('RCS (dBsm)', fontsize=11)
ax1.set_title(
    'NASA Almond — All Reference Data\n'
    'Woo 1993: measured (8–16 GHz) | '
    'HFSS: full-wave IE (9.92 GHz) | '
    'MATLAB PO: pure PO (7 GHz)\n'
    'Full-wave HH ≠ VV due to edge diffraction & creeping waves; '
    'pure PO is polarization-independent (Barile 1984)',
    fontsize=9)
ax1.set_xlim(0, 180)
ax1.legend(fontsize=8, loc='upper left')
ax1.grid(True, alpha=0.3)
plt.tight_layout()
out1 = os.path.join(SCRIPT_DIR, "plots", f"almond_all_reference_{ts}.png")
plt.savefig(out1, dpi=150)
plt.close(fig1)
print(f"  Saved {os.path.basename(out1)}")

# ── Figure 2: OpenRCS convergence vs MathWorks PO ───────────
# Reference: MathWorks PO at 7 GHz (light green)
# OpenRCS also at 7 GHz — direct apples-to-apples comparison
fig2, ax2 = plt.subplots(figsize=(12, 5))

po_a, po_r = ref_data["PO_MATLAB"]
if po_r is not None:
    ax2.plot(po_a, po_r, color='limegreen', lw=2.5, ls='-', zorder=6,
             label='MATLAB Antenna Toolbox PO  (7 GHz) — reference')
else:
    print("  Figure 2: MathWorks PO CSV not found — ")

for (factor, label), color in zip(zip(mesh_factors, mesh_labels), conv_colors):
    dat_path = mesh_info.get(label, {}).get("dat_path")
    if dat_path is None:
        dat_path = os.path.join("results", f"almond_{label}.dat")
    if not os.path.exists(dat_path):
        print(f"  {label}: no .dat file, skipping")
        continue

    d = parse_dat(dat_path)
    if len(d["phi"]) == 0:
        continue

    idx     = np.argsort(d["phi"])
    edge_mm = mesh_info[label]["edge_mm"]
    n_tri   = mesh_info[label]["n_tri"]
    frac    = f"λ/{round(1/factor)}" if factor < 1 else "λ"

    ax2.plot(d["phi"][idx], d["sph"][idx],
             color=color, lw=1.3,
             label=f'OpenRCS PO {frac}  '
                   f'(edge={edge_mm:.2f}mm, tris={n_tri})')

ax2.set_xlabel('Azimuth angle (deg)   [0° = nose-on, 90° = broadside]',
               fontsize=11)
ax2.set_ylabel('RCS (dBsm)', fontsize=11)
ax2.set_title(
    f'NASA Almond — OpenRCS PO Mesh Convergence  (f = {freq/1e9:.1f} GHz)\n'
    f'd={D_METRES*100:.2f} cm, d/λ={D_METRES/wl:.1f}  |  '
    f'Reference: MATLAB Antenna Toolbox PO (same frequency)\n'
    f'Pure PO is polarization-independent (Barile 1984) — ',
    fontsize=9)
ax2.set_xlim(0, 180)
ax2.legend(fontsize=8, ncol=2, loc='upper left')
ax2.grid(True, alpha=0.3)
plt.tight_layout()
out2 = os.path.join(SCRIPT_DIR, "plots", f"almond_convergence_7GHz_{ts}.png")
plt.savefig(out2, dpi=150)
plt.close(fig2)
print(f"  Saved {os.path.basename(out2)}")

print("\nDone.")