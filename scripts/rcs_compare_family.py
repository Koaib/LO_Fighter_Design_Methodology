# -*- coding: utf-8 -*-
"""
Created on Sat Sep  5 17:06:29 2026

@author: KK

rcs_compare_family.py — standalone RCS sensitivity-study plotting/summary tool.

Decoupled on purpose from rcs_sweep_driver.py's execution: this script
only READS whatever manifest .json files and OpenRCS .dat outputs
already exist on disk (glob-based, exactly like the aero-side
aero_stab_mission_compare_family.py's own load_family()) and (re)builds
three comparison plots + a summary CSV per study:
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

import plot_style

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

def _resolve_manifest_paths(entry, results_root):
    """Rewrites entry["stl_path"]/entry["rcs_outputs"][...] in place from
    RESULTS_ROOT-relative (as rcs_sweep_worker.py now writes them) to
    absolute, resolved against results_root - the study/_baseline
    directory THIS manifest file was just read from, not wherever it was
    originally generated. This is what makes copying the whole
    Results/RCS_SensitivityStudy/ tree to a different machine or clone
    location just work.

    Manifests written before this fix already store absolute paths
    there - os.path.isabs() below leaves those untouched (best-effort;
    they only resolve correctly on the machine that generated them,
    exactly like before this fix existed)."""
    stl_path = entry.get("stl_path")
    if stl_path and not os.path.isabs(stl_path):
        entry["stl_path"] = str(results_root / stl_path)
    for k, v in entry.get("rcs_outputs", {}).items():
        if v and not os.path.isabs(v):
            entry["rcs_outputs"][k] = str(results_root / v)
    return entry


def _load_baseline_manifest():
    """Returns the shared baseline manifest dict, or None if it doesn't
    exist yet or hasn't finished — callers treat None as "no Δ=0 point
    available yet", not as an error."""
    mpath = BASELINE_ROOT / "manifest" / "baseline.json"
    if not mpath.exists():
        return None
    with open(mpath) as f:
        entry = json.load(f)
    if entry.get("status") != "done":
        return None
    return _resolve_manifest_paths(entry, BASELINE_ROOT)


def _delta_from_tag(tag, study_name):
    # tag is built by rcs_sweep_driver.py as f"{study_name}_{d:+.2f}",
    # e.g. "VT_Cant_+3.00" -> strip the "VT_Cant_" prefix -> float("+3.00")
    return float(tag[len(study_name) + 1:])


def _add_absolute_values(rows):
    """
    rows: [(delta, entry), ...] as returned by load_family().
    Returns (rows3, spec_baseline):
      rows3         : [(delta, entry, absolute_value), ...]
      spec_baseline : SWEEP_PARAMS[param_key]["baseline"] for this study's
                      PRIMARY swept parameter, or None if no row in this
                      family has a non-empty parm_overrides yet to derive
                      it from (e.g. only the shared Δ=0 baseline has
                      finished so far).

    absolute_value is parm_overrides[0][4] directly - the actual applied
    value of the primary parameter, i.e. spec["baseline"] + delta (see
    _override() in rcs_sweep_driver.py). The shared baseline entry stores
    parm_overrides=[] (build_baseline_config() applies nothing), so its
    own absolute_value can't be read directly - back-derived instead as
    spec_baseline + 0.0 once spec_baseline is known from any ONE sibling
    row. This is an exact affine identity, not a fit: every row in a
    family shares the same spec_baseline by construction.
    """
    spec_baseline = None
    for d, e in rows:
        overrides = e.get("parm_overrides") or []
        if overrides:
            spec_baseline = overrides[0][4] - d
            break
    rows3 = []
    for d, e in rows:
        overrides = e.get("parm_overrides") or []
        if overrides:
            abs_val = overrides[0][4]
        elif spec_baseline is not None:
            abs_val = spec_baseline + d
        else:
            abs_val = None
        rows3.append((d, e, abs_val))
    return rows3, spec_baseline


def load_family(study_name, results_root):
    """
    [(delta, manifest_dict), ...] sorted by delta, done runs only.
    Glob-based (like aero_stab_mission_compare_family.py's load_family())
    instead of requiring a delta list up front, so this works even if you
    don't remember/pass the exact DELTAS_* list the driver used.

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
        _resolve_manifest_paths(entry, results_root)
        tag = entry.get("tag") or Path(f).stem
        rows.append((_delta_from_tag(tag, study_name), entry))

    if not any(d == 0.0 for d, _ in rows):
        baseline_entry = _load_baseline_manifest()
        if baseline_entry is not None:
            rows.append((0.0, baseline_entry))

    return sorted(rows, key=lambda r: r[0])


# ── plotting ─────────────────────────────────────────────────────────────

def _plot_mean_vs_delta(rows, tag_key, study_name, ylabel, out_path, spec_baseline=None):
    deltas = [d for d, e, _ in rows if tag_key in e.get("means", {})]
    means  = [e["means"][tag_key] for d, e, _ in rows if tag_key in e.get("means", {})]
    if not deltas:
        print(f"  [outputs] no {tag_key} means to plot for {study_name}"); return None, None

    sensitivity = None
    # Needed below BEFORE the trend block now (to normalize into a
    # percent sensitivity), so computed here rather than where it's
    # plotted further down. Real baseline (Δ=0) value when available,
    # else the sweep's own mean as a fallback reference point.
    baseline_val = means[deltas.index(0.0)] if 0.0 in deltas else np.mean(means)

    fig, ax = plt.subplots(figsize=(7, 4.5), facecolor="white")
    ax.set_facecolor("white")
    # Points only, no connecting line: each delta is an independent noisy
    # sample, not a continuous path, so a straight segment between
    # adjacent deltas would imply a continuity that isn't physically
    # there - scatter + the separate fitted trend line below is the
    # correct read here (the trend line is the only line on the chart).
    ax.plot(deltas, means, color="steelblue", marker="o", markersize=7,
            markeredgecolor="white", markeredgewidth=0.8, linestyle="none",
            zorder=3, label="raw")
    if len(deltas) >= 2:
        # Linear trendline: these sweeps are noisy run-to-run (mesh/PO
        # discretization), so a straight-line trend makes the underlying
        # direction legible without deleting any raw point - fit with
        # Theil-Sen (see plot_style.robust_linear_trend()'s own
        # docstring), so the occasional sharp spike (e.g. a specular
        # flash at one delta) barely tilts the line instead of dragging
        # it the way an ordinary least-squares fit would.
        x_trend, y_trend, r2 = plot_style.robust_linear_trend(deltas, means)
        # R² alongside the line (same convention as Excel's own "add
        # trendline") - low R² is a real warning that this parameter's
        # response isn't well-summarized by a straight line at all (e.g.
        # rises then plateaus), not just noisy around one - see
        # plot_style.robust_linear_trend()'s own docstring.
        trend_label = f"linear trend (R²={r2:.2f})" if r2 is not None else "linear trend"
        ax.plot(x_trend, y_trend, color="crimson", lw=2.2, zorder=2, alpha=0.85, label=trend_label)
        # Sensitivity, quantified three ways:
        #  - slope: rate of change per unit delta (this parameter's own
        #    units - degrees, t/c, ...)
        #  - main_effect: the Design-of-Experiments term for what this
        #    line predicts the metric moves by, end to end across THIS
        #    study's actual tested envelope (slope * delta range - the
        #    continuous-sweep analogue of a factorial DOE's "high level
        #    minus low level" effect estimate). Comparable across studies
        #    with different swept units, since it's in the shared OUTPUT
        #    metric's units (dBsm here) - but NOT comparable across
        #    DIFFERENT metrics (dBsm vs lbm vs L/D are incompatible).
        #  - sensitivity_pct: main_effect as a percentage of this
        #    metric's own OBSERVED RANGE across the sweep (max - min of
        #    the raw means, not just the two endpoints) - "what fraction
        #    of everything this metric actually did across the tested
        #    delta range does the trend account for, end to end." NOT
        #    normalized by baseline_val: a metric whose baseline happens
        #    to sit near zero (dBsm and t/c generally don't, but this
        #    guards any that might) would blow the percentage up toward
        #    +-infinity for an ordinary-sized main_effect, since the
        #    denominator is arbitrarily small - normalizing by the
        #    sweep's own spread instead has no such failure mode.
        #    Comparable across different metrics too (unitless).
        slope = (y_trend[1] - y_trend[0]) / (x_trend[1] - x_trend[0]) if x_trend[1] != x_trend[0] else 0.0
        main_effect = y_trend[1] - y_trend[0]
        value_range = max(means) - min(means)
        sensitivity_pct = (main_effect / value_range * 100.0) if value_range else None
        sensitivity = {"slope": slope, "r2": r2, "main_effect": main_effect,
                        "sensitivity_pct": sensitivity_pct,
                        "delta_min": x_trend[0], "delta_max": x_trend[1]}
    if 0.0 in deltas:
        i0 = deltas.index(0.0)
        ax.plot(deltas[i0], means[i0], marker="o", markersize=9,
                markerfacecolor="none", markeredgecolor="crimson", markeredgewidth=1.6,
                zorder=4, label="baseline (Δ=0)")
    ax.axhline(baseline_val, color="grey", lw=0.6, linestyle=":", zorder=1)
    ax.set_xlabel(f"{study_name}  Δ")
    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.set_title(f"{study_name} — {ylabel} vs. Δ")
    ax.legend(fontsize=9)

    if spec_baseline is not None:
        # Secondary top axis: the ABSOLUTE applied value of this study's
        # primary swept parameter (e.g. t/c 0.02-0.06, not just Δ=-0.02..
        # +0.02 around an unstated 0.04 baseline) - exact affine mapping,
        # see _add_absolute_values().
        ax_top = ax.secondary_xaxis(
            "top",
            functions=(lambda x, b=spec_baseline: x + b, lambda x, b=spec_baseline: x - b),
        )
        ax_top.set_xlabel(f"{study_name}  absolute value", fontsize=11)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved -> {out_path.name}")
    return out_path, sensitivity


def _plot_azimuth_polar_overlay(rows, study_name, out_path):
    """All deltas' azimuth cuts (TE-z co-pol = Sph) overlaid on one polar plot."""
    curves = []
    for d, e, a in rows:
        dat_path = e.get("rcs_outputs", {}).get("AZ_TE")
        if not dat_path or not os.path.isfile(dat_path):
            continue
        parsed = _parse_dat(dat_path)
        if not len(parsed["sph"]):
            continue
        phi_full, sph_full = _azimuth_to_full_circle(parsed["phi_vals"], parsed["sph"])
        curves.append((d, phi_full, sph_full, a))
    if not curves:
        print(f"  [outputs] no azimuth .dat files to overlay for {study_name}"); return None

    all_sph = np.concatenate([c[2] for c in curves])
    rcs_max = np.ceil(np.nanmax(all_sph) / 10) * 10
    rcs_min = rcs_max - 60.0

    fig = plt.figure(figsize=(7.5, 7.5), facecolor="#e8e8e8")
    ax = fig.add_subplot(111, polar=True, facecolor="#e8e8e8")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    max_abs_delta = max(abs(d) for d, _, _, _ in curves) or 1.0
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

    for d, phi_full, sph_full, a in curves:
        color = "black" if d == 0.0 else cmap(0.5 + 0.5 * d / max_abs_delta)
        r = _rcs_to_r(sph_full)
        t = np.append(np.deg2rad(phi_full), np.deg2rad(phi_full[0]))
        r = np.append(r, r[0])
        # No per-curve legend entry: with ~20-30 deltas overlaid, a full
        # legend was more clutter than information (each entry's exact
        # abs value is still in summary_<study>.csv). Colour alone
        # (cmap below, mapped to delta via the colorbar) carries the
        # same ordering information far more compactly; only the
        # baseline gets its own callout, via the proxy artist below.
        ax.plot(t, r, color=color, lw=1.6 if d == 0.0 else 1.0,
                alpha=1.0 if d == 0.0 else 0.85, zorder=5)

    norm = matplotlib.colors.Normalize(vmin=-max_abs_delta, vmax=max_abs_delta)
    sm = matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, pad=0.12, shrink=0.65)
    cbar.set_label(f"{study_name}  Δ", fontsize=9)
    baseline_proxy = plt.Line2D([0], [0], color="black", lw=1.6, label="baseline (Δ=0)")
    ax.legend(handles=[baseline_proxy], loc="lower left", bbox_to_anchor=(-0.15, -0.1),
              fontsize=8.5, framealpha=0.7)
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
    fig.savefig(out_path, bbox_inches="tight", facecolor="#e8e8e8")
    plt.close(fig)
    print(f"  saved -> {out_path.name}")
    return out_path


def _write_summary_csv(rows, study_name, out_path):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["delta", "absolute_value", "tag", "az_mean_TE_dBsm", "frontal_mean_TE_dBsm",
                    "stl_path", "az_dat_path", "frontal_dat_path"])
        for d, e, a in rows:
            means = e.get("means", {})
            rcs_out = e.get("rcs_outputs", {})
            w.writerow([
                d, a, e.get("tag"),
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
        return None

    rows3, spec_baseline = _add_absolute_values(rows)

    plots_dir = results_root / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    has_baseline = any(d == 0.0 for d, _ in rows)
    print(f"[{study_name}] building plots from {len(rows)} completed deltas "
          f"({'with' if has_baseline else 'WITHOUT'} baseline)"
          + (f", absolute baseline value={spec_baseline:.4g}" if spec_baseline is not None else
             " (no absolute value yet - no non-baseline delta done)"))

    _, az_sens = _plot_mean_vs_delta(rows3, "AZ_TE", study_name, "Mean Azimuth RCS (dBsm)",
                                       plots_dir / f"{study_name}_AzimuthMean_vs_delta.png", spec_baseline)
    _, fr_sens = _plot_mean_vs_delta(rows3, "FR_TE", study_name, "Mean Frontal-Sector RCS (dBsm)",
                                       plots_dir / f"{study_name}_FrontalMean_vs_delta.png", spec_baseline)
    _plot_azimuth_polar_overlay(rows3, study_name, plots_dir / f"{study_name}_AzimuthPolar_overlay.png")
    _write_summary_csv(rows3, study_name, results_root / f"summary_{study_name}.csv")

    return {
        "study": study_name,
        "az_slope_dBsm_per_delta": az_sens["slope"] if az_sens else None,
        "az_r2": az_sens["r2"] if az_sens else None,
        "az_main_effect_dBsm": az_sens["main_effect"] if az_sens else None,
        "az_sensitivity_pct": az_sens["sensitivity_pct"] if az_sens else None,
        "frontal_slope_dBsm_per_delta": fr_sens["slope"] if fr_sens else None,
        "frontal_r2": fr_sens["r2"] if fr_sens else None,
        "frontal_main_effect_dBsm": fr_sens["main_effect"] if fr_sens else None,
        "frontal_sensitivity_pct": fr_sens["sensitivity_pct"] if fr_sens else None,
        "delta_min": (az_sens or fr_sens)["delta_min"] if (az_sens or fr_sens) else None,
        "delta_max": (az_sens or fr_sens)["delta_max"] if (az_sens or fr_sens) else None,
    }


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


def _write_sensitivity_summary(sensitivity_rows, out_path):
    """One row per study, ranking each by how much its own linear trend
    predicts mean RCS moves across the FULL delta range actually tested.
    Two ways to read the size of that movement:
      *_main_effect_dBsm  - the Design-of-Experiments term for a
        factor's response change from one end of its tested range to
        the other (see plot_style.robust_linear_trend()'s docstring);
        directly comparable ACROSS STUDIES (VT_Cant in degrees vs
        WingThickChord in t/c ratio), since it's in the shared OUTPUT
        metric's units (dBsm here) - but NOT across different metrics.
      *_sensitivity_pct   - the same movement as a percentage of this
        metric's own OBSERVED RANGE across the sweep (max-min of the raw
        means, not the single Δ=0 baseline point) - unitless, so ALSO
        comparable across different metrics (e.g. against
        aero_stab_mission_compare_family.py's own LDmax/SM/fuel
        sensitivity_pct columns). Deliberately NOT normalized by the
        baseline value: a metric whose baseline happens to sit near zero
        would blow a baseline-normalized percentage up toward +-infinity
        for an ordinary-sized change, since the denominator is
        arbitrarily small - normalizing by the sweep's own spread avoids
        that failure mode entirely.
    *_r2 says how much to trust either number for a given study; CAN be
    negative here (see plot_style.robust_linear_trend()'s own docstring
    for exactly why - it's a real, correct result for a parameter with
    no real linear effect, not a bug). Treat r2<=~0 the same as a low
    positive one: this study's numbers aren't a reliable finding for
    that metric. Rows are in the same (alphabetical, by study) order as
    aero_stab_mission_compare_family.py's own sensitivity_summary.csv,
    so the two files' rows line up directly when read side by side."""
    if not sensitivity_rows:
        print("  [outputs] no sensitivity data to summarize"); return
    fieldnames = ["study", "az_slope_dBsm_per_delta", "az_r2", "az_main_effect_dBsm", "az_sensitivity_pct",
                  "frontal_slope_dBsm_per_delta", "frontal_r2", "frontal_main_effect_dBsm", "frontal_sensitivity_pct",
                  "delta_min", "delta_max"]
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in sensitivity_rows:
            w.writerow(row)
    print(f"  saved -> {out_path.name}")


def _save_sensitivity_table_png(sensitivity_rows, out_path):
    """Same rows as _write_sensitivity_summary()'s CSV, rendered as a
    table image - same convention run_openrcs.py's own _save_mean_table()
    already uses for the MeanRCS table, so this drops into a slide the
    same way. Shows sensitivity_pct (not main_effect) as the headline
    number - both are in the CSV, but percent is comparable across
    metrics too (not just across studies), so it's the more useful
    single number for a compact, presentation-ready table. Rows are kept
    in the SAME order they arrive in (alphabetical by study, same as
    discover_studies()) rather than re-sorted by any one column here -
    deliberately, so this table's rows line up directly, one-to-one,
    against aero_stab_mission_compare_family.py's own sensitivity table
    for the same studies (re-sort by whichever column matters for a
    given point in Excel/pandas instead)."""
    if not sensitivity_rows:
        print("  [outputs] no sensitivity data to summarize"); return

    col_labels = ["Study", "Az sensitivity (%)", "Az R²", "Frontal sensitivity (%)", "Frontal R²"]
    cell_data = [
        [r["study"],
         f"{r['az_sensitivity_pct']:+.1f}%" if r["az_sensitivity_pct"] is not None else "N/A",
         f"{r['az_r2']:.2f}" if r["az_r2"] is not None else "N/A",
         f"{r['frontal_sensitivity_pct']:+.1f}%" if r["frontal_sensitivity_pct"] is not None else "N/A",
         f"{r['frontal_r2']:.2f}" if r["frontal_r2"] is not None else "N/A"]
        for r in sensitivity_rows
    ]

    fig, ax = plt.subplots(figsize=(9.5, 1.2 + 0.5 * len(sensitivity_rows)), facecolor="white")
    ax.set_facecolor("white")
    ax.axis("off")

    tbl = ax.table(cellText=cell_data, colLabels=col_labels, cellLoc="center", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.auto_set_column_width(col=list(range(len(col_labels))))
    tbl.scale(1.2, 2.0)

    ax.set_title(
        "RCS Sensitivity Summary — linear-trend sensitivity across each study's own tested Δ range\n"
        "sensitivity = trend's total predicted change end-to-end, as a % of the metric's OWN observed\n"
        "range over the sweep; R² = how well a straight line fits (R²<=~0 means no reliable trend)",
        fontsize=11, pad=14,
    )
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved -> {out_path.name}")


if __name__ == "__main__":
    targets = sys.argv[1:] or discover_studies()
    if not targets:
        print(f"No study folders (with a manifest/ dir) found under {RESULTS_ROOT}")
        sys.exit(1)
    print(f"Building outputs for: {', '.join(targets)}\n")
    sensitivity_rows = []
    for study_name in targets:
        row = build_study_outputs(study_name)
        if row is not None:
            sensitivity_rows.append(row)
    _write_sensitivity_summary(sensitivity_rows, RESULTS_ROOT / "sensitivity_summary.csv")
    _save_sensitivity_table_png(sensitivity_rows, RESULTS_ROOT / "sensitivity_summary.png")