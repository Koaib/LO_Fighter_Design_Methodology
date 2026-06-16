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
print(f"Plate b (Z)       = {a*1000:.1f} mm = {a/wl:.1f} lambda")
print(f"Plate a (Y)       = {b*1000:.1f} mm = {b/wl:.1f} lambda")
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
        u = max(int(round(b / target_edge)), 4)
        w = max(int(round(a / target_edge)), 4)

        vsp.VSPRenew()                      # full reset EVERY iteration, not just once
        vsp.ReadVSPFile(template_path)

        geoms = vsp.FindGeoms()
        print(f"{label}: geoms after fresh read -> "
              f"{[(g, vsp.GetGeomTypeName(g)) for g in geoms]}")
        wid = geoms[0]

        parm_by_name = {vsp.GetParmName(pid): pid for pid in vsp.GetGeomParmIDs(wid)}

        def pset(name, val):
            pid = parm_by_name.get(name)
            if pid is None:
                raise KeyError(f"No parm named '{name}' on this geom. "
                                f"Available: {sorted(parm_by_name.keys())}")
            vsp.SetParmVal(pid, val)

        pset("Length", b)
        pset("Width",  a)
        pset("Height", 0.001)
        pset("Tess_W", w)
        pset("Tess_U", u)
        pset("Y_Rotation", 90)
        vsp.Update()

        bb_min = vsp.GetGeomBBoxMin(wid)
        bb_max = vsp.GetGeomBBoxMax(wid)
        dx, dy, dz = bb_max.x()-bb_min.x(), bb_max.y()-bb_min.y(), bb_max.z()-bb_min.z()
        print(f"  bbox: dx={dx*1000:.1f}mm dy={dy*1000:.1f}mm dz={dz*1000:.1f}mm "
              f"(expect dx~1mm thin, dy~{b*1000:.0f}mm, dz~{a*1000:.0f}mm)")

        stl_path  = os.path.abspath(f"stl/plate_{label}.stl")
        vsp3_path = os.path.abspath(f"vsp3/plate_{label}.vsp3")

        vsp.ExportFile(stl_path, vsp.SET_ALL, vsp.EXPORT_STL)
        vsp.SetVSP3FileName(vsp3_path)
        vsp.WriteVSPFile(vsp3_path, vsp.SET_ALL)

        mesh_info[label] = dict(w=w, u=u,
                                edge_mm=target_edge*1000,
                                stl_path=stl_path,
                                vsp3_path=vsp3_path)
        print(f"{label}: edge~{target_edge*1000:.1f}mm, "
              f"w={w}, u={u} -> {stl_path}")
        # no DeleteGeom needed — next loop iteration's VSPRenew() wipes everything clean

# if HAVE_VSP:
#     vsp.VSPRenew()
#     template_path = os.path.abspath("box_template.vsp3")

#     for factor, label in zip(mesh_factors, mesh_labels):
#         target_edge = factor * wl
#         u = max(int(round(b / target_edge)), 4)
#         w  = max(int(round(a / target_edge)), 4)

#         vsp.ReadVSPFile(template_path)

#         wid = vsp.FindGeoms()[0]

#         vsp.SetParmVal(wid, "Length", "Design", b)
#         vsp.SetParmVal(wid, "Width",  "Design", a)
#         vsp.SetParmVal(wid, "Height", "Design", 0.001)
#         vsp.SetParmVal(wid, "Tess_W", "Shape",  w)
#         vsp.SetParmVal(wid, "Tess_U", "Shape",  u)
#         vsp.SetParmVal(wid, "Y_Rotation", "XForm",  90)

#         vsp.Update()

#         stl_path  = os.path.abspath(f"stl/plate_{label}.stl")
#         vsp3_path = os.path.abspath(f"vsp3/plate_{label}.vsp3")

#         vsp.ExportFile(stl_path, vsp.SET_ALL, vsp.EXPORT_STL)
#         vsp.SetVSP3FileName(vsp3_path)
#         vsp.WriteVSPFile(vsp3_path, vsp.SET_ALL)

#         mesh_info[label] = dict(w=w, u=u,
#                                 edge_mm=target_edge*1000,
#                                 stl_path=stl_path,
#                                 vsp3_path=vsp3_path)
#         print(f"{label}: edge~{target_edge*1000:.1f}mm, "
#               f"w={w}, u={u} -> {stl_path}")

#         vsp.DeleteGeom(wid)


# # try:
# #     import openvsp as vsp
# #     HAVE_VSP = True
# # except ImportError:
# #     HAVE_VSP = False
# #     print("\nWARNING: openvsp not importable — skipping STL generation.")

# # mesh_info = {}

# # if HAVE_VSP:
# #     vsp.VSPRenew()
# #     template_path = os.path.abspath("box_template.vsp3")

# #     for factor, label in zip(mesh_factors, mesh_labels):
# #         target_edge = factor * wl
# #         u = max(int(round(b / target_edge)), 4)
# #         w = max(int(round(a / target_edge)), 4)

# #         vsp.ReadVSPFile(template_path)
# #         wid = vsp.FindGeoms()[0]

# #         # Build a name -> parm_id lookup, group-agnostic.
# #         parm_by_name = {vsp.GetParmName(pid): pid for pid in vsp.GetGeomParmIDs(wid)}

# #         def pset(name, val):
# #             pid = parm_by_name.get(name)
# #             if pid is None:
# #                 raise KeyError(f"No parm named '{name}' on this geom. "
# #                                 f"Available: {sorted(parm_by_name.keys())}")
# #             vsp.SetParmVal(pid, val)

# #         pset("Length", b)
# #         pset("Width",  a)
# #         pset("Height", 0.001)
# #         pset("Num_W",  w)
# #         pset("Num_U",  u)
# #         pset("YRot",   90)
# #         vsp.Update()

# #         # Sanity check: confirm the exported box actually has the dimensions
# #         # you think it has, given the 90deg YRot.
# #         bb_min = vsp.GetGeomBBoxMin(wid)
# #         bb_max = vsp.GetGeomBBoxMax(wid)
# #         dx, dy, dz = bb_max.x()-bb_min.x(), bb_max.y()-bb_min.y(), bb_max.z()-bb_min.z()
# #         print(f"  bbox: dx={dx*1000:.1f}mm dy={dy*1000:.1f}mm dz={dz*1000:.1f}mm "
# #               f"(expect ~0.001m thick on X, a={a*1000:.0f}mm on Z, b={b*1000:.0f}mm on Y)")

# #         stl_path  = os.path.abspath(f"stl/plate_{label}.stl")
# #         vsp3_path = os.path.abspath(f"vsp3/plate_{label}.vsp3")

# #         vsp.ExportFile(stl_path, vsp.SET_ALL, vsp.EXPORT_STL)
# #         vsp.SetVSP3FileName(vsp3_path)
# #         vsp.WriteVSPFile(vsp3_path, vsp.SET_ALL)

# #         mesh_info[label] = dict(w=w, u=u,
# #                                 edge_mm=target_edge*1000,
# #                                 stl_path=stl_path,
# #                                 vsp3_path=vsp3_path)
# #         print(f"{label}: edge~{target_edge*1000:.1f}mm, "
# #               f"w={w}, u={u} -> {stl_path}")

# #         vsp.DeleteGeom(wid)


# try:
#     import openvsp as vsp
#     HAVE_VSP = True
# except ImportError:
#     HAVE_VSP = False
#     print("\nWARNING: openvsp not importable — skipping STL generation.")

# mesh_info = {}

# if HAVE_VSP:
#     vsp.VSPRenew()
#     template_path = os.path.abspath("box_template.vsp3")

#     for factor, label in zip(mesh_factors, mesh_labels):
#         target_edge = factor * wl
#         u = max(int(round(b / target_edge)), 4)
#         w = max(int(round(a / target_edge)), 4)

#         vsp.ReadVSPFile(template_path)
#         wid = vsp.FindGeoms()[0]

#         parm_by_name = {vsp.GetParmName(pid): pid for pid in vsp.GetGeomParmIDs(wid)}

#         def pset(name, val):
#             pid = parm_by_name.get(name)
#             if pid is None:
#                 raise KeyError(f"No parm named '{name}' on this geom. "
#                                 f"Available: {sorted(parm_by_name.keys())}")
#             vsp.SetParmVal(pid, val)

#         pset("Length", a)        # local X -> global Z after Y_Rotation=90
#         pset("Width",  b)        # local Y -> stays global Y
#         pset("Height", 0.001)    # local Z -> global X  (thin, becomes the normal)
#         pset("Tess_W", w)        # divisions along Length (a / Z)
#         pset("Tess_U", u)        # divisions along Width  (b / Y)
#         pset("Y_Rotation", 90)
#         vsp.Update()

#         bb_min = vsp.GetGeomBBoxMin(wid)
#         bb_max = vsp.GetGeomBBoxMax(wid)
#         dx, dy, dz = bb_max.x()-bb_min.x(), bb_max.y()-bb_min.y(), bb_max.z()-bb_min.z()
#         print(f"  bbox: dx={dx*1000:.1f}mm dy={dy*1000:.1f}mm dz={dz*1000:.1f}mm "
#               f"(expect dx~1mm thin, dy~{b*1000:.0f}mm, dz~{a*1000:.0f}mm)")

#         stl_path  = os.path.abspath(f"stl/plate_{label}.stl")
#         vsp3_path = os.path.abspath(f"vsp3/plate_{label}.vsp3")

#         vsp.ExportFile(stl_path, vsp.SET_ALL, vsp.EXPORT_STL)
#         vsp.SetVSP3FileName(vsp3_path)
#         vsp.WriteVSPFile(vsp3_path, vsp.SET_ALL)

#         mesh_info[label] = dict(w=w, u=u,
#                                 edge_mm=target_edge*1000,
#                                 stl_path=stl_path,
#                                 vsp3_path=vsp3_path)
#         print(f"{label}: edge~{target_edge*1000:.1f}mm, "
#               f"w={w}, u={u} -> {stl_path}")

#         vsp.DeleteGeom(wid)
        
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
    idx     = np.argsort(d["phi_vals"])
    edge_mm = mesh_info[label]["edge_mm"]
    n_c     = mesh_info[label]["w"]
    n_s     = mesh_info[label]["u"]
    ax.plot(d["phi_vals"][idx], d["sph"][idx],
            color=color, lw=1.2,
            label=f'{label}  (edge~{edge_mm:.1f}mm, Nc={n_c}, Ns={n_s})')

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
plt.savefig("plots/plate_convergence_cart.png", dpi=150)
plt.close(fig)
print("\nSaved plots/plate_convergence_cart.png")

print("\nDone.")