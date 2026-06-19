# -*- coding: utf-8 -*-
"""
Created on Mon Jun 15 17:59:37 2026

@author: KK

PEC flat plate RCS validation — mirrors sphere_validation.py structure:
  1. Analytical PO RCS for azimuth cut (Cartesian plot)
  2. Generate plate STL meshes at different densities via OpenVSP
  3. Run each through OpenRCS PO solver (azimuth cut, theta=90)
  4. Overlay analytical + all mesh results on one Cartesian plot

Plate geometry:
    normal along +X  (broadside at phi=0/180)
    a = 125 mm = 5*lambda  (height, along Z)
    b = 250 mm = 10*lambda (width,  along Y)

Analytical formula:
    sigma(phi) = (4pi/lambda^2) * (a*b)^2 * cos^2(phi) * sinc^2(b*sin(phi)/lambda)

    cos^2(phi)             obliquity factor  -> zero at edge-on (phi=90,270)
    sinc^2(b*sin(phi)/lam) lobing pattern   -> first null at arcsin(lambda/b)
    numpy sinc(x) = sin(pi*x)/(pi*x)  so  np.sinc(b*sin(phi)/lambda)  is correct

Everything driven by freq, a, b at the top.

Folder layout (next to this script):
    stl/      generated plate STLs
    vsp3/     generated VSP3 model files
    results/  OpenRCS .dat output files
    plots/    analytical + comparison figures
"""

import sys, os, shutil
import numpy as np
import matplotlib.pyplot as plt

# ============================================================
# USER INPUTS
# ============================================================
freq = 12e9       # Hz
a    = 0.125      # plate height along Z (m)  — 5*lambda
b    = 0.250      # plate width  along Y (m)  — 10*lambda

mesh_factors = [1.0, 0.5, 1/3, 1/4]
# mesh_factors = [1/5, 1/6, 1/8, 1/10]
# mesh_factors = [1, 0.5, 1/5, 1/6]
# mesh_factors = [1/6, 1/5, 0.5, 1]


mesh_labels  = ["lambda", "lambda_2", "lambda_3", "lambda_4"]

OPENRCS_DIR = "../../OpenRCS/open-rcs"

# ============================================================
# Derived quantities
# ============================================================
c   = 3e8
wl  = c / freq
k   = 2 * np.pi / wl

sigma_max_lin  = (4 * np.pi / wl**2) * (a * b)**2
sigma_max_dBsm = 10 * np.log10(sigma_max_lin)
phi_null_deg   = np.degrees(np.arcsin(wl / b))

print("=" * 55)
print(f"Frequency         = {freq/1e9:.2f} GHz")
print(f"Wavelength lambda = {wl*1000:.3f} mm")
print(f"Plate a (Y, width)  = {a*1000:.1f} mm = {a/wl:.1f} lambda")
print(f"Plate b (Z, height) = {b*1000:.1f} mm = {b/wl:.1f} lambda")
print(f"Peak RCS          = {sigma_max_dBsm:.2f} dBsm  (phi=0,180)")
print(f"First null        = {phi_null_deg:.2f} deg from broadside")
print("=" * 55)

# ============================================================
# Output folders
# ============================================================
for d in ("stl", "vsp3", "results", "plots"):
    os.makedirs(d, exist_ok=True)

# ============================================================
# STEP 1 — Analytical solution + standalone plot
# ============================================================
phi_deg = np.linspace(0, 360, 3601)
phi_rad = np.deg2rad(phi_deg)

sigma_lin_phi  = ((4 * np.pi / wl**2) * (a * b)**2
                  * np.cos(phi_rad)**2
                  * np.sinc(b * np.sin(phi_rad) / wl)**2)

sigma_dBsm_phi = 10 * np.log10(np.maximum(sigma_lin_phi, 1e-20))

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(phi_deg, sigma_dBsm_phi, 'k-', lw=2, label='Analytical (PO)')
ax.set_xlabel('Azimuth angle phi (deg)')
ax.set_ylabel('RCS (dBsm)')
ax.set_title(f'Flat Plate RCS — Analytical PO\n'
             f'a={a*1000:.0f}mm x b={b*1000:.0f}mm, '
             f'f={freq/1e9:.1f} GHz')
ax.set_xlim(0, 360)
ax.set_ylim(sigma_max_dBsm - 60, sigma_max_dBsm + 10)
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("plots/analytical_plate.png", dpi=150)
plt.close(fig)
print("Saved plots/analytical_plate.png")


# ============================================================
# STEP 2 — Generate plate STLs via OpenVSP
# ============================================================

def filter_stl_keep_face(in_path, out_path, normal_axis=0, tol=0.9):
    with open(in_path) as f:
        lines = f.readlines()
    out_lines = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("solid") or line.startswith("endsolid"):
            out_lines.append(lines[i])
            i += 1
        elif line.startswith("facet normal"):
            parts = line.split()
            n = [float(parts[2]), float(parts[3]), float(parts[4])]
            if abs(n[normal_axis]) >= tol:   # keeps both +X and -X faces
                out_lines.extend(lines[i:i+7])
            i += 7
        else:
            i += 1
    with open(out_path, 'w') as f:
        f.writelines(out_lines)
        
try:
    import openvsp as vsp
    HAVE_VSP = True
except ImportError:
    HAVE_VSP = False
    print("\nWARNING: openvsp not importable — skipping STL generation.")

mesh_info = {}

if HAVE_VSP:
    template_path = os.path.abspath("box_template.vsp3")

    for factor, label in zip(mesh_factors, mesh_labels):
        target_edge = factor * wl

        # --- build geometry ---
        vsp.VSPRenew()
        vsp.ReadVSPFile(template_path)

        wid = vsp.FindGeoms()[0]
        parm_by_name = {vsp.GetParmName(pid): pid
                        for pid in vsp.GetGeomParmIDs(wid)}

        def pset(name, val):
            pid = parm_by_name.get(name)
            if pid is None:
                raise KeyError(f"Parm '{name}' not found. "
                               f"Available: {sorted(parm_by_name.keys())}")
            vsp.SetParmVal(pid, val)

        pset("Length", b)
        pset("Width",  a)
        pset("Height", 0.001)
        pset("Y_Rotation", 90)
        vsp.Update()

        # --- CFDMesh: set uniform edge length = factor * lambda ---
        vsp.SetCFDMeshVal(vsp.CFD_MAX_EDGE_LEN, target_edge)
        vsp.SetCFDMeshVal(vsp.CFD_MIN_EDGE_LEN, target_edge)   # min=max kills curvature criteria
        vsp.SetCFDMeshVal(vsp.CFD_GROWTH_RATIO, 10.0)           # large = growth ratio OFF
        vsp.SetCFDMeshVal(vsp.CFD_MAX_GAP,      target_edge)    # max_gap >= edge len = OFF
        vsp.SetCFDMeshVal(vsp.CFD_NUM_CIRCLE_SEGS, 0.00001)     # near-zero = OFF
        vsp.DeleteAllCFDSources()                                # no local sources

        stl_path  = os.path.abspath(f"stl/plate_{label}.stl")
        vsp3_path = os.path.abspath(f"vsp3/plate_{label}.vsp3")

        vsp.SetComputationFileName(vsp.CFD_STL_TYPE, stl_path)
        vsp.ComputeCFDMesh(vsp.SET_ALL, vsp.SET_NONE, vsp.CFD_STL_TYPE)

        vsp.SetComputationFileName(vsp.CFD_STL_TYPE, stl_path)
        vsp.ComputeCFDMesh(vsp.SET_ALL, vsp.SET_NONE, vsp.CFD_STL_TYPE)

        # filter to keep only +X face (plate normal after Y_Rotation=90)
        raw_stl = stl_path.replace(".stl", "_raw.stl")
        if os.path.exists(raw_stl):
            os.remove(raw_stl)
        os.rename(stl_path, raw_stl)
        filter_stl_keep_face(raw_stl, stl_path, normal_axis=0, tol=0.9)  

        vsp.SetVSP3FileName(vsp3_path)
        vsp.WriteVSPFile(vsp3_path, vsp.SET_ALL)

        # --- count actual triangles from the STL for the legend ---
        tri_count = 0
        if os.path.exists(stl_path):
            with open(stl_path) as fh:
                tri_count = sum(1 for ln in fh if ln.strip().startswith("facet normal"))

        mesh_info[label] = dict(edge_mm=target_edge * 1000,
                                n_tri=tri_count,
                                stl_path=stl_path,
                                vsp3_path=vsp3_path)
        print(f"{label}: edge={target_edge*1000:.1f}mm, "
              f"tris={tri_count}, -> {stl_path}")
        
# ============================================================
# STEP 3 — Run OpenRCS PO solver on each mesh
# ============================================================
import importlib
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
        
        # verify the facets file actually changed
        import os
        facets_file = os.path.join(OPENRCS_DIR, "facets.txt")
        coords_file = os.path.join(OPENRCS_DIR, "coordinates.txt")
        print(f"{label}: facets.txt size={os.path.getsize(facets_file)}, "
              f"coords.txt size={os.path.getsize(coords_file)}")

        Rs         = 0
        coord_list = extractCoordinatesData(Rs)

        params = [
            f"plate_{label}",
            freq,
            0, 0,
            1,          # TE-z
            Rs,
            0, 360, 1,
            90, 90, 1,
            None
        ]

        plot_name, fig_name, file_name = rcs_monostatic(params, coord_list)
        print(f"{label}: solver done -> {file_name}")

        if file_name and os.path.exists(file_name):
            dst = f"results/plate_{label}.dat"
            shutil.move(file_name, dst)
            mesh_info[label]["dat_path"] = dst
            print(f"  moved -> {dst}")
        else:
            print(f"  WARNING: result file not found at '{file_name}'")

# ============================================================
# STEP 4 — Parse .dat files and overlay Cartesian comparison plot
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
        "phi_vals": _extract("Phi (deg):"),
        "sth":      _extract("RCS Theta (dBsm):"),
        "sph":      _extract("RCS Phi (dBsm):"),
    }


fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(phi_deg, sigma_dBsm_phi, 'k-', lw=2.5,
        label=f'Analytical (peak={sigma_max_dBsm:.1f} dBsm)')

colors = ['red', 'green', 'blue', 'purple']
for (factor, label), color in zip(zip(mesh_factors, mesh_labels), colors):
    dat_path = mesh_info[label].get("dat_path", f"results/plate_{label}.dat")
    if not os.path.exists(dat_path):
        print(f"{label}: no .dat file found, skipping plot")
        continue
    d = parse_dat(dat_path)
    if len(d["phi_vals"]) == 0:
        print(f"{label}: .dat parsed empty, skipping plot")
        continue
    idx      = np.argsort(d["phi_vals"])
    edge_mm  = mesh_info[label]["edge_mm"]
    n_tri    = mesh_info[label].get("n_tri", 0)
    ax.plot(d["phi_vals"][idx], d["sph"][idx],
            color=color, lw=1.2,
            label=f'λ/{round(1/factor):.0f}  (edge={edge_mm:.1f}mm, tris={n_tri})')
    
ax.set_xlabel('Azimuth angle phi (deg)')
ax.set_ylabel('RCS (dBsm)')
ax.set_title(f'Flat Plate RCS — Mesh Convergence vs Analytical\n'
             f'a={a*1000:.0f}mm x b={b*1000:.0f}mm, '
             f'f={freq/1e9:.1f} GHz, theta=90 deg')
ax.set_xlim(0, 360)
ax.set_ylim(sigma_max_dBsm - 60, sigma_max_dBsm + 10)
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)
plt.tight_layout()
from datetime import datetime
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
plt.savefig(f"plots/plate_convergence_cart_{ts}.png", dpi=150)
plt.close(fig)
print("\nSaved plots/plate_convergence_cart.png")

print("\nDone.")

