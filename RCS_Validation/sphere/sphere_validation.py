# -*- coding: utf-8 -*-
"""
Created on Mon Jun 15 15:59:59 2026

@author: KK

sphere_validation.py

Single-file PEC sphere RCS validation:
  1. Analytical PO RCS  (sigma = pi*a^2, constant for all angles)
  2. Generate sphere STL meshes at different densities via OpenVSP
     (lambda, lambda/2, lambda/3, lambda/5, lambda/9 edge length targets)
  3. Run each mesh through the OpenRCS PO solver (azimuth cut, theta=90)
  4. Overlay analytical + all mesh results on one linear plot

Everything is driven by `a` (sphere radius, m) and `freq` (Hz) at the top —
change these and the whole pipeline recalculates.

Folder layout created next to this script:
    stl/      generated sphere STLs
    results/  OpenRCS .dat output files
    plots/    final comparison + analytical plots
"""

import sys, os, shutil
import numpy as np
import matplotlib.pyplot as plt

# ============================================================
# USER INPUTS — change these and everything else updates
# ============================================================
a    = 0.1        # sphere radius (m)
freq = 12e9       # frequency (Hz)

# mesh densities to test, as edge_length = factor * lambda
mesh_factors = [2.0, 1.5, 1.0, 0.5, 1/3, 1/4, 1/5, 1/6]
mesh_labels  = ["2lambda", "1p5lambda", "lambda",
                "lambda_2", "lambda_3", "lambda_4", "lambda_5", "lambda_6"]

# path to OpenRCS engine (adjust to your project layout)
OPENRCS_DIR = "../../OpenRCS/open-rcs"

# ============================================================
# Derived quantities
# ============================================================
c   = 3e8
wl  = c / freq
k   = 2 * np.pi / wl
ka  = k * a
circumference = 2 * np.pi * a

print("=" * 50)
print(f"Sphere radius a   = {a} m")
print(f"Frequency         = {freq/1e9:.2f} GHz")
print(f"Wavelength lambda = {wl*1000:.3f} mm")
print(f"k (= 2*pi/lambda) = {k:.3f} rad/m")
print(f"ka                = {ka:.3f}")
if ka > 10:
    print("ka >> 1 -> optical region, PO formula valid")
else:
    print("WARNING: ka not >> 1, PO may not be accurate for this radius/freq")
print("=" * 50)

# ============================================================
# Output folders
# ============================================================
for d in ("stl", "vsp3", "results", "plots"):
    os.makedirs(d, exist_ok=True)

# ============================================================
# STEP 1 — Analytical PO solution
# ============================================================
sigma_lin   = np.pi * a**2
sigma_dBsm  = 10 * np.log10(sigma_lin)
print(f"\nAnalytical PO RCS: sigma = pi*a^2 = {sigma_lin:.6f} m^2 "
      f"= {sigma_dBsm:.2f} dBsm  (constant over all angles)")

phi_analytical = np.linspace(0, 360, 361)
rcs_analytical = np.full_like(phi_analytical, sigma_dBsm)

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(phi_analytical, rcs_analytical, 'k-', lw=2,
        label='Analytical (PO)')
ax.set_xlabel('Azimuth angle phi (deg)')
ax.set_ylabel('RCS (dBsm)')
ax.set_xlim(0, 360)
ax.set_title(f"Sphere RCS — Analytical PO\n"
              f"a={a} m, f={freq/1e9:.1f} GHz, ka={ka:.1f}\n"
              f"sigma = {sigma_dBsm:.2f} dBsm")
ax.legend(loc='best')
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("plots/analytical_sphere.png", dpi=150)
plt.close(fig)
print("Saved plots/analytical_sphere.png")

# ============================================================
# STEP 2 — Generate sphere STLs at each mesh density (OpenVSP)
# ============================================================
try:
    import openvsp as vsp
    HAVE_VSP = True
except ImportError:
    HAVE_VSP = False
    print("\nWARNING: openvsp not importable in this environment — "
          "skipping STL generation. Run this script from your project "
          ".venv where OpenVSP python bindings are installed.")

mesh_info = {}  # label -> dict(divisions, edge_mm, stl_path)

if HAVE_VSP:
    for factor, label in zip(mesh_factors, mesh_labels):
        target_edge = factor * wl

        vsp.VSPRenew()
        eid = vsp.AddGeom("ELLIPSOID")
        vsp.SetParmVal(eid, "A_Radius", "Design", a)
        vsp.SetParmVal(eid, "B_Radius", "Design", a)
        vsp.SetParmVal(eid, "C_Radius", "Design", a)
        vsp.Update()

        # CFDMesh uniform edge length = factor * lambda
        vsp.SetCFDMeshVal(vsp.CFD_MAX_EDGE_LEN, target_edge)
        vsp.SetCFDMeshVal(vsp.CFD_MIN_EDGE_LEN, target_edge)
        vsp.SetCFDMeshVal(vsp.CFD_GROWTH_RATIO, 10.0)
        vsp.SetCFDMeshVal(vsp.CFD_MAX_GAP,      target_edge)
        vsp.SetCFDMeshVal(vsp.CFD_NUM_CIRCLE_SEGS, 0.00001)
        vsp.DeleteAllCFDSources()

        stl_path  = os.path.abspath(f"stl/sphere_{label}.stl")
        vsp3_path = os.path.abspath(f"vsp3/sphere_{label}.vsp3")

        vsp.SetComputationFileName(vsp.CFD_STL_TYPE, stl_path)
        vsp.ComputeCFDMesh(vsp.SET_ALL, vsp.SET_NONE, vsp.CFD_STL_TYPE)

        vsp.SetVSP3FileName(vsp3_path)
        vsp.WriteVSPFile(vsp3_path, vsp.SET_ALL)

        tri_count = 0
        if os.path.exists(stl_path):
            with open(stl_path) as fh:
                tri_count = sum(1 for ln in fh
                                if ln.strip().startswith("facet normal"))

        mesh_info[label] = dict(divisions=tri_count,
                                edge_mm=target_edge * 1000,
                                stl_path=stl_path,
                                vsp3_path=vsp3_path)
        print(f"{label}: edge={target_edge*1000:.1f}mm, "
              f"tris={tri_count} -> {stl_path}")
        
# ============================================================
# STEP 3 — Run OpenRCS PO solver on each mesh
# ============================================================
sys.path.insert(0, OPENRCS_DIR)

try:
    from rcs_functions import extractCoordinatesData, stl_converter
    from rcs_monostatic import rcs_monostatic
    HAVE_OPENRCS = True
except ImportError as e:
    HAVE_OPENRCS = False
    print(f"\nWARNING: could not import OpenRCS modules ({e}) — "
          f"check OPENRCS_DIR='{OPENRCS_DIR}'. Skipping solver runs.")

if HAVE_OPENRCS:
    for factor, label in zip(mesh_factors, mesh_labels):
        info = mesh_info[label]
        stl_path = info["stl_path"]

        if not os.path.exists(stl_path):
            print(f"{label}: STL not found at {stl_path}, skipping")
            continue

        # STL -> coordinates.txt + facets.txt (written to CWD)
        stl_converter(stl_path)

        Rs = 0  # PEC
        coord_list = extractCoordinatesData(Rs)

        # azimuth cut: theta fixed at 90 deg, phi 0->360
        # ipol: 0 = TM-z, 1 = TE-z  (sphere is polarization-independent
        #       per Barile 1984, so either is fine)
        params = [
            f"sphere_{label}",    # input_model
            freq,                  # freq
            0,                     # corr
            0,                     # delstd
            1,                     # ipol -> TE-z
            Rs,                    # rs
            0, 360, 1,             # pstart, pstop, delp
            90, 90, 1,             # tstart, tstop, delt
            None                   # matrlpath
        ]

        plot_name, fig_name, file_name = rcs_monostatic(params, coord_list)
        print(f"{label}: solver done -> {file_name}")

        if file_name and os.path.exists(file_name):
            dst = f"results/sphere_{label}.dat"
            shutil.move(file_name, dst)
            mesh_info[label]["dat_path"] = dst
            print(f"  moved -> {dst}")
        else:
            print(f"  WARNING: result file not found at '{file_name}'")

# ============================================================
# STEP 4 — Parse .dat files and overlay comparison linear plot
# ============================================================
def parse_dat(dat_path):
    """Parse an OpenRCS .dat file into phi_vals/theta_vals/sth/sph arrays."""
    HEADERS = ["Theta (deg):", "RCS Theta (dBsm):",
               "Phi (deg):", "RCS Phi (dBsm):"]

    with open(dat_path) as fh:
        content = fh.read()

    def _extract(header):
        idx = content.find(header)
        if idx == -1:
            return np.array([])
        start = idx + len(header)
        stop = len(content)
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
        "phi_vals":   _extract("Phi (deg):"),
        "theta_vals": _extract("Theta (deg):"),
        "sth":        _extract("RCS Theta (dBsm):"),
        "sph":        _extract("RCS Phi (dBsm):"),
    }


fig, ax = plt.subplots(figsize=(10, 5))

# analytical reference (constant)
ax.plot(phi_analytical, rcs_analytical, 'k-', lw=2.5,
        label=f'Analytical ({sigma_dBsm:.2f} dBsm)')

colors = ['red', 'orange', 'green', 'blue', 'purple', 'brown', 'cyan', 'pink', 'olive']
for (factor, label), color in zip(zip(mesh_factors, mesh_labels), colors):
    dat_path = mesh_info[label].get("dat_path", f"results/sphere_{label}.dat")
    if not os.path.exists(dat_path):
        print(f"{label}: no .dat file found at {dat_path}, skipping plot")
        continue

    d = parse_dat(dat_path)
    if len(d["phi_vals"]) == 0:
        print(f"{label}: .dat parsed empty, skipping plot")
        continue

    # for TE-z, co-pol is Sph; sort by phi for clean line
    idx = np.argsort(d["phi_vals"])
    edge_mm = mesh_info[label]["edge_mm"]
    n_tri   = mesh_info[label]["divisions"]  # now stores tri count
    ax.plot(d["phi_vals"][idx], d["sph"][idx],
            color=color, lw=1.2,
            label=f'{label}  (edge~{edge_mm:.1f}mm, tris={n_tri})')
    
ax.set_xlabel('Azimuth angle phi (deg)')
ax.set_ylabel('RCS (dBsm)')
ax.set_xlim(0, 360)

# y limits centered on the analytical value, so this adapts
# automatically when `a` (and thus sigma_dBsm) changes
margin = 5  # dB above/below analytical value to show
ax.set_ylim(sigma_dBsm - margin, sigma_dBsm + margin)

ax.set_title(f"Sphere RCS — Mesh Convergence vs Analytical\n"
              f"a={a} m, f={freq/1e9:.1f} GHz, ka={ka:.1f}")
ax.legend(loc='best', fontsize=8)
ax.grid(True, alpha=0.3)
plt.tight_layout()
from datetime import datetime
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
plt.savefig(f"plots/sphere_convergence_linear_{ts}.png", dpi=150)
plt.close(fig)
print("\nSaved plots/sphere_convergence_linear.png")

print("\nDone.")