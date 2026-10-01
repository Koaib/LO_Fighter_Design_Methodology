# -*- coding: utf-8 -*-
"""
maneuver_compare_family.py — plots and sensitivity tables for the
maneuver_metrics_extractor.py outputs (Ps at 1g, sustained load factor
n_s, sustained turn rate), styled identically to
aero_stab_mission_compare_family.py/rcs_compare_family.py: same figure
size, fonts/colours (via plot_style), markers, legend entries (raw
points, linear trend with R², open crimson-ringed-circle baseline
marker), x-axis = absolute parameter value, same dpi, same output
folder (Results/AeroStabMissionStudy/Comparisons/), same file-naming
convention.

Where this reuses the EXISTING per-metric plot wholesale (nothing new
to draw), it just calls aero_stab_mission_compare_family.
plot_metric_by_study() directly - zero new plotting code. Where the
brief asks for a layout that function can't produce (several metrics
sharing ONE multi-panel figure), a small _panel() helper reproduces
that exact same per-panel convention (same marker/colour/trend/baseline
calls), since one-metric-per-file isn't optional there.

R² ONE-LINER (asked for separately, now stale - kept for the history):
compare_family USED TO compute R² as 1 - SS_res/SS_tot of a Theil-Sen
trend line against the raw points (plot_style.robust_linear_trend()),
which could go negative because Theil-Sen is fit for outlier-
robustness, NOT to minimize SS_res, so unlike OLS it had no guarantee
of beating the flat-mean baseline. As of the fit-alignment fix below,
every panel in THIS file uses plot_style.linear_fit() (ordinary least
squares) instead, which always lands in [0, 1] and always passes
through the panel's own (x.mean(), y.mean()) - see that function's own
docstring. rcs_compare_family.py was NOT changed and still uses
Theil-Sen, so an RCS panel's R² can still be negative; only the two
files this fix touched (aero_stab_mission_compare_family.py and this
one) switched to OLS.

Does NOT modify plot_style.YLIM_BY_METRIC or aero_stab_mission_compare_
family.py's own _YLIM_BY_METRIC_COL (would mean editing an existing
file) - the 3 new metrics here auto-scale per study instead of using a
fixed cross-study range. Fine to add fixed ranges there later once
real numbers exist to set them from.
"""
import argparse
import glob
import json
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import plot_style
import aero_stab_mission_compare_family as compare_family
import rcs_compare_family as rcs_family

RESULTS_ROOT = compare_family.RESULTS_ROOT          # Results/AeroStabMissionStudy
OUT_DIR = compare_family.OUT_DIR                    # .../Comparisons - shared with the existing aero outputs,
                                                      # new filenames only, nothing existing is overwritten
TURN_METRIC_LABELS = {
    "turn_rate": ("turn_rate_dps", "Sustained turn rate (deg/s)"),
    "n_s": ("n_s", "Sustained load factor (g)"),
}


def load_maneuver_family():
    """Every *_maneuver_manifest.json written by maneuver_metrics_
    extractor.py, globbed the same way load_family() elsewhere in this
    project reads manifests - no hardcoded tag/study list. Reads from
    maneuver/, a dir SIBLING to manifest/ (matching aero/, stability/,
    mission/'s own convention) - NOT manifest/ itself, which would let
    aero_stab_mission_compare_family.load_family()'s own unscoped
    manifest/*.json glob sweep these files back up as if they were
    additional aero manifests on the next run (confirmed: this caused a
    real, serious self-corruption bug - see maneuver_metrics_extractor.
    py's own _manifest_dir_for() docstring for the full mechanism)."""
    pattern = os.path.join(RESULTS_ROOT, "*", "maneuver", "*_maneuver_manifest.json")
    rows = []
    for path in sorted(glob.glob(pattern)):
        with open(path) as f:
            rows.append(json.load(f))
    return rows


def _maneuver_dataframe(rows):
    """Flat DataFrame with the same study/delta/absolute_value column
    names aero_stab_mission_compare_family.plot_metric_by_study() itself
    expects, so that function can be called on this data directly."""
    recs = []
    for r in rows:
        if r.get("status") != "done":
            continue
        recs.append({
            "study": r["study"], "delta": r["delta"], "tag": r["tag"],
            "absolute_value": r.get("parameter_value"),
            "Ps_1g_fpm": r.get("Ps_1g_fpm"), "Ps_1g_ms": r.get("Ps_1g_ms"),
            "n_s": r.get("n_s"), "turn_rate_dps": r.get("turn_rate_dps"),
        })
    return pd.DataFrame(recs)


def _panel(ax, x, y, baseline_x, baseline_y, ylabel, title, ylim=None):
    """One scatter+trend+baseline panel - same marker/colour/trend-line/
    baseline-marker convention as aero_stab_mission_compare_family.
    plot_metric_by_study()'s own per-panel code, factored out here since
    this script needs MULTI-panel figures that one-metric-per-file
    function can't produce. Returns (r2, slope, main_effect) for the
    sensitivity table, or (None, None, None) if <2 points. ylim, when
    given, is a fixed (lo, hi) range applied regardless of this panel's
    own data - same "equal scale per metric, across every study" intent
    as plot_style.YLIM_BY_METRIC already applies to every other metric
    in this project (see that dict for why: auto-scaling makes the same
    metric look like a different scale from one study's plot to the
    next, which makes a flat baseline line look like it "moves" purely
    from the axis rescaling)."""
    # x/y are the EXACT arrays handed to both the scatter call below AND
    # the fit call right after - one pair of variables, used twice, so
    # the plotted points and the fitted points can never drift apart.
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ax.plot(x, y, "o", ms=7, color="steelblue", markeredgecolor="white",
             markeredgewidth=0.8, zorder=3, label="raw")
    r2 = slope = main_effect = None
    fit = plot_style.linear_fit(x, y)
    if fit is not None:
        slope, intercept, r2, xs, ys, n = fit
        # Line drawn from the fit's own slope/intercept over the fit's
        # own [xs.min(), xs.max()] - guaranteed to sit exactly on the
        # OLS fit for these points, not a separately-sourced range.
        x_trend = np.array([xs.min(), xs.max()])
        y_trend = slope * x_trend + intercept
        trend_label = f"linear trend (R²={r2:.2f})" if r2 is not None else "linear trend"
        ax.plot(x_trend, y_trend, color="crimson", lw=2.2, zorder=2, alpha=0.85, label=trend_label)
        main_effect = y_trend[1] - y_trend[0]
    if baseline_x is not None:
        ax.plot(baseline_x, baseline_y, marker="o", markersize=9, markerfacecolor="none",
                 markeredgecolor="crimson", markeredgewidth=1.6, zorder=4, label="baseline (delta=0)")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=10)
    ax.grid(True, ls="--", alpha=0.6)
    ax.legend(fontsize=8)
    if ylim is not None:
        ax.set_ylim(*ylim)
    return r2, slope, main_effect


def _baseline_xy(sub, col):
    base = sub[sub["delta"].abs() < 1e-9]
    if base.empty:
        return None, None
    return float(base["absolute_value"].iloc[0]), float(base[col].iloc[0])


# ── (a) one 3-panel figure per study: Ps_1g, n_s, turn_rate ────────────

def plot_maneuver_panels(df, out_dir):
    saved = []
    sensitivity_by_study = {}
    for study in sorted(df["study"].dropna().unique()):
        sub = df[df["study"] == study].sort_values("delta")
        if sub.empty:
            continue
        fig, axes = plt.subplots(1, 3, figsize=(18, 4.5))

        bx, by = _baseline_xy(sub, "Ps_1g_fpm")
        r2_ps, slope_ps, me_ps = _panel(
            axes[0], sub["absolute_value"], sub["Ps_1g_fpm"], bx, by,
            "Ps at 1g (ft/min)", f"{study} — Ps at 1g vs. absolute value",
            ylim=plot_style.YLIM_BY_METRIC["ps_1g"])

        bx, by = _baseline_xy(sub, "n_s")
        r2_ns, slope_ns, me_ns = _panel(
            axes[1], sub["absolute_value"], sub["n_s"], bx, by,
            "Sustained n_s (g)", f"{study} — n_s vs. absolute value",
            ylim=plot_style.YLIM_BY_METRIC["n_s"])

        bx, by = _baseline_xy(sub, "turn_rate_dps")
        r2_tr, slope_tr, me_tr = _panel(
            axes[2], sub["absolute_value"], sub["turn_rate_dps"], bx, by,
            "Sustained turn rate (deg/s)", f"{study} — turn rate vs. absolute value",
            ylim=plot_style.YLIM_BY_METRIC["turn_rate"])

        fig.suptitle(f"{study} — Maneuver metrics (Mach 0.6, 15,000 ft, full afterburner)", fontsize=12)
        fig.tight_layout()
        out_path = os.path.join(out_dir, f"{study}_maneuver_vs_param.png")
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"   ✅ {out_path}")
        saved.append(out_path)

        sensitivity_by_study[study] = {
            "Ps_1g_slope_per_delta": slope_ps, "Ps_1g_r2": r2_ps, "Ps_1g_main_effect": me_ps,
            "n_s_slope_per_delta": slope_ns, "n_s_r2": r2_ns, "n_s_main_effect": me_ns,
            "turn_rate_slope_per_delta": slope_tr, "turn_rate_r2": r2_tr, "turn_rate_main_effect": me_tr,
            "n_points": len(sub),
            "Ps_1g_baseline_fpm": float(sub.loc[sub["delta"].abs() < 1e-9, "Ps_1g_fpm"].iloc[0])
                if (sub["delta"].abs() < 1e-9).any() else None,
            "n_s_baseline": float(sub.loc[sub["delta"].abs() < 1e-9, "n_s"].iloc[0])
                if (sub["delta"].abs() < 1e-9).any() else None,
            "turn_rate_baseline_dps": float(sub.loc[sub["delta"].abs() < 1e-9, "turn_rate_dps"].iloc[0])
                if (sub["delta"].abs() < 1e-9).any() else None,
            "delta_min": float(sub["delta"].min()), "delta_max": float(sub["delta"].max()),
        }
    return saved, sensitivity_by_study


# ── (b) combined metrics figure: top RCS, bottom turn-metric/Ps/SM/Fuel ─

def _rcs_means_by_study_delta(study):
    """(delta -> (az_mean, frontal_mean)) for one study, read straight
    from the EXISTING RCS manifests - same load_family()/_add_absolute_
    values() rcs_compare_family.py itself uses, so this is the exact
    same data its own plots are built from, not a re-derivation."""
    out = {}
    results_root = rcs_family.RESULTS_ROOT / study
    if not results_root.is_dir():
        return out
    rows = rcs_family.load_family(study, results_root)
    rows3, _ = rcs_family._add_absolute_values(rows)
    for d, e, a in rows3:
        means = e.get("means", {})
        out[d] = (a, means.get("AZ_TE"), means.get("FR_TE"))
    return out


def plot_combined_metrics_figure(maneuver_df, turn_metric, out_dir):
    """Per-study dashboard: top row = mean Az RCS, mean Frontal RCS
    (existing RCS manifests); bottom row = <turn_metric>, Ps at 1g
    (existing maneuver manifests), static margin, residual fuel
    (existing aero manifests) - everything one parameter needs on one
    image, same idea as the per-parameter slide layout already used
    elsewhere in this project."""
    turn_col, turn_label = TURN_METRIC_LABELS[turn_metric]

    # Same cruise condition aero_stab_mission_compare_family.py's own
    # __main__ uses for its CD0/K/L-D-max/SM/fuel columns (CRUISE_MACH,
    # CRUISE_ALTITUDE_FT are local to that block, not module attributes,
    # so the values are repeated here rather than imported).
    aero_done, _ = compare_family.load_family()
    aero_df = pd.DataFrame(compare_family.build_summary_rows(aero_done, 0.6, 30000.0))

    saved = []
    for study in sorted(maneuver_df["study"].dropna().unique()):
        sub_m = maneuver_df[maneuver_df["study"] == study].sort_values("delta")
        sub_a = aero_df[aero_df["study"] == study].sort_values("delta") if not aero_df.empty else pd.DataFrame()
        rcs_by_delta = _rcs_means_by_study_delta(study)
        if not rcs_by_delta and sub_a.empty:
            continue

        # GridSpec, not plt.subplots(2,4): the top row has only 2 panels
        # (RCS) against the bottom row's 4 (turn metric, Ps_1g, SM, fuel) -
        # each top panel spans 2 of the 4 columns so the row fills its
        # full width instead of leaving the right half blank.
        fig = plt.figure(figsize=(20, 9))
        gs = fig.add_gridspec(2, 4)
        ax_az = fig.add_subplot(gs[0, 0:2])
        ax_fr = fig.add_subplot(gs[0, 2:4])
        ax_turn = fig.add_subplot(gs[1, 0])
        ax_ps = fig.add_subplot(gs[1, 1])
        ax_sm = fig.add_subplot(gs[1, 2])
        ax_fuel = fig.add_subplot(gs[1, 3])

        az_x = [v[0] for v in rcs_by_delta.values() if v[0] is not None and v[1] is not None]
        az_y = [v[1] for v in rcs_by_delta.values() if v[0] is not None and v[1] is not None]
        fr_x = [v[0] for v in rcs_by_delta.values() if v[0] is not None and v[2] is not None]
        fr_y = [v[2] for v in rcs_by_delta.values() if v[0] is not None and v[2] is not None]
        az_bx, az_by = (rcs_by_delta.get(0.0, (None, None, None))[0], rcs_by_delta.get(0.0, (None, None, None))[1])
        fr_bx, fr_by = (rcs_by_delta.get(0.0, (None, None, None))[0], rcs_by_delta.get(0.0, (None, None, None))[2])
        _panel(ax_az, az_x, az_y, az_bx, az_by, "Mean Azimuth RCS (dBsm)", f"{study} — Mean Az RCS",
               ylim=plot_style.YLIM_BY_METRIC["az_rcs"])
        _panel(ax_fr, fr_x, fr_y, fr_bx, fr_by, "Mean Frontal RCS (dBsm)", f"{study} — Mean Frontal RCS",
               ylim=plot_style.YLIM_BY_METRIC["frontal_rcs"])

        bx, by = _baseline_xy(sub_m, turn_col)
        _panel(ax_turn, sub_m["absolute_value"], sub_m[turn_col], bx, by, turn_label, f"{study} — {turn_label}",
               ylim=plot_style.YLIM_BY_METRIC[turn_metric])
        bx, by = _baseline_xy(sub_m, "Ps_1g_fpm")
        _panel(ax_ps, sub_m["absolute_value"], sub_m["Ps_1g_fpm"], bx, by, "Ps at 1g (ft/min)", f"{study} — Ps at 1g",
               ylim=plot_style.YLIM_BY_METRIC["ps_1g"])

        if not sub_a.empty:
            bx = float(sub_a.loc[sub_a["delta"].abs() < 1e-9, "absolute_value"].iloc[0]) \
                if (sub_a["delta"].abs() < 1e-9).any() else None
            by_sm = float(sub_a.loc[sub_a["delta"].abs() < 1e-9, "SM_cruise"].iloc[0]) \
                if (sub_a["delta"].abs() < 1e-9).any() else None
            by_fuel = float(sub_a.loc[sub_a["delta"].abs() < 1e-9, "residual_fuel_lbm"].iloc[0]) \
                if (sub_a["delta"].abs() < 1e-9).any() else None
            _panel(ax_sm, sub_a["absolute_value"], sub_a["SM_cruise"], bx, by_sm,
                   "Static margin", f"{study} — Static margin", ylim=plot_style.YLIM_BY_METRIC["static_margin"])
            _panel(ax_fuel, sub_a["absolute_value"], sub_a["residual_fuel_lbm"], bx, by_fuel,
                   "Residual fuel (lbm)", f"{study} — Residual fuel", ylim=plot_style.YLIM_BY_METRIC["residual_fuel"])
        else:
            ax_sm.axis("off"); ax_fuel.axis("off")

        fig.suptitle(f"{study} — RCS + Performance metrics (--turn-metric={turn_metric})", fontsize=13)
        fig.tight_layout()
        out_path = os.path.join(out_dir, f"{study}_metrics_combined.png")
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"   ✅ {out_path}")
        saved.append(out_path)
    return saved


# ── (c) sensitivity summary table (CSV + PNG + printed markdown) ───────

def write_sensitivity_table(sensitivity_by_study, out_dir):
    rows = []
    for study, s in sorted(sensitivity_by_study.items()):
        unit_label, unit_scale = plot_style.delta_unit_for_study(study)
        rows.append({
            "study": study, "n_points": s["n_points"],
            "delta_min": s["delta_min"], "delta_max": s["delta_max"],
            "Ps_1g_slope": s["Ps_1g_slope_per_delta"], "Ps_1g_r2": s["Ps_1g_r2"],
            "Ps_1g_baseline_fpm": s["Ps_1g_baseline_fpm"],
            "n_s_slope": s["n_s_slope_per_delta"], "n_s_r2": s["n_s_r2"],
            "n_s_baseline": s["n_s_baseline"],
            "turn_rate_slope": s["turn_rate_slope_per_delta"], "turn_rate_r2": s["turn_rate_r2"],
            "turn_rate_baseline_dps": s["turn_rate_baseline_dps"],
            "slope_unit": unit_label,
        })
    if not rows:
        print("   (no sensitivity data to summarize)")
        return None, None

    csv_path = os.path.join(out_dir, "maneuver_sensitivity_summary.csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    print(f"✅ Maneuver sensitivity summary CSV: {csv_path}")

    col_labels = ["Study", "Ps_1g slope (fpm)", "Ps_1g R²", "n_s slope",
                  "n_s R²", "Turn rate slope (dps)", "Turn rate R²", "N pts"]
    cell_data = []
    md_lines = ["| Study | Ps_1g slope (fpm) | Ps_1g R2 | n_s slope | n_s R2 | "
                "Turn rate slope (dps) | Turn rate R2 | N pts |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        unit_label, unit_scale = plot_style.delta_unit_for_study(r["study"])

        def fmt(v, sig=3):
            return "N/A" if v is None else f"{v * unit_scale:+.{sig}f}/{unit_label}"

        def fmt_r2(v):
            return "N/A" if v is None else f"{v:.2f}"

        cell_data.append([r["study"], fmt(r["Ps_1g_slope"], 1), fmt_r2(r["Ps_1g_r2"]),
                           fmt(r["n_s_slope"], 3), fmt_r2(r["n_s_r2"]),
                           fmt(r["turn_rate_slope"], 3), fmt_r2(r["turn_rate_r2"]), str(r["n_points"])])
        md_lines.append(f"| {r['study']} | {fmt(r['Ps_1g_slope'], 1)} | {fmt_r2(r['Ps_1g_r2'])} | "
                         f"{fmt(r['n_s_slope'], 3)} | {fmt_r2(r['n_s_r2'])} | "
                         f"{fmt(r['turn_rate_slope'], 3)} | {fmt_r2(r['turn_rate_r2'])} | {r['n_points']} |")

    fig, ax = plt.subplots(figsize=(13, 1.2 + 0.5 * len(rows)), facecolor="white")
    ax.set_facecolor("white")
    ax.axis("off")
    tbl = ax.table(cellText=cell_data, colLabels=col_labels, cellLoc="center", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.auto_set_column_width(col=list(range(len(col_labels))))
    tbl.scale(1.15, 2.0)
    ax.set_title(
        "Maneuver Sensitivity Summary — linear-trend slope at Mach 0.6 / 15,000 ft / full afterburner\n"
        "slope = trend's rate of change in real units, per degree or per 0.01 Δ(t/c); "
        "R² = how well a straight line fits (R²<=~0 means no reliable trend)",
        fontsize=10.5, pad=14)
    fig.tight_layout()
    png_path = os.path.join(out_dir, "maneuver_sensitivity_summary.png")
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)
    print(f"✅ Maneuver sensitivity summary PNG: {png_path}")

    md = "\n".join(md_lines)
    print("\n" + md)
    return csv_path, png_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--turn-metric", choices=["turn_rate", "n_s"], default="turn_rate")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    rows = load_maneuver_family()
    print(f"Found {len(rows)} maneuver manifest(s).")
    if not rows:
        print("Nothing to plot - run maneuver_metrics_extractor.py first.")
        raise SystemExit(0)

    df = _maneuver_dataframe(rows)
    print(f"{len(df)} variant(s) with done status and usable fields.")

    files_written = []
    saved_panels, sensitivity_by_study = plot_maneuver_panels(df, OUT_DIR)
    files_written += saved_panels

    saved_combined = plot_combined_metrics_figure(df, args.turn_metric, OUT_DIR)
    files_written += saved_combined

    csv_path, png_path = write_sensitivity_table(sensitivity_by_study, OUT_DIR)
    if csv_path:
        files_written += [csv_path, png_path]

    print(f"\nFiles created ({len(files_written)}):")
    for p in files_written:
        print(f"  {p}")


if __name__ == "__main__":
    main()
