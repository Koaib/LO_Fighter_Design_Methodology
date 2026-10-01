# -*- coding: utf-8 -*-
"""
maneuver_compare_family.py — plots and sensitivity tables for the
maneuver_metrics_extractor.py outputs (Ps at 1g, sustained load factor
n_s, sustained turn rate).

One file per metric per study - aero_stab_mission_compare_family.
plot_metric_by_study() is called directly, wholesale, for each of the
3 new metrics, zero new plotting code - so every <study>_<Metric>_vs_
delta.png this writes is the exact same figure size, fonts/colours
(plot_style), markers, legend entries, trend+R² convention, open
crimson-ringed-circle baseline marker, x-axis-as-absolute-value, dpi
and output folder (Results/AeroStabMissionStudy/Comparisons/) every
other metric in this project already uses - not a combined multi-panel
figure (an earlier version of this script built one; switched to this
because individual per-metric files are what actually drop into slides
one at a time).

R² ONE-LINER (asked for separately): compare_family computes R² as
1 - SS_res/SS_tot of the Theil-Sen trend line against the raw points
(plot_style.robust_linear_trend(), exactly sklearn.metrics.r2_score's
formula) - it goes negative because Theil-Sen is fit for outlier-
robustness, NOT to minimize SS_res, so unlike OLS it has no guarantee
of beating the flat-mean baseline.

Does NOT add entries to plot_style.YLIM_BY_METRIC or edit
aero_stab_mission_compare_family.py's own _YLIM_BY_METRIC_COL for the
3 new metrics (would mean modifying an existing file) - they auto-scale
per study for now. Fine to add fixed ranges there later once real
numbers exist to set them from.
"""
import glob
import json
import os

import matplotlib.pyplot as plt
import pandas as pd

import plot_style
import aero_stab_mission_compare_family as compare_family

RESULTS_ROOT = compare_family.RESULTS_ROOT
OUT_DIR = compare_family.OUT_DIR

# (dataframe column, y-axis label, output file stem) - one entry per
# metric maneuver_metrics_extractor.py writes, each becomes its own
# <study>_<stem>.png via plot_metric_by_study().
METRICS = [
    ("Ps_1g_fpm", "Ps at 1g (ft/min)", "Ps1g_vs_delta"),
    ("n_s", "Sustained load factor n_s (g)", "ns_vs_delta"),
    ("turn_rate_dps", "Sustained turn rate (deg/s)", "TurnRate_vs_delta"),
]


def load_maneuver_family():
    """Every *_maneuver_manifest.json written by maneuver_metrics_
    extractor.py, globbed the same way load_family() elsewhere in this
    project reads manifests - no hardcoded tag/study list."""
    pattern = os.path.join(RESULTS_ROOT, "*", "manifest", "*_maneuver_manifest.json")
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
            "Ps_1g_fpm": r.get("Ps_1g_fpm"),
            "n_s": r.get("n_s"),
            "turn_rate_dps": r.get("turn_rate_dps"),
        })
    return pd.DataFrame(recs)


def write_sensitivity_table(sensitivity_by_metric, out_dir):
    """sensitivity_by_metric: {metric_col: {study: {"slope","r2",
    "main_effect","delta_min","delta_max"}}} - exactly what
    plot_metric_by_study() itself returns as its second value, one dict
    per metric. Same CSV+PNG+markdown convention as rcs_compare_family.
    py's/aero_stab_mission_compare_family.py's own sensitivity tables,
    slope shown in real units via plot_style.delta_unit_for_study() the
    same way those already do."""
    all_studies = sorted(set().union(*[set(d) for d in sensitivity_by_metric.values()])) \
        if sensitivity_by_metric else []
    if not all_studies:
        print("   (no sensitivity data to summarize)")
        return None, None

    rows = []
    for study in all_studies:
        row = {"study": study}
        for metric_col, _, _ in METRICS:
            s = sensitivity_by_metric.get(metric_col, {}).get(study)
            row[f"{metric_col}_slope"] = s["slope"] if s else None
            row[f"{metric_col}_r2"] = s["r2"] if s else None
            row[f"{metric_col}_main_effect"] = s["main_effect"] if s else None
        rows.append(row)

    csv_path = os.path.join(out_dir, "maneuver_sensitivity_summary.csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    print(f"✅ Maneuver sensitivity summary CSV: {csv_path}")

    col_labels = ["Study", "Ps_1g slope (fpm)", "Ps_1g R²", "n_s slope",
                  "n_s R²", "Turn rate slope (dps)", "Turn rate R²"]
    cell_data = []
    md_lines = ["| Study | Ps_1g slope (fpm) | Ps_1g R2 | n_s slope | n_s R2 | "
                "Turn rate slope (dps) | Turn rate R2 |", "|---|---|---|---|---|---|---|"]
    for row in rows:
        unit_label, unit_scale = plot_style.delta_unit_for_study(row["study"])

        def fmt(v, sig):
            return "N/A" if v is None else f"{v * unit_scale:+.{sig}f}/{unit_label}"

        def fmt_r2(v):
            return "N/A" if v is None else f"{v:.2f}"

        ps_s, ps_r2 = fmt(row["Ps_1g_fpm_slope"], 1), fmt_r2(row["Ps_1g_fpm_r2"])
        ns_s, ns_r2 = fmt(row["n_s_slope"], 3), fmt_r2(row["n_s_r2"])
        tr_s, tr_r2 = fmt(row["turn_rate_dps_slope"], 3), fmt_r2(row["turn_rate_dps_r2"])
        cell_data.append([row["study"], ps_s, ps_r2, ns_s, ns_r2, tr_s, tr_r2])
        md_lines.append(f"| {row['study']} | {ps_s} | {ps_r2} | {ns_s} | {ns_r2} | {tr_s} | {tr_r2} |")

    fig, ax = plt.subplots(figsize=(12.5, 1.2 + 0.5 * len(rows)), facecolor="white")
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

    print("\n" + "\n".join(md_lines))
    return csv_path, png_path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = load_maneuver_family()
    print(f"Found {len(rows)} maneuver manifest(s).")
    if not rows:
        print("Nothing to plot - run maneuver_metrics_extractor.py first.")
        raise SystemExit(0)

    df = _maneuver_dataframe(rows)
    print(f"{len(df)} variant(s) with done status and usable fields.")

    files_written = []
    sensitivity_by_metric = {}
    for metric_col, ylabel, file_stem in METRICS:
        saved, sens = compare_family.plot_metric_by_study(df, metric_col, ylabel, OUT_DIR, file_stem)
        files_written += saved
        sensitivity_by_metric[metric_col] = sens

    csv_path, png_path = write_sensitivity_table(sensitivity_by_metric, OUT_DIR)
    if csv_path:
        files_written += [csv_path, png_path]

    print(f"\nFiles created ({len(files_written)}):")
    for p in files_written:
        print(f"  {p}")


if __name__ == "__main__":
    main()
