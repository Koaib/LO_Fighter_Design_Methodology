# -*- coding: utf-8 -*-
"""
Created on Fri Jun 19 23:55:44 2026

@author: KK

PEC NASA almond RCS validation — mirrors sphere_validation.py / flat_plate_validation.py:
  1. Load NASA_Almond_template.vsp3, set Length in metres, export STLs at
     different CFDMesh densities
  2. Run each STL through OpenRCS PO solver
     - Azimuth cut:   theta=90 deg, phi=0->360
     - Elevation cut: phi=0  deg, theta=0->180
  3. Plot solver results for convergence assessment
     (no closed-form analytical formula — validation against
      Woo et al. 1993 experimental data loaded from digitised .csv)

Geometry:
    NASA almond (Woo, Wang, Schuh & Sanders, IEEE AP Mag, Feb 1993)
    Standard benchmark length d = 9.936 inches = 0.252374 m
    Template parm "Length" is set in METRES (same convention as flat plate script)
    so STL vertices come out in metres and match OpenRCS freq in Hz.

Benchmark frequency: 9.92 GHz  (primary Woo et al. frequency, d/lambda ~ 8.4)

Folder layout (next to this script):
    stl/      generated almond STLs
    vsp3/     generated VSP3 model files
    results/  OpenRCS .dat output files
    plots/    convergence figures
"""

import sys, os, shutil, importlib
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

# ============================================================
# USER INPUTS
# ============================================================
freq = 9.92e9      # Hz  — primary Woo et al. benchmark frequency

# Standard almond length.  Template was built at 9.936 inches;
# we set the VSP parm in metres so STL units match OpenRCS (Hz).
D_INCHES  = 9.936
D_METRES  = D_INCHES * 0.0254          # 0.252374 m

mesh_factors = [1.0, 0.5, 1/3, 1/4]
mesh_labels  = ["lambda", "lambda_2", "lambda_3", "lambda_4"]

OPENRCS_DIR   = "../../OpenRCS/open-rcs"
TEMPLATE_PATH = os.path.abspath("NASA_Almond_template.vsp3")

# Woo et al. (1993) digitised experimental data files (optional).
# If present, overlaid on the convergence plots for direct comparison.
# Expected columns: angle_deg, RCS_dBsm  (space or comma separated, no header)
WOO_AZIMUTH_CSV   = "woo1993_azimuth.csv"    # phi cut, theta=90
WOO_ELEVATION_CSV = "woo1993_elevation.csv"   # theta cut, phi=0

# ============================================================
# Derived quantities
# ============================================================
c  = 3e8
wl = c / freq
k  = 2 * np.pi / wl

print("=" * 55)
print(f"Frequency         = {freq/1e9:.3f} GHz")
print(f"Wavelength lambda = {wl*1000:.3f} mm")
print(f"Almond length d   = {D_METRES*1000:.2f} mm  ({D_INCHES} in)")
print(f"d / lambda        = {D_METRES/wl:.2f}")
print(f"Max width         = {2*0.193333*D_METRES*1000:.2f} mm")
print(f"Max thickness     = {2*0.064444*D_METRES*1000:.2f} mm")
print("=" * 55)

# ============================================================
# Output folders
# ============================================================
for folder in ("stl", "vsp3", "results", "plots"):
    os.makedirs(folder, exist_ok=True)

# ============================================================
# Helper — load optional Woo digitised CSV
# ============================================================
def load_woo_csv(path):
    """Return (angles_deg, rcs_dBsm) arrays, or (None, None) if file absent."""
    if not os.path.exists(path):
        return None, None
    try:
        data = np.loadtxt(path, delimiter=None, comments="#")
        return data[:, 0], data[:, 1]
    except Exception as e:
        print(f"  WARNING: could not load {path}: {e}")
        return None, None

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

if HAVE_VSP:
    if not os.path.exists(TEMPLATE_PATH):
        print(f"ERROR: template not found at {TEMPLATE_PATH}")
        HAVE_VSP = False

if HAVE_VSP:
    for factor, label in zip(mesh_factors, mesh_labels):
        target_edge = factor * wl          # metres

        # --- load template fresh each iteration ---
        vsp.VSPRenew()
        vsp.ReadVSPFile(TEMPLATE_PATH)

        geom_id = vsp.FindGeoms()[0]
        parm_by_name = {vsp.GetParmName(pid): pid
                        for pid in vsp.GetGeomParmIDs(geom_id)}

        def pset(name, val):
            pid = parm_by_name.get(name)
            if pid is None:
                raise KeyError(f"Parm '{name}' not found. "
                               f"Available: {sorted(parm_by_name.keys())}")
            vsp.SetParmVal(pid, val)

        # Set Length in metres — same convention as flat plate script.
        # The Custom Geom script uses Length everywhere as 'd', so all
        # vertex positions come out in metres, matching OpenRCS freq in Hz.
        pset("Length", D_METRES)
        vsp.Update()

        # --- CFDMesh: uniform target edge length ---
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
                                vsp3_path=vsp3_path)
        print(f"{label}: edge={target_edge*1000:.2f}mm, "
              f"tris={tri_count} -> {stl_path}")

# ============================================================
# STEP 2 — Run OpenRCS PO solver — azimuth + elevation cuts
# ============================================================
importlib.invalidate_caches()
sys.path_importer_cache.clear()
sys.path.insert(0, OPENRCS_DIR)

try:
    from rcs_functions import extractCoordinatesData, stl_converter
    from rcs_monostatic import rcs_monostatic
    HAVE_OPENRCS = True
except ImportError as e:
    HAVE_OPENRCS = False
    print(f"\nWARNING: could not import OpenRCS ({e}). Skipping solver.")

if HAVE_OPENRCS:
    for factor, label in zip(mesh_factors, mesh_labels):
        stl_path = mesh_info[label]["stl_path"]

        if not os.path.exists(stl_path):
            print(f"{label}: STL not found, skipping")
            continue

        stl_converter(stl_path)

        facets_file = os.path.join(OPENRCS_DIR, "facets.txt")
        coords_file = os.path.join(OPENRCS_DIR, "coordinates.txt")
        print(f"{label}: facets={os.path.getsize(facets_file)}B, "
              f"coords={os.path.getsize(coords_file)}B")

        Rs         = 0
        coord_list = extractCoordinatesData(Rs)

        # ── Azimuth cut: theta=90, phi=0->360 ──────────────────
        params_az = [
            f"almond_{label}_az",
            freq,
            0, 0,
            1,           # TE-z (PO: polarisation-independent per Barile 1984)
            Rs,
            0, 360, 1,   # phi
            90, 90, 1,   # theta fixed at 90
            None
        ]
        _, _, file_az = rcs_monostatic(params_az, coord_list)
        print(f"  azimuth done -> {file_az}")
        if file_az and os.path.exists(file_az):
            dst = f"results/almond_{label}_az.dat"
            shutil.move(file_az, dst)
            mesh_info[label]["dat_az"] = dst

        # ── Elevation cut: phi=0, theta=0->180 ─────────────────
        # stl_converter already ran; coord_list is still valid
        params_el = [
            f"almond_{label}_el",
            freq,
            0, 0,
            1,           # TE-z
            Rs,
            0, 0, 1,     # phi fixed at 0
            0, 180, 1,   # theta
            None
        ]
        _, _, file_el = rcs_monostatic(params_el, coord_list)
        print(f"  elevation done -> {file_el}")
        if file_el and os.path.exists(file_el):
            dst = f"results/almond_{label}_el.dat"
            shutil.move(file_el, dst)
            mesh_info[label]["dat_el"] = dst

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
        "phi":   _extract("Phi (deg):"),
        "theta": _extract("Theta (deg):"),
        "sth":   _extract("RCS Theta (dBsm):"),
        "sph":   _extract("RCS Phi (dBsm):"),
    }

# ============================================================
# STEP 4 — Convergence plots
# ============================================================
colors = ['red', 'green', 'blue', 'purple', 'orange', 'brown']
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# ── Plot A: Azimuth cut (phi 0->360, theta=90) ─────────────
fig, ax = plt.subplots(figsize=(10, 5))

woo_phi, woo_phi_rcs = load_woo_csv(WOO_AZIMUTH_CSV)
if woo_phi is not None:
    ax.plot(woo_phi, woo_phi_rcs, 'k-', lw=2.5,
            label='Woo et al. 1993 (experimental)')

for (factor, label), color in zip(zip(mesh_factors, mesh_labels), colors):
    dat = mesh_info[label].get("dat_az",
                               f"results/almond_{label}_az.dat")
    if not os.path.exists(dat):
        print(f"{label}: no azimuth .dat, skipping")
        continue
    d = parse_dat(dat)
    if len(d["phi"]) == 0:
        continue
    idx = np.argsort(d["phi"])
    edge_mm = mesh_info[label]["edge_mm"]
    n_tri   = mesh_info[label]["n_tri"]
    ax.plot(d["phi"][idx], d["sph"][idx],
            color=color, lw=1.2,
            label=f'λ/{round(1/factor):.0f}  '
                  f'(edge={edge_mm:.1f}mm, tris={n_tri})')

ax.set_xlabel('Azimuth angle phi (deg)')
ax.set_ylabel('RCS (dBsm)')
ax.set_title(f'NASA Almond RCS — Azimuth Cut (theta=90°)\n'
             f'd={D_METRES*100:.1f}cm, f={freq/1e9:.2f}GHz, '
             f'd/λ={D_METRES/wl:.1f}')
ax.set_xlim(0, 360)
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(f"plots/almond_azimuth_{ts}.png", dpi=150)
plt.close(fig)
print(f"Saved plots/almond_azimuth_{ts}.png")

# ── Plot B: Elevation cut (theta 0->180, phi=0) ────────────
fig, ax = plt.subplots(figsize=(10, 5))

woo_el, woo_el_rcs = load_woo_csv(WOO_ELEVATION_CSV)
if woo_el is not None:
    ax.plot(woo_el, woo_el_rcs, 'k-', lw=2.5,
            label='Woo et al. 1993 (experimental)')

for (factor, label), color in zip(zip(mesh_factors, mesh_labels), colors):
    dat = mesh_info[label].get("dat_el",
                               f"results/almond_{label}_el.dat")
    if not os.path.exists(dat):
        print(f"{label}: no elevation .dat, skipping")
        continue
    d = parse_dat(dat)
    if len(d["theta"]) == 0:
        continue
    idx = np.argsort(d["theta"])
    edge_mm = mesh_info[label]["edge_mm"]
    n_tri   = mesh_info[label]["n_tri"]
    ax.plot(d["theta"][idx], d["sth"][idx],
            color=color, lw=1.2,
            label=f'λ/{round(1/factor):.0f}  '
                  f'(edge={edge_mm:.1f}mm, tris={n_tri})')

ax.set_xlabel('Elevation angle theta (deg)')
ax.set_ylabel('RCS (dBsm)')
ax.set_title(f'NASA Almond RCS — Elevation Cut (phi=0°)\n'
             f'd={D_METRES*100:.1f}cm, f={freq/1e9:.2f}GHz, '
             f'd/λ={D_METRES/wl:.1f}')
ax.set_xlim(0, 180)
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(f"plots/almond_elevation_{ts}.png", dpi=150)
plt.close(fig)
print(f"Saved plots/almond_elevation_{ts}.png")

print("\nDone.")