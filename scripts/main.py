# -*- coding: utf-8 -*-
"""
Created on Thu Apr 16 20:24:37 2026

@author: KK
"""

"""
Single entry point for the LO Fighter Design Methodology pipeline.

Pipeline (all controlled from the config sections below — one file,
edited in one place):
  1. OpenVSP    — parametric aircraft geometry generation, VSP3/STEP/STL export
  2. OpenRCS    — Physical Optics monostatic RCS (pure Python, no MATLAB/
                  Octave/license) → Results/RCS/            [RUN_RCS toggle]
  3. VSPAero    — VLM aero sweep across the Mach x Altitude grid below →
                  Results/Aero/
  4. Stability  — static margin / Cm-alpha analysis on each aero run →
                  Results/Stability/
  5. Aviary     — fixed-mission fuel/range analysis, built from this run's
                  aero CSVs → Results/aviary_perf/           [RUN_AVIARY toggle]

Usage:
    python scripts/main.py

To change design parameters, edit the geometry section below.
To change RCS settings (frequency, angles, polarisation), edit the
RCS SETTINGS section at the bottom or pass them into run_openrcs_rcs().
To change Aviary/mission settings (mass basis, engine specs, cruise
profile), edit the AVIARY / MISSION CONFIG section below — everything
Aviary-related is configured from this one file, nothing to edit in
scripts/aviary/run_aviary.py for a normal run.
"""

import vsp_setup
import openvsp as vsp
import os
import matplotlib.pyplot as plt
import pandas as pd
import time

# IMPORT_FILE/GEOMETRY_DIR/REF_WING_NAME live in pipeline_config.py — the
# single place that names the geometry file, shared with extract_params.py
# and print_wing_ref_params.py so they can never silently disagree.
from pipeline_config import ROOT_DIR, GEOMETRY_DIR, IMPORT_FILE, REF_WING_NAME

"""
Single entry point for the LO Fighter Design Methodology pipeline.

INPUT_MODE options:
  "generate"   — build geometry from scratch using OpenVSP parameters below
  "import_stl" — skip geometry, load an existing STL from Geometry/
  "import_vsp3"— load an existing .vsp3 from Geometry/, then export STL
"""

# =========================
# INPUT MODE — edit this
# =========================
# IMPORT_FILE/REF_WING_NAME come from pipeline_config.py (see import above)
# — edit them there, not here, so extract_params.py and
# print_wing_ref_params.py automatically stay pointed at the same geometry.

INPUT_MODE    = "import_vsp3"       # "generate" | "import_stl" | "import_vsp3"
REF_MODE      = "auto"      # use "manual" for box_template — it has no wing

# =========================
# PIPELINE STAGE TOGGLES — edit this
# =========================
RUN_RCS    = True    # OpenRCS monostatic RCS pass (Results/RCS/)
RUN_AVIARY = True   # Aviary mission analysis, runs AFTER the aero+stability
                     # loop below finishes — needs this run's full 9-file
                     # Mach x Altitude aero-CSV grid to build its polar table

# =========================
# STL MESH SETTINGS — edit this
# =========================
# STL tessellation tied directly to RCS wavelength (lambda = c/freq),
# same CFD-mesh approach used in the sphere/flat-plate/almond validation.
# Convergence study on those shapes showed lambda/4-lambda/8 is feasible;
# lambda/6 is the time/accuracy compromise currently in use.
# min and max no longer have to match — e.g. MAX=4, MIN=8 refines curved
# regions to lambda/8 while flatter regions stay at lambda/4.
USE_CFD_MESH     = True     # False -> old plain ExportFile(EXPORT_STL)
FREQ_GHZ         = 12.0     # also drives the RCS run below
AZ_RANGE         = "half"   # "full" or "half" — half valid for bilaterally symmetric aircraft
DELP             = 1.0       # phi step, deg — 30° (7 pts across a half-circle) was
                              # far too coarse to resolve real RCS features (specular
                              # flashes/nulls are often only a few degrees wide);
                              # matches sweep_driver.py's own delp=1.0
MAX_EDGE_FACTOR  = 1        # coarse bound: edge = lambda / MAX_EDGE_FACTOR
MIN_EDGE_FACTOR  = 3        # fine bound:   edge = lambda / MIN_EDGE_FACTOR
MAX_GAP_FACTOR   = 3        # max_gap = lambda / MAX_GAP_FACTOR
GROWTH_RATIO     = 1.6      # OpenVSP default -- grading ON (was 10.0 = off)
NUM_CIRCLE_SEGS  = 12.0     # OpenVSP default -- curvature detection ON (was ~0 = off)

# =========================
# GEOMETRY FOLDER PATH
# =========================
# ROOT_DIR/GEOMETRY_DIR come from pipeline_config.py (see import above).

os.makedirs(GEOMETRY_DIR, exist_ok=True)

SETS_FILE = os.path.join(GEOMETRY_DIR, os.path.splitext(IMPORT_FILE)[0] + "_sets.json")

# =========================
# BRANCH ON INPUT MODE
# =========================

if INPUT_MODE == "import_stl":
    stl_file = os.path.join(GEOMETRY_DIR, IMPORT_FILE)
    if not os.path.isfile(stl_file):
        raise FileNotFoundError(f"STL not found: {stl_file}")
    # Copy into STL_Files/ where run_openrcs expects it
    import shutil
    dest = vsp_setup.stl_path(IMPORT_FILE)
    shutil.copy2(stl_file, dest)
    print(f"✅ Imported STL: {IMPORT_FILE}")
    stl_for_rcs = IMPORT_FILE

elif INPUT_MODE == "import_vsp3":
    import openvsp as vsp
    vsp3_file = os.path.join(GEOMETRY_DIR, IMPORT_FILE)
    if not os.path.isfile(vsp3_file):
        raise FileNotFoundError(f"VSP3 not found: {vsp3_file}")
    vsp.VSPCheckSetup()
    vsp.ClearVSPModel()
    vsp.ReadVSPFile(vsp3_file)
    vsp.Update()

    if not os.path.exists(SETS_FILE):
        raise FileNotFoundError(
            f"No sets file found: {SETS_FILE}\n"
            f"Run extract_params.py on this vsp3 first, then classify the geoms."
        )
    thin_set, thick_set = vsp_setup.apply_geom_sets(SETS_FILE)

    wing_id = None
    if REF_MODE == "auto":
        matches = [gid for gid in vsp.FindGeoms() if vsp.GetGeomName(gid) == REF_WING_NAME]
        if not matches:
            raise ValueError(f"REF_WING_NAME='{REF_WING_NAME}' not found in geometry.")
        wing_id = matches[0]

    # Derive STL name from the vsp3 filename
    stl_name = os.path.splitext(IMPORT_FILE)[0] + ".stl"
    stl_out  = vsp_setup.stl_path(stl_name)

    if USE_CFD_MESH:
        vsp_setup.export_stl_cfdmesh(
            out_stl_path    = stl_out,
            freq_ghz        = FREQ_GHZ,
            min_edge_factor = MIN_EDGE_FACTOR,
            max_edge_factor = MAX_EDGE_FACTOR,
            max_gap_factor  = MAX_GAP_FACTOR,
            growth_ratio    = GROWTH_RATIO,
            num_circle_segs = NUM_CIRCLE_SEGS,
        )
    else:
        vsp.ExportFile(stl_out, vsp.SET_ALL, vsp.EXPORT_STL)

    print(f"✅ Loaded VSP3 and exported STL: {stl_name}")
    stl_for_rcs = stl_name
    
else:  # "generate"
    import openvsp as vsp
    vsp.VSPCheckSetup()
    vsp.ClearVSPModel()

    # =====================
    # FUSELAGE
    # =====================
    fuselage = vsp.AddGeom("FUSELAGE")
    vsp.SetParmVal(fuselage, "Length", "Design", 10.0)

    # =====================
    # MAIN WING
    # =====================
    wing = vsp.AddGeom("WING")
    vsp.SetParmVal(wing, "Span",       "XSec_1", 12.0)
    vsp.SetParmVal(wing, "Root_Chord", "XSec_1",  2.5)
    vsp.SetParmVal(wing, "Tip_Chord",  "XSec_1",  1.2)
    vsp.SetParmVal(wing, "Sweep",      "XSec_1", 25.0)
    vsp.SetParmVal(wing, "Dihedral",   "XSec_1",  5.0)
    vsp.SetParmVal(wing, "X_Rel_Location", "XForm", 4.0)
    vsp.SetParmVal(wing, "Z_Rel_Location", "XForm", 0.0)

    # =====================
    # HORIZONTAL TAIL
    # =====================
    htail = vsp.AddGeom("WING")
    vsp.SetParmVal(htail, "Span",       "XSec_1",  5.0)
    vsp.SetParmVal(htail, "Root_Chord", "XSec_1",  1.2)
    vsp.SetParmVal(htail, "Tip_Chord",  "XSec_1",  0.6)
    vsp.SetParmVal(htail, "Sweep",      "XSec_1", 30.0)
    vsp.SetParmVal(htail, "X_Rel_Location", "XForm", 8.5)
    vsp.SetParmVal(htail, "Z_Rel_Location", "XForm", 0.2)

    vsp.Update()

    vsp.WriteVSPFile(vsp_setup.vsp_path("aircraft.vsp3"))
    vsp.ExportFile(vsp_setup.stp_path("aircraft.stp"), vsp.SET_ALL, vsp.EXPORT_STEP)
    vsp.ExportFile(vsp_setup.stl_path("aircraft.stl"), vsp.SET_ALL, vsp.EXPORT_STL)
    print("✅ Aircraft created and saved successfully!")
    stl_for_rcs = "aircraft.stl"

# =========================
# RCS PIPELINE
# =========================

if RUN_RCS:
    vsp_setup.run_openrcs_rcs(
        stl_filename = stl_for_rcs,
        freq         = FREQ_GHZ,
        pol          = "TE-z",
        cuts         = "azimuth",
        az_range     = AZ_RANGE,
        delp         = DELP,
    )

# =========================
# AERO SETTINGS
# =========================

ALPHA_START  = -10.0
ALPHA_END    = 22.0
ALPHA_NPTS   = 17
MACH_LIST      = [0.2, 0.4, 0.6]
ALTITUDE_LIST  = [0.0, 15000.0, 35000.0]
RE_CREF      = 1e6   # fallback only — run_vspaero_aero() auto-computes the real
                      # Reynolds number from actual wing chord + ISA atmosphere
                      # whenever it can read the wing geometry (always, in
                      # practice), silently overriding this value. Only takes
                      # effect if that auto-calc fails.
WAKE_ITERS   = 8

# =========================
# STABILITY SETTINGS
# =========================
# X_CG/Y_CG/Z_CG are absolute coordinates in the .vsp3 model's own native
# length unit (meters, for this geometry) — NOT a fraction of MAC. They're
# passed straight into OpenVSP's VSPAEROSettings "Xcg"/"Ycg"/"Zcg" parms
# (vsp_setup.run_vspaero_aero()), which read plain model-unit coordinates.
#
# X_CG traces to Giannelis, Bykerk & Vio, Aerospace 2023, 10, 746 (the
# SSAM-Gen5 source paper), Table 1: "XCoG = -0.4385 m" for their 0.75 m
# wind-tunnel-scale model (sign convention differs from this .vsp3's axis
# direction, magnitude matches exactly). This project's own two .vsp3
# geometries are NOT a 1:25.339 copy of the paper's exact model (this
# project's "NOT_scaled_by_19" file measures 0.2169 m^2 / 0.7135 m,
# bigger than the paper's Table 1 0.1091 m^2 / 0.535 m — expected, since
# it's a locally modified "nozzle_mod" variant, not a byte-identical
# reproduction). "scaled_by_19" (this file) IS confirmed, via its own
# .vsp3 dump, to be a clean, exact 19x scale-up of THAT file specifically
# — span ratio 19.000000, area ratio 361=19^2, aspect ratio identical to
# 12 decimal places between the two dumps. So 0.4385 m scales by 19 (the
# real ratio between this project's own two files), not by 25.339 (the
# paper's wind-tunnel-to-full-scale ratio, which doesn't apply here).
X_CG = 8.3315   # m — 0.4385 * 19 (see note above)
Y_CG = 0.0      # m
Z_CG = 0.0      # m

# =========================
# AVIARY / MISSION CONFIG — edit this to change any Aviary-related input
# =========================
# Same Mach/altitude grid drives both VSPAero (above) and Aviary — MACH_LIST
# / ALTITUDE_LIST from AERO SETTINGS are reused directly below, so there's
# no separate list here that could silently fall out of sync.

# "scaled_by_19" wing planform (confirmed via both .vsp3 dumps to be
# this project's own "NOT_scaled_by_19" geometry scaled up by an exact
# factor of 19 — span ratio 19.000000, area ratio 361=19^2, identical
# aspect ratio between the two files to 12 decimal places; NOT directly
# tied to the SSAM-Gen5 source paper's separately-stated "19 m full-scale
# vehicle" length, which is a different, unverified-against-this-project
# number — see pipeline_config.py's IMPORT_FILE note) — NOT a scaled-down
# F-16C value (see mass basis note below for why that distinction
# matters). Read directly off the actual .vsp3 (TotalArea/TotalSpan/
# TotalAR parms, via scripts/aviary/print_wing_ref_params.py's method)
# and unit-converted:
# TotalArea=78.319 m^2 -> 843.018 ft^2, TotalSpan=13.5565 m -> 44.477 ft,
# TotalAR=2.3465 (dimensionless, low-AR delta planform per Giannelis,
# Bykerk & Vio, Aerospace 2023, 10, 746 — the SSAM-Gen5 source paper).
TEST_WING_AREA_FT2     = 843.018026816014
TEST_WING_SPAN_FT      = 44.47670603674372
TEST_WING_ASPECT_RATIO = 2.346542205448008
TEST_WING_HAS_STRUT    = False
TEST_WING_HAS_FOLD     = False

# ── Mass basis ───────────────────────────────────────────────────────────
# Real F-22A Raptor published reference specs, used ONLY as a wing-loading
# basis to derive a physically self-consistent placeholder mass for this
# geometry — NOT a claim that this geometry IS an F-22 or a uniform scale
# of one. Still a placeholder pending a real mass buildup for the actual
# full-scale geometry.
#
# Switched from F-16C to F-22A (was F16C_* before). Two reasons: (1) this
# geometry's own wing area (TEST_WING_AREA_FT2 = 843.02 ft^2) is almost
# exactly the real F-22A's (840 ft^2, 78.04 m^2) — scaling the F-22's
# wing loading onto this geometry is ~1.004x, vs. ~2.81x scaling up from
# the F-16C's much smaller 300 ft^2 wing, so far less of the resulting
# mass is an artifact of the scale-up itself; (2) this project's source
# geometry (SSAM-Gen5, Giannelis, Bykerk & Vio, Aerospace 2023, 10, 746)
# explicitly models a fifth-generation, twin-engine, high-performance
# fighter class — the F-22 is a direct match for that class; the F-16C
# is a much lighter fourth-generation single-engine aircraft.
# Source: USAF F-22 Raptor fact sheet (af.mil), as mirrored/corroborated
# across multiple independent aviation references — the primary af.mil
# page itself was not directly fetchable from this environment (network
# egress policy blocks .mil and most non-package-registry domains); the
# figures below are consistent across every source checked.
F22_EMPTY_MASS_LBM = 43340.0   # published F-22A empty weight
F22_GROSS_MASS_LBM = 83500.0   # published F-22A max takeoff weight
F22_FUEL_MASS_LBM  = 18000.0   # published F-22A internal fuel capacity
F22_WING_AREA_FT2  = 840.0     # published F-22A wing area

# ── Engine specs (simplified F100-PW-229-class deck — NOT real engine test
# data, see scripts/aviary/build_engine_deck.py) ───────────────────────────
ENGINE_T_SL_DRY_LBF = 17800.0   # published F100-PW-229 dry static thrust
ENGINE_T_SL_AB_LBF  = 29100.0   # published F100-PW-229 afterburner static thrust
# TSFC is no longer a constant here — build_engine_deck.py computes it
# from Mattingly & Heiser's TSFC correlation (Ch.3 Sec.3.3.2, Eqs.
# 3.55a/b for this engine class), same citation-over-guess upgrade as
# the thrust lapse below.

# Thrust lapse AND TSFC are both engine-CLASS-specific — Mattingly &
# Heiser give a different equation per engine architecture (turbojet,
# high-bypass turbofan, low-bypass mixed-flow turbofan, ...), not one
# universal formula. ENGINE_TYPE selects which class's equations
# build_engine_deck.py uses.
# "low_bypass_mixed_flow_turbofan" (thrust: Eqs. 2.54a/b; TSFC: Eqs.
# 3.55a/b) is the correct choice — it's the F100-PW-229/F110 engine
# class (F-16/F-15) this deck models. "turbojet" is also implemented
# (thrust: Eqs. 2.55a/b; TSFC: Eqs. 3.56a/b) if this project ever needs
# it. Any other value raises NotImplementedError rather than silently
# reusing these numbers for a different engine architecture — add a
# class only by pasting its real equations from the same book sections.
ENGINE_TYPE = "low_bypass_mixed_flow_turbofan"

# ENGINE_THROTTLE_RATIO is Mattingly & Heiser's TR: the theta0 breakpoint
# above which the engine control system is temperature-limited rather
# than flat-rated (Appendix D, Eq. D.6) — a control-system design choice,
# not a tabulated per-engine-class value (the book has no TR lookup
# table). 1.07 is the closest available anchor: the book's own AAF
# (supercruise fighter, F100-class engine) worked example sweeps
# TR=1.00-1.08 and settles on TR=1.07 (Ch.2 example, Fig.2.E1b/
# Table 2.E2) — still not the real F100-PW-229 manufacturer TR (not in
# any excerpt available for this project). build_engine_deck.py prints a
# sea-level-static cross-check against ENGINE_T_SL_DRY_LBF every run —
# if TR is changed, watch that check for a large disagreement.
ENGINE_THROTTLE_RATIO = 1.07

# ── Mission profile ────────────────────────────────────────────────────────
CRUISE_MACH        = 0.6
CRUISE_ALTITUDE_FT = 35000.0
DESIGN_RANGE_NMI   = 400.0

# =========================
# TRIGGER AERO PIPELINE
# =========================

geom_stem = os.path.splitext(IMPORT_FILE)[0]

import glob
for f in glob.glob(os.path.join(vsp_setup.VSP_FILES, f"{geom_stem}_M*.*")):
    os.remove(f)

mach_results = []  # (M, alt, polar_dst, CD0, K, r2)
for ALT in ALTITUDE_LIST:
    for M in MACH_LIST:
        # supersonic panel/mixed-body limitation: thick surfaces only valid subsonic —
        # for M>=1, exclude thick geometry entirely and run thin-surfaces-only VLM
        thick_set_this_run = thick_set if M < 1.0 else vsp.SET_NONE
        polar_dst, CD0, K, r2 = vsp_setup.run_vspaero_aero(
            wing_id=wing_id,
            altitude_ft=ALT,
            alpha_start=ALPHA_START, alpha_end=ALPHA_END, alpha_npts=ALPHA_NPTS,
            mach_start=M, mach_end=M, mach_npts=1,
            re_cref_start=RE_CREF, wake_iters=WAKE_ITERS,
            thin_geom_set=thin_set,
            thick_geom_set=thick_set_this_run,
            ref_mode=REF_MODE,
            x_cg=X_CG, y_cg=Y_CG, z_cg=Z_CG,
            run_name=f"{geom_stem}_M{M:.2f}_ALT{int(ALT)}",
        )
        if polar_dst is not None:
            mach_results.append((M, ALT, polar_dst, CD0, K, r2))
        time.sleep(5)

# ── everything below runs ONCE, after the loop finishes ──────────────
import csv
summary_path = os.path.join(vsp_setup.AERO_RESULTS_DIR, f"drag_polar_fits_{geom_stem}.csv")
write_header = not os.path.exists(summary_path)
with open(summary_path, "a", newline="") as f:
    writer = csv.writer(f)
    if write_header:
        writer.writerow(["Mach", "Altitude_ft", "CD0", "K", "R2", "polar_file"])
    for M, ALT, polar_dst, CD0, K, r2 in mach_results:
        writer.writerow([M, ALT, CD0, K, r2, os.path.basename(polar_dst)])
print(f"   ✅ CD0/K summary: {summary_path}")
      
        
# # ── OVERLAY PLOTS — all Mach points on same axes, one per metric ────────

# # L/D vs Alpha
# fig, ax = plt.subplots(figsize=(7, 5))
# for M, polar_dst, CD0, K, r2 in mach_results:
#     df = pd.read_csv(polar_dst.replace(".polar", ".csv"))
#     if df["CL"].isna().all():
#         print(f"   Skipping M={M:.2f} in L/D overlay — all-NaN (diverged)")
#         continue
#     ax.plot(df["Alpha"], df["L/D"], "-o", ms=4, label=f"M={M:.2f}")
# ax.set_xlabel("Alpha (deg)")
# ax.set_ylabel("L/D")
# ax.set_title(f"L/D vs Alpha — {geom_stem}, Mach comparison")
# ax.legend()
# ax.grid(True, ls="--", alpha=0.6)
# fig.tight_layout()
# fig.savefig(os.path.join(vsp_setup.AERO_RESULTS_DIR, f"ld_alpha_overlay_{geom_stem}.png"), dpi=150)
# plt.close(fig)
# print(f"   ✅ L/D overlay saved for {geom_stem}")

# # CL vs Alpha
# fig, ax = plt.subplots(figsize=(7, 5))
# for M, polar_dst, CD0, K, r2 in mach_results:
#     df = pd.read_csv(polar_dst.replace(".polar", ".csv"))
#     if df["CL"].isna().all():
#         print(f"   Skipping M={M:.2f} in CL-alpha overlay — all-NaN (diverged)")
#         continue
#     ax.plot(df["Alpha"], df["CL"], "-o", ms=4, label=f"M={M:.2f}")
# ax.set_xlabel("Alpha (deg)")
# ax.set_ylabel("CL")
# ax.set_title(f"CL vs Alpha — {geom_stem}, Mach comparison")
# ax.legend()
# ax.grid(True, ls="--", alpha=0.6)
# fig.tight_layout()
# fig.savefig(os.path.join(vsp_setup.AERO_RESULTS_DIR, f"cl_alpha_overlay_{geom_stem}.png"), dpi=150)
# plt.close(fig)
# print(f"   ✅ CL-alpha overlay saved for {geom_stem}")

# # CL vs CD (drag polar)
# fig, ax = plt.subplots(figsize=(7, 5))
# for M, polar_dst, CD0, K, r2 in mach_results:
#     df = pd.read_csv(polar_dst.replace(".polar", ".csv"))
#     if df["CL"].isna().all():
#         print(f"   Skipping M={M:.2f} in drag-polar overlay — all-NaN (diverged)")
#         continue
#     ax.plot(df["CDtot"], df["CL"], "-o", ms=4, label=f"M={M:.2f}")
# ax.set_xlabel("CD")
# ax.set_ylabel("CL")
# ax.set_title(f"Drag Polar — {geom_stem}, Mach comparison")
# ax.legend()
# ax.grid(True, ls="--", alpha=0.6)
# fig.tight_layout()
# fig.savefig(os.path.join(vsp_setup.AERO_RESULTS_DIR, f"drag_polar_overlay_{geom_stem}.png"), dpi=150)
# plt.close(fig)
# print(f"   ✅ Drag polar overlay saved for {geom_stem}")

# ── STABILITY ────────────────────────────────────────────────────────
# CL_TARGET is computed PER (Mach, Altitude) point rather than one fixed
# number for the whole sweep: static margin (SM = -dCm/dCL) is evaluated
# AT a specific CL, and each Mach/Altitude combination in mach_results
# implies a DIFFERENT level-flight CL for the same aircraft weight
# (CL = W / (q*S), q = 0.5*rho(h)*V^2 falls as altitude rises or Mach
# drops) — a single fixed CL_TARGET would report SM at a CL most of the
# 9 sweep points don't actually fly at.
#
# Weight reuses the SAME wing-loading-scaled placeholder mass
# run_aviary.py computes downstream (gross_mass_lbm = F-22A wing loading
# x this geometry's TEST_WING_AREA_FT2, see AVIARY/MISSION CONFIG above)
# — kept consistent here rather than introducing a second, independent
# mass assumption just for this plot. Still inherits that mass basis's
# placeholder status (real F-22A wing loading, not this airframe's own
# mass) until the real full-scale mass buildup replaces it.
_wing_loading_lbm_ft2 = F22_GROSS_MASS_LBM / F22_WING_AREA_FT2
_gross_mass_lbm = _wing_loading_lbm_ft2 * TEST_WING_AREA_FT2
_weight_N = _gross_mass_lbm * 0.45359237 * 9.80665   # lbm -> kg -> N (std gravity)
_wing_area_m2 = TEST_WING_AREA_FT2 * 0.09290304

for M, ALT, polar_dst, CD0, K, r2 in mach_results:
    aero_csv = polar_dst.replace(".polar", ".csv")

    alpha_c, cl_c, sm_curve, r2_curve, linear_range = vsp_setup.local_slope_curve(aero_csv)
    print(f"   M={M:.2f}, ALT={int(ALT)}: linear region ≈ {linear_range[0]:.1f}° to {linear_range[1]:.1f}°"
          if linear_range[0] is not None else f"   M={M:.2f}, ALT={int(ALT)}: no region met R² threshold")

    # Level-flight CL at this Mach/Altitude: CL = W / (0.5 * rho * V^2 * S)
    _, RHO, _, a_sound = vsp_setup.isa_atmosphere(ALT)
    V = M * a_sound
    q = 0.5 * RHO * V**2
    CL_TARGET = _weight_N / (q * _wing_area_m2)

    # compute_static_margin() doesn't extrapolate — it fits the slope over
    # the window_pts CL points closest to CL_TARGET, so a CL_TARGET outside
    # the alpha sweep's actual CL range silently reports SM at whatever CL
    # the sweep DID reach (near-stall/sweep edge), not the printed target.
    # That's a real limitation of the wing-loading-placeholder weight at
    # low-Mach/high-altitude points (level flight there needs a CL beyond
    # what a -10..22 deg alpha sweep produces for this planform) — flagged
    # here rather than left silent.
    if CL_TARGET < cl_c.min() or CL_TARGET > cl_c.max():
        print(f"   ⚠️  CL_TARGET={CL_TARGET:.4f} outside this sweep's CL range "
              f"[{cl_c.min():.4f}, {cl_c.max():.4f}] — SM below is evaluated at "
              f"the nearest reachable CL, not the printed target")

    sm, sm_r2 = vsp_setup.compute_static_margin(aero_csv, CL_TARGET)
    print(f"   M={M:.2f}, ALT={int(ALT)}: SM at CL={CL_TARGET:.4f} (level-flight) = {sm:.4f}  (R²={sm_r2:.4f})")

    # Cm vs Alpha
    df = pd.read_csv(aero_csv)
    fig, ax = plt.subplots(figsize=(7,5))
    ax.plot(df["Alpha"], df["CMytot"], "b-o", ms=4)
    ax.set_xlabel("Alpha (deg)"); ax.set_ylabel("Cm")
    ax.set_title(f"Cm vs Alpha — M={M:.2f}, ALT={int(ALT)}ft, Xcg={X_CG}")
    ax.grid(True, ls="--", alpha=0.6)
    fig.savefig(os.path.join(vsp_setup.STABILITY_DIR, f"cm_alpha_{geom_stem}_M{M:.2f}_ALT{int(ALT)}.png"), dpi=150)
    plt.close(fig)

    # Cm vs CL
    fig, ax = plt.subplots(figsize=(7,5))
    ax.plot(df["CL"], df["CMytot"], "r-o", ms=4)
    ax.set_xlabel("CL"); ax.set_ylabel("Cm")
    ax.set_title(f"Cm vs CL — M={M:.2f}, ALT={int(ALT)}ft, Xcg={X_CG}")
    ax.grid(True, ls="--", alpha=0.6)
    fig.savefig(os.path.join(vsp_setup.STABILITY_DIR, f"cm_cl_{geom_stem}_M{M:.2f}_ALT{int(ALT)}.png"), dpi=150)
    plt.close(fig)

    # local-slope diagnostic
    fig, ax = plt.subplots(figsize=(7,5))
    ax.plot(alpha_c, sm_curve, "g-o", ms=3)
    ax.set_xlabel("Alpha (deg)"); ax.set_ylabel("Local SM (windowed)")
    ax.set_title(f"Local SM vs Alpha — M={M:.2f}, ALT={int(ALT)}ft")
    ax.grid(True, ls="--", alpha=0.6)
    fig.savefig(os.path.join(vsp_setup.STABILITY_DIR, f"sm_local_{geom_stem}_M{M:.2f}_ALT{int(ALT)}.png"), dpi=150)
    plt.close(fig)

    summary_path = os.path.join(vsp_setup.STABILITY_DIR, f"stability_summary_{geom_stem}.csv")
    write_header = not os.path.exists(summary_path)
    with open(summary_path, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["Mach", "Altitude_ft", "X_cg", "CL_target", "SM", "SM_R2", "linear_alpha_min", "linear_alpha_max"])
        w.writerow([M, ALT, X_CG, CL_TARGET, sm, sm_r2, linear_range[0], linear_range[1]])

# =========================
# AVIARY MISSION ANALYSIS
# =========================
# Runs last — needs the full 9-file Mach x Altitude aero-CSV grid this
# script just produced (above) for this same geom_stem. Every Aviary input
# comes from the AVIARY / MISSION CONFIG section above and is passed in
# explicitly below — run_aviary.py has nothing left to edit for a normal run.

if RUN_AVIARY:
    import sys
    sys.path.insert(0, os.path.join(ROOT_DIR, "scripts", "aviary"))
    from run_aviary import run_aviary_mission
    run_aviary_mission(
        geom_stem=geom_stem,
        wing_area_ft2=TEST_WING_AREA_FT2,
        wing_span_ft=TEST_WING_SPAN_FT,
        wing_aspect_ratio=TEST_WING_ASPECT_RATIO,
        wing_has_strut=TEST_WING_HAS_STRUT,
        wing_has_fold=TEST_WING_HAS_FOLD,
        f22_empty_mass_lbm=F22_EMPTY_MASS_LBM,
        f22_gross_mass_lbm=F22_GROSS_MASS_LBM,
        f22_fuel_mass_lbm=F22_FUEL_MASS_LBM,
        f22_wing_area_ft2=F22_WING_AREA_FT2,
        engine_t_sl_dry_lbf=ENGINE_T_SL_DRY_LBF,
        engine_t_sl_ab_lbf=ENGINE_T_SL_AB_LBF,
        engine_throttle_ratio=ENGINE_THROTTLE_RATIO,
        engine_type=ENGINE_TYPE,
        cruise_mach=CRUISE_MACH,
        cruise_altitude_ft=CRUISE_ALTITUDE_FT,
        design_range_nmi=DESIGN_RANGE_NMI,
        mach_list=MACH_LIST,
        altitude_list=ALTITUDE_LIST,
    )