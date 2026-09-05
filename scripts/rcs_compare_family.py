# -*- coding: utf-8 -*-
"""
Created on Sat Sep  5 17:06:29 2026

@author: KK

rcs_compare_family.py — standalone RCS sensitivity-study plotting/summary tool.

Decoupled on purpose from rcs_sweep_driver.py's execution: this script
only READS whatever manifest .json files and OpenRCS .dat outputs
already exist on disk (glob-based, exactly like the aero-side
compare_family.py's own load_family()) and (re)builds three comparison
plots + a summary CSV per study:
  1. mean azimuth RCS  vs. delta   (line plot)
  2. mean frontal RCS  vs. delta   (line plot)
  3. azimuth polar RCS, all completed deltas overlaid on one polar plot
  4. summary_<study>.csv — delta, means, and every raw output file path

It never spawns a worker subprocess and never re-runs the (expensive)
OpenRCS solver — that's rcs_sweep_driver.py's job. This means:
  - A study with only 8/11 deltas done and NO baseline yet still gets a
    full set of plots from whatever IS done.
  - Re-running this exact command later (e.g. once baseline finishes,
    or more deltas land) just overwrites the same plot files with the
    fuller picture — safe to run as often as you like, at any point.
  - Plotting no longer blocks on, or is blocked by, run_baseline() /
    run_parameter() in the driver.

Bug fix vs. the old in-driver version: the polar-overlay plot used to
call run_openrcs._azimuth_to_full_circle(...), but that function is
defined NESTED inside run_openrcs.py's run_openrcs_pipeline() — it is
not reachable as a module attribute, so that call would raise
AttributeError. Reimplemented locally below (_azimuth_to_full_circle),
identical half-circle-mirror logic, no import of run_openrcs needed for
it. _parse_dat IS a real module-level function in run_openrcs.py, so
that one is still imported and reused as-is.

Usage:
    python rcs_compare_family.py                  # every study found
    python rcs_compare_family.py VT_Cant           # just one
    python rcs_compare_family.py VT_Cant VT_Sweep_surf0sec1   # a few
"""
import sys, os, json, glob, csv
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from run_openrcs import _parse_dat  # module-level in run_openrcs.py — safe to reuse

RESULTS_ROOT  = ROOT_DIR / "Results" / "RCS_SensitivityStudy"
BASELINE_ROOT = RESULTS_ROOT / "_baseline"


# ── local re-implementation of the nested run_openrcs helper ────────────────

def _azimuth_to_full_circle(phi_deg, rcs_dBsm):
    """
    Mirrors a half-circle (az_range="half") azimuth cut out to the full
    360°, assuming left-right symmetry. Identical logic to the nested
    function of the same name inside run_openrcs.run_openrcs_pipeline() —
    duplicated here (not imported) because that one isn't module-level.
    If you ever promote it to module level in run_openrcs.py, this copy
    can be deleted and replaced with an import.
    """
    phi = phi_deg.copy()
    if len(phi) > 1 and np.isclose(phi[-1], phi[0] + 360.0):
        phi = phi[:-1]
        return phi, rcs_dBsm[:len(phi)]
    phi_left = 360.0 - phi[-2:0:-1]
    rcs_left = rcs_dBsm[-2:0:-1]
    return np.concatenate([phi, phi_left]), np.concatenate([rcs_dBsm[:len(phi)], rcs_left])


# ── manifest loading (glob-based — no hardcoded delta list required) ────────

def _load_baseline_manifest():
    """Returns the shared baseline manifest dict, or None if it doesn't
    exist yet or hasn't finished — callers treat None as "no Δ=0 point
    available yet", not as an error."""
    mpath = BASELINE_ROOT / "manifest" / "baseline.json"
    if not mpath.exists():
        return None
    with open(mpath) as f:
        entry = json.load(f)
    return entry if entry.get("status") == "done" else None


def _delta_from_tag(tag, study_name):
    # tag is built by rcs_sweep_driver.py as f"{study_name}_{d:+.2f}",
    # e.g. "VT_Cant_+3.00" -> strip the "VT_Cant_" prefix -> float("+3.00")
    return float(tag[len(study_name) + 1:])


def load_family(study_name, results_root):
    """
    [(delta, manifest_dict), ...] sorted by delta, done runs only.
    Glob-based (like compare_family.py's load_family()) instead of
    requiring a delta list up front, so this works even if you don't
    remember/pass the exact DELTAS_* list the driver used.

    Splices in the shared baseline as the Δ=0.0 point, if and only if
    it's actually done AND no per-study "+0.00" manifest already exists
    (build_param_configs() never writes one, but this guards against it
    anyway in case that ever changes).
    """
    manifest_dir = results_root / "manifest"
    rows = []
    for f in sorted(glob.glob(str(manifest_dir / f"{study_name}_*.json"))):
        with open(f) as fh:
            entry = json.load(fh)
        if entry.get("status") != "done":
            continue
        tag = entry.get("tag") or Path(f).stem
        rows.append((_delta_from_tag(tag, study_name), entry))

    if not any(d == 0.0 for d, _ in rows):
        baseline_entry = _load_baseline_manifest()
        if baseline_entry is not None:
            rows.append((0.0, baseline_entry))

    return sorted(rows, key=lambda r: r[0])


# ── plotting ─────────────────────────────────────────────────────────────

def _plot_mean_vs_delta(rows, tag_key, study_name, ylabel, out_path):
    deltas = [d for d, e in rows if tag_key in e.get("means", {})]
    means  = [e["means"][tag_key] for d, e in rows if tag_key in e.get("means", {})]
    if not deltas:
        print(f"  [outputs] no {tag_key} means to plot for {study_name}"); return None

    fig, ax = plt.subplots(figsize=(7, 4.5), facecolor="white")
    ax.set_facecolor("white")
    ax.plot(deltas, means, color="steelblue", lw=1.4, marker="o", markersize=5, zorder=3)
    baseline_val = np.mean(means)
    if 0.0 in deltas:
        i0 = deltas.index(0.0)
        baseline_val = means[i0]
        ax.plot(deltas[i0], means[i0], marker="o", markersize=9,
                markerfacecolor="none", markeredgecolor="crimson", markeredgewidth=1.6,
                zorder=4, label="baseline (Δ=0)")
        ax.legend(fontsize=9)
    ax.axhline(baseline_val, color="grey", lw=0.6, linestyle=":", zorder=1)
    ax.set_xlabel(f"{study_name}  Δ", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.set_title(f"{study_name} — {ylabel} vs. Δ", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved -> {out_path.name}")
    return out_path


def _plot_azimuth_polar_overlay(rows, study_name, out_path):
    """All deltas' azimuth cuts (TE-z co-pol = Sph) overlaid on one polar plot."""
    curves = []
    for d, e in rows:
        dat_path = e.get("rcs_outputs", {}).get("AZ_TE")
        if not dat_path or not os.path.isfile(dat_path):
            continue
        parsed = _parse_dat(dat_path)
        if not len(parsed["sph"]):
            continue
        phi_full, sph_full = _azimuth_to_full_circle(parsed["phi_vals"], parsed["sph"])
        curves.append((d, phi_full, sph_full))
    if not curves:
        print(f"  [outputs] no azimuth .dat files to overlay for {study_name}"); return None

    all_sph = np.concatenate([c[2] for c in curves])
    rcs_max = np.ceil(np.nanmax(all_sph) / 10) * 10
    rcs_min = rcs_max - 60.0

    fig = plt.figure(figsize=(7.5, 7.5), facecolor="#e8e8e8")
    ax = fig.add_subplot(111, polar=True, facecolor="#e8e8e8")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    max_abs_delta = max(abs(d) for d, _, _ in curves) or 1.0
    cmap = matplotlib.colormaps["coolwarm"]

    def _rcs_to_r(rcs):
        return np.clip((rcs - rcs_min) / (rcs_max - rcs_min), 0.0, 1.0)

    ring_vals = np.linspace(rcs_min, rcs_max, 7)
    ring_angles = np.linspace(0, 2 * np.pi, 361)
    for rv in ring_vals:
        rr = _rcs_to_r(rv)
        ax.plot(ring_angles, np.full_like(ring_angles, rr), color="grey", lw=0.5, zorder=1)
        if rr > 0.05:
            ax.text(np.deg2rad(105), rr, f"{rv:.0f}", ha="left", va="center",
                    fontsize=7, color="dimgrey", zorder=6)
    for sd in range(0, 360, 30):
        ax.plot([np.deg2rad(sd), np.deg2rad(sd)], [0, 1], color="grey", lw=0.5, zorder=1)

    for d, phi_full, sph_full in curves:
        color = "black" if d == 0.0 else cmap(0.5 + 0.5 * d / max_abs_delta)
        r = _rcs_to_r(sph_full)
        t = np.append(np.deg2rad(phi_full), np.deg2rad(phi_full[0]))
        r = np.append(r, r[0])
        ax.plot(t, r, color=color, lw=1.6 if d == 0.0 else 1.0,
                alpha=1.0 if d == 0.0 else 0.85, zorder=5,
                label=f"Δ={d:+.2f}" + ("  (baseline)" if d == 0.0 else ""))

    ax.legend(loc="lower left", bbox_to_anchor=(-0.15, -0.15), fontsize=7.5, framealpha=0.7)
    spokes = {0: "0°\n(nose)", 90: "90°", 180: "180°\n(tail)", 270: "270°"}
    ax.set_xticks(np.deg2rad(list(spokes.keys())))
    ax.set_xticklabels(list(spokes.values()), fontsize=8)
    ax.set_yticks([])
    ax.grid(False)
    ax.spines["polar"].set_visible(False)
    ax.set_ylim(0, 1)
    fig.suptitle(f"{study_name} — Azimuth RCS overlay, all Δ  (TE-z co-pol Sφ, θ=90°)\n"
                 f"scale: {rcs_min:.0f} dBsm (centre) → {rcs_max:.0f} dBsm (rim)",
                 fontsize=10, y=1.0)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="#e8e8e8")
    plt.close(fig)
    print(f"  saved -> {out_path.name}")
    return out_path


def _write_summary_csv(rows, study_name, out_path):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["delta", "tag", "az_mean_TE_dBsm", "frontal_mean_TE_dBsm",
                    "stl_path", "az_dat_path", "frontal_dat_path"])
        for d, e in rows:
            means = e.get("means", {})
            rcs_out = e.get("rcs_outputs", {})
            w.writerow([
                d, e.get("tag"),
                means.get("AZ_TE", ""), means.get("FR_TE", ""),
                e.get("stl_path", ""),
                rcs_out.get("AZ_TE", ""), rcs_out.get("FR_TE", ""),
            ])
    print(f"  saved -> {out_path.name}")


def build_study_outputs(study_name):
    results_root = RESULTS_ROOT / study_name
    rows = load_family(study_name, results_root)
    if not rows:
        print(f"[{study_name}] no completed deltas found under {results_root} — nothing to plot")
        return

    plots_dir = results_root / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    has_baseline = any(d == 0.0 for d, _ in rows)
    print(f"[{study_name}] building plots from {len(rows)} completed deltas "
          f"({'with' if has_baseline else 'WITHOUT'} baseline)")

    _plot_mean_vs_delta(rows, "AZ_TE", study_name, "Mean Azimuth RCS (dBsm)",
                         plots_dir / f"{study_name}_AzimuthMean_vs_delta.png")
    _plot_mean_vs_delta(rows, "FR_TE", study_name, "Mean Frontal-Sector RCS (dBsm)",
                         plots_dir / f"{study_name}_FrontalMean_vs_delta.png")
    _plot_azimuth_polar_overlay(rows, study_name, plots_dir / f"{study_name}_AzimuthPolar_overlay.png")
    _write_summary_csv(rows, study_name, results_root / f"summary_{study_name}.csv")


def discover_studies():
    """Every subfolder of RESULTS_ROOT with its own manifest/ dir, i.e.
    every study rcs_sweep_driver.py's run_parameter() has touched at
    least once. Skips the shared _baseline and _logs housekeeping
    folders (leading underscore)."""
    studies = []
    if not RESULTS_ROOT.is_dir():
        return studies
    for p in sorted(RESULTS_ROOT.iterdir()):
        if not p.is_dir() or p.name.startswith("_"):
            continue
        if (p / "manifest").is_dir():
            studies.append(p.name)
    return studies


if __name__ == "__main__":
    targets = sys.argv[1:] or discover_studies()
    if not targets:
        print(f"No study folders (with a manifest/ dir) found under {RESULTS_ROOT}")
        sys.exit(1)
    print(f"Building outputs for: {', '.join(targets)}\n")
    for study_name in targets:
        build_study_outputs(study_name)