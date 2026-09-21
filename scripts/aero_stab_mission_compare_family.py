# -*- coding: utf-8 -*-
"""
aero_stab_mission_compare_family.py — aggregates every finished config's
manifest JSON (written by aero_stab_mission_worker.py) into one combined
summary CSV plus diagnostic plots, faceted by study.

Decoupled from the driver/worker the same way rcs_compare_family.py is
decoupled from rcs_sweep_driver.py/rcs_sweep_worker.py: run this any
time, as often as you want, against whatever manifests already exist on
disk - it never re-runs anything itself.

One row per finished config in the combined CSV, at the CRUISE
condition (cruise_mach/cruise_altitude_ft, matching whatever the driver
actually swept - not hardcoded here) specifically, since that's the
mission-relevant flight point for a shaping trade-off - every config's
full 9-point aero/stability detail is still sitting in its own manifest
JSON under Results/AeroStabMissionStudy/<study_name>/manifest/ (or
_baseline/manifest/ for the shared Delta=0 run) if a deeper look at a
specific point/config is ever needed.

Mirrors rcs_compare_family.py's own baseline handling: aero_stab_
mission_driver.py's build_study_configs() skips d==0.0 and relies on
one shared run_baseline() result instead (see that file's module
docstring) - load_family() below splices that single manifest in as
each discovered study's own Delta=0 anchor point, relabeled to that
study so the faceted-by-study plots/CSV group it correctly instead of
showing a stray 6th "baseline" facet.
"""
import glob
import json
import os

import matplotlib.pyplot as plt
import plot_style
import pandas as pd

RESULTS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Results", "AeroStabMissionStudy")
BASELINE_MANIFEST = os.path.join(RESULTS_ROOT, "_baseline", "manifest", "baseline.json")
OUT_DIR = os.path.join(RESULTS_ROOT, "Comparisons")


def discover_studies():
    """Every subfolder of RESULTS_ROOT with its own manifest/ dir, i.e.
    every study aero_stab_mission_driver.py's run_study() has touched at
    least once. Skips the shared _baseline/_logs housekeeping folders
    (leading underscore) and Comparisons (this script's own output)."""
    studies = []
    if not os.path.isdir(RESULTS_ROOT):
        return studies
    for name in sorted(os.listdir(RESULTS_ROOT)):
        path = os.path.join(RESULTS_ROOT, name)
        if not os.path.isdir(path) or name.startswith("_") or name == "Comparisons":
            continue
        if os.path.isdir(os.path.join(path, "manifest")):
            studies.append(name)
    return studies


def _resolve_manifest_paths(entry, results_root):
    """Rewrites entry["aero_dir"]/entry["stability_plot_path"]/
    entry["mission_md_path"]/each aero_points[*]["csv"] in place from
    RESULTS_ROOT-relative (as aero_stab_mission_worker.py now writes
    them) to absolute, resolved against results_root - the study/
    _baseline directory THIS manifest file was just read from, not
    wherever it was originally generated. Makes copying the whole
    Results/AeroStabMissionStudy/ tree to a different machine or clone
    location just work. Manifests written before this fix already store
    absolute paths there - os.path.isabs() below leaves those untouched
    (best-effort; they only resolve on the machine that generated them,
    exactly like before this fix existed)."""
    for key in ("aero_dir", "stability_plot_path", "mission_md_path"):
        v = entry.get(key)
        if v and not os.path.isabs(v):
            entry[key] = os.path.join(results_root, v)
    for pt in entry.get("aero_points", []):
        v = pt.get("csv")
        if v and not os.path.isabs(v):
            pt["csv"] = os.path.join(results_root, v)
    return entry


def _load_baseline_manifest():
    """Returns the shared baseline manifest dict, or None if it doesn't
    exist yet or hasn't finished - callers treat None as "no Delta=0
    point available yet", not as an error. Mirrors rcs_compare_family.
    py's own _load_baseline_manifest()."""
    if not os.path.exists(BASELINE_MANIFEST):
        return None
    with open(BASELINE_MANIFEST) as f:
        entry = json.load(f)
    if entry.get("status") != "done":
        return None
    return _resolve_manifest_paths(entry, os.path.dirname(os.path.dirname(BASELINE_MANIFEST)))


def _splice_baseline_for_study(baseline_entry, study_name):
    """Shallow copy of the shared baseline entry, relabeled as THIS
    study's own Delta=0 point (same physical aircraft/analysis either
    way - see module docstring). Relabeling instead of reusing the dict
    directly matters because build_summary_rows()/plot_metric_by_study()
    group rows by e["study"]; without this every study's baseline point
    would collide into one stray "baseline" facet instead of anchoring
    each study's own panel."""
    spliced = dict(baseline_entry)
    spliced["study"] = study_name
    spliced["tag"] = f"{study_name}_+0.00"
    return spliced


def load_family(study_names=None):
    """Reads every manifest JSON across every (or the given) study
    folder(s), splices the shared baseline in as each study's own
    Delta=0 anchor (unless that study somehow already has its own
    delta==0.0 entry), and returns (done_entries, other_entries).
    other_entries (status != "done") are returned too, not silently
    dropped, so a caller can report what's still missing/failed rather
    than just seeing a shorter-than-expected table."""
    study_names = discover_studies() if study_names is None else study_names
    baseline_entry = _load_baseline_manifest()

    done, other = [], []
    for study_name in study_names:
        manifest_glob = os.path.join(RESULTS_ROOT, study_name, "manifest", "*.json")
        has_zero = False
        for path in sorted(glob.glob(manifest_glob)):
            with open(path) as f:
                entry = json.load(f)
            if entry.get("status") == "done":
                _resolve_manifest_paths(entry, os.path.join(RESULTS_ROOT, study_name))
                done.append(entry)
                if entry.get("delta") == 0.0:
                    has_zero = True
            else:
                other.append(entry)
        if not has_zero and baseline_entry is not None:
            done.append(_splice_baseline_for_study(baseline_entry, study_name))
    return done, other


def _point_at(points, mach, alt_ft, tol=1e-6):
    for p in points:
        if abs(p["mach"] - mach) < tol and abs(p["alt_ft"] - alt_ft) < tol:
            return p
    return None


def _point_interp(points, mach, alt_ft, tol=1e-6):
    """Falls back to linear interpolation in altitude (at an EXACT mach
    match only - the grid's own mach list, so no mach-axis blending is
    ever needed for a cruise_mach that's actually swept) when
    cruise_altitude_ft isn't itself a grid altitude. CD0/K are blended
    directly and LD_max_theoretical is recomputed from the blended CD0/K
    (not itself linearly blended - it's a nonlinear function of them).
    Returns None if cruise_mach/cruise_altitude_ft can't be bracketed at
    all (e.g. cruise_mach isn't a grid mach), same as _point_at()'s own
    "no match" behavior."""
    exact = _point_at(points, mach, alt_ft, tol)
    if exact is not None:
        return exact
    at_m = sorted((p for p in points if abs(p["mach"] - mach) < tol), key=lambda p: p["alt_ft"])
    lo = [p for p in at_m if p["alt_ft"] < alt_ft]
    hi = [p for p in at_m if p["alt_ft"] > alt_ft]
    if not lo or not hi:
        return None
    a, b = lo[-1], hi[0]
    w = (alt_ft - a["alt_ft"]) / (b["alt_ft"] - a["alt_ft"])
    out = dict(a)
    for k, va in a.items():
        vb = b.get(k)
        if k in ("mach", "alt_ft"):
            continue
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            out[k] = va + w * (vb - va)
    out["alt_ft"] = alt_ft
    if out.get("CD0") and out.get("K"):
        out["LD_max_theoretical"] = 1.0 / (2.0 * (out["CD0"] * out["K"]) ** 0.5)
    return out


def build_summary_rows(entries, cruise_mach, cruise_altitude_ft):
    # Back-derive each study's own spec_baseline (the swept primary
    # parameter's un-swept value) from any ONE of that study's non-
    # baseline rows. Needed because the spliced-in shared baseline row
    # (see _splice_baseline_for_study()) carries the ORIGINAL
    # parm_overrides=[] from build_baseline_config() - it's literally the
    # untouched aircraft, nothing was applied - so its own absolute_value
    # can't be read directly the way every other row's can. This is an
    # exact affine identity (absolute_value = spec_baseline + delta for
    # every non-baseline row of a study), not a fit: any one sibling
    # recovers the same constant.
    spec_baseline_by_study = {}
    for e in entries:
        overrides = e.get("parm_overrides") or []
        if overrides and e["study"] not in spec_baseline_by_study:
            spec_baseline_by_study[e["study"]] = overrides[0][4] - e["delta"]

    rows = []
    for e in entries:
        aero_pt = _point_interp(e.get("aero_points", []), cruise_mach, cruise_altitude_ft)
        stab_pt = _point_interp(e.get("stability_points", []), cruise_mach, cruise_altitude_ft)
        mr = e.get("mission_results", {})
        # Absolute applied value of the PRIMARY swept parameter (index 4
        # of its override tuple = spec["baseline"] + delta - see
        # aero_stab_mission_driver.py's _override()/build_study_configs()).
        overrides = e.get("parm_overrides") or []
        if overrides:
            absolute_value = overrides[0][4]
        else:
            spec_baseline = spec_baseline_by_study.get(e["study"])
            absolute_value = (spec_baseline + e["delta"]) if spec_baseline is not None else None
        rows.append({
            "study": e["study"], "delta": e["delta"], "tag": e["tag"],
            "absolute_value": absolute_value,
            "wing_area_ft2": e.get("wing_area_ft2"), "wing_aspect_ratio": e.get("wing_aspect_ratio"),
            "CD0_cruise": aero_pt["CD0"] if aero_pt else None,
            "K_cruise": aero_pt["K"] if aero_pt else None,
            "LD_max_theoretical_cruise": aero_pt["LD_max_theoretical"] if aero_pt else None,
            "SM_cruise": stab_pt["SM"] if stab_pt else None,
            "SM_R2_cruise": stab_pt["SM_R2"] if stab_pt else None,
            "climb_completed": mr.get("climb_completed"),
            "feasible": mr.get("feasible"),
            "climb_throttle_used": mr.get("climb_throttle_used"),
            "fuel_required_lbm": mr.get("fuel_required_lbm"),
            "residual_fuel_lbm": mr.get("residual_fuel_lbm"),
            "total_range_nmi": mr.get("total_range_nmi"),
            "failure_reason": mr.get("failure_reason", ""),
        })
    return rows


def plot_metric_by_study(df, metric, ylabel, out_dir, file_stem):
    """Saves ONE individual figure per study (not a single combined row
    of subplots) - so a slide-per-parameter deck can embed each study's
    own panel at full size, alongside that same parameter's RCS plots
    (rcs_compare_family.py already saves those individually, per study).

    Each panel also overlays plot_style.robust_linear_trend()'s straight-
    line trendline on top of the raw delta-sweep line: these sweeps are
    noisy run-to-run (VSPAero/meshing sensitivity to shaping deltas, not
    measurement error), so a linear trend makes the underlying direction
    legible without deleting any raw point - fit with Theil-Sen so it
    downweights outliers (a lone severe spike barely tilts it) instead
    of requiring them removed first.

    Returns (saved, sensitivity_by_study): saved is the list of file
    paths written; sensitivity_by_study maps each study name to its own
    {"slope", "r2", "main_effect", "delta_min", "delta_max"} (only for
    studies with >=2 points, i.e. an actual line was fit) - the caller
    collects these across all three metrics into one cross-study
    sensitivity ranking table (see __main__ below)."""
    studies = sorted(df["study"].dropna().unique())
    if not studies:
        print(f"   (nothing to plot for {metric} - no studies found)")
        return [], {}
    saved = []
    sensitivity_by_study = {}
    for study in studies:
        sub = df[df["study"] == study].sort_values("delta")
        sub = sub[sub[metric].notna()]
        if sub.empty:
            print(f"   ({study}: no data for {metric})")
            continue

        # Needed before the star-marker plotting below, and (as a
        # DataFrame, not read here) unrelated to the sensitivity_pct
        # calculation further down - that normalizes by this study's own
        # observed range instead, not by the delta=0 point specifically.
        baseline = sub[sub["delta"].abs() < 1e-9]

        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.plot(sub["delta"], sub[metric], "-o", ms=5, color="steelblue", zorder=3, label="raw")
        if len(sub) >= 2:
            x_trend, y_trend, r2 = plot_style.robust_linear_trend(sub["delta"].to_numpy(), sub[metric].to_numpy())
            # R² alongside the line (same convention as Excel's own "add
            # trendline") - low R² is a real warning that this study's
            # response isn't well-summarized by a straight line at all
            # (e.g. rises then plateaus), not just noisy around one -
            # see plot_style.robust_linear_trend()'s own docstring.
            trend_label = f"linear trend (R²={r2:.2f})" if r2 is not None else "linear trend"
            ax.plot(x_trend, y_trend, color="crimson", lw=2.2, zorder=2, alpha=0.85, label=trend_label)
            # Sensitivity, quantified two ways:
            #  - main_effect (the Design-of-Experiments term for this -
            #    see plot_style.robust_linear_trend()'s docstring): the
            #    line's own total predicted change across THIS study's
            #    tested envelope (slope * delta range) - comparable
            #    across studies with different swept units (degrees vs
            #    t/c ratio) since it's in the shared metric's own units,
            #    but NOT across different metrics (L/D vs SM vs lbm).
            #  - sensitivity_pct: the same movement as a percentage of
            #    this metric's own OBSERVED RANGE across the sweep
            #    (max-min of the raw values, not the single delta=0
            #    baseline point) - unitless, so ALSO comparable across
            #    different metrics (and against rcs_compare_family.py's
            #    own sensitivity_pct columns). Deliberately NOT
            #    normalized by baseline_val: static margin in particular
            #    is designed to sit close to zero, so a baseline-
            #    normalized percentage there can blow up toward
            #    +-infinity for an ordinary-sized change (confirmed
            #    numerically before switching away from it: a baseline of
            #    -0.006 turned a real main_effect of 0.14 into a reported
            #    +2349%). Normalizing by the sweep's own spread instead
            #    has no such failure mode, for any metric.
            slope = (y_trend[1] - y_trend[0]) / (x_trend[1] - x_trend[0]) if x_trend[1] != x_trend[0] else 0.0
            main_effect = y_trend[1] - y_trend[0]
            value_range = float(sub[metric].max() - sub[metric].min())
            sensitivity_pct = (main_effect / value_range * 100.0) if value_range else None
            sensitivity_by_study[study] = {
                "slope": slope, "r2": r2, "main_effect": main_effect,
                "sensitivity_pct": sensitivity_pct,
                "delta_min": x_trend[0], "delta_max": x_trend[1],
            }
        if not baseline.empty:
            ax.plot(baseline["delta"], baseline[metric], "*", ms=15, color="crimson",
                     markeredgecolor="black", markeredgewidth=0.8, zorder=4, label="baseline (delta=0)")
        ax.set_xlabel("delta")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{study} — {ylabel} vs. delta")
        ax.grid(True, ls="--", alpha=0.6)
        ax.legend(fontsize=9)

        # Secondary top axis: the ABSOLUTE applied value of this study's
        # primary swept parameter, not just its delta - e.g. thickness/
        # chord deltas of +-0.01/0.02 around an unstated 0.04 baseline
        # should also read as 0.02-0.06 somewhere on the plot. Exact
        # affine relationship within one study (absolute_value =
        # spec_baseline + delta, see build_study_configs()' _override()),
        # so any single row recovers spec_baseline exactly - no fit needed.
        abs_sub = sub[sub["absolute_value"].notna()]
        if not abs_sub.empty:
            spec_baseline = float(abs_sub["absolute_value"].iloc[0] - abs_sub["delta"].iloc[0])
            ax_top = ax.secondary_xaxis(
                "top",
                functions=(lambda x, b=spec_baseline: x + b, lambda x, b=spec_baseline: x - b),
            )
            ax_top.set_xlabel(f"{study}  absolute value", fontsize=11)

        fig.tight_layout()
        out_path = os.path.join(out_dir, f"{study}_{file_stem}.png")
        fig.savefig(out_path)
        plt.close(fig)
        print(f"   ✅ {out_path}")
        saved.append(out_path)
    return saved, sensitivity_by_study


def _save_sensitivity_table_png(sensitivity_rows, out_path):
    """Same rows as the sensitivity_summary.csv written just before this
    call, rendered as a table image - same convention run_openrcs.py's
    own _save_mean_table() already uses for the MeanRCS table, so this
    drops into a slide the same way. Shows sensitivity_pct (not
    main_effect) as the headline number - both are in the CSV, but
    percent is comparable across metrics too (L/D vs SM vs fuel), so
    it's the more useful single number for a compact table. No single
    metric dominates "worse" here the way RCS dBsm does (higher L/D and
    residual fuel are good, static margin isn't just bigger-is-better),
    so rows stay in the same order as the CSV (alphabetical by study)
    rather than pre-sorted by one column - deliberately, so this table's
    rows line up directly, one-to-one, against rcs_compare_family.py's
    own sensitivity table for the same studies. Re-sort by whichever
    metric matters for a given point in Excel/pandas instead."""
    if not sensitivity_rows:
        print("   (no sensitivity data to summarize)"); return

    col_labels = ["Study", "L/D sensitivity (%)", "L/D R²", "SM sensitivity (%)", "SM R²",
                  "Fuel sensitivity (%)", "Fuel R²"]
    cell_data = [
        [r["study"],
         f"{r['LDmax_sensitivity_pct']:+.1f}%" if r["LDmax_sensitivity_pct"] is not None else "N/A",
         f"{r['LDmax_r2']:.2f}" if r["LDmax_r2"] is not None else "N/A",
         f"{r['SM_sensitivity_pct']:+.1f}%" if r["SM_sensitivity_pct"] is not None else "N/A",
         f"{r['SM_r2']:.2f}" if r["SM_r2"] is not None else "N/A",
         f"{r['ResidualFuel_sensitivity_pct']:+.1f}%" if r["ResidualFuel_sensitivity_pct"] is not None else "N/A",
         f"{r['ResidualFuel_r2']:.2f}" if r["ResidualFuel_r2"] is not None else "N/A"]
        for r in sensitivity_rows
    ]

    fig, ax = plt.subplots(figsize=(11, 1.2 + 0.5 * len(sensitivity_rows)), facecolor="white")
    ax.set_facecolor("white")
    ax.axis("off")

    tbl = ax.table(cellText=cell_data, colLabels=col_labels, cellLoc="center", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.auto_set_column_width(col=list(range(len(col_labels))))
    tbl.scale(1.2, 2.0)

    ax.set_title(
        "Aero/Mission Sensitivity Summary — linear-trend sensitivity across each study's own tested delta range\n"
        "sensitivity = trend's total predicted change end-to-end, as a % of the metric's OWN observed\n"
        "range over the sweep; R² = how well a straight line fits (R²<=~0 means no reliable trend)",
        fontsize=11, pad=14,
    )
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"✅ Sensitivity summary PNG: {out_path}")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    done, other = load_family()
    print(f"Found {len(done)} finished config(s), {len(other)} not-done (status: "
          f"{sorted({e.get('status') for e in other})}).")
    if not done:
        print("Nothing to summarize yet - run aero_stab_mission_driver.py first.")
        raise SystemExit(0)

    # Cruise condition to report on. Not itself stored in mission_results,
    # and not safe to guess from the data (multiple swept Mach/altitude
    # points exist per config) - must match aero_stab_mission_driver.py's
    # own CRUISE_MACH/CRUISE_ALTITUDE_FT values exactly, since that's the
    # flight condition this project's actual design mission cruises at.
    # CRUISE_ALTITUDE_FT=30000.0 is NOT itself a swept grid altitude
    # (ALTITUDE_LIST=[0, 15000, 35000] ft in main.py/aero_stab_mission_
    # driver.py) - _point_interp() below blends the 15000/35000 ft grid
    # points' CD0/K linearly to report this exact cruise altitude instead
    # of a nearby grid point's, since that's the altitude the mission
    # itself (Raymer_sizing_based_mission_check.py's AeroLookup) actually
    # cruises and burns fuel at.
    CRUISE_MACH, CRUISE_ALTITUDE_FT = 0.6, 30000.0

    rows = build_summary_rows(done, CRUISE_MACH, CRUISE_ALTITUDE_FT)
    df = pd.DataFrame(rows)
    summary_path = os.path.join(RESULTS_ROOT, "summary_aero_stab_mission.csv")
    df.to_csv(summary_path, index=False)
    print(f"✅ Combined summary CSV: {summary_path}")

    _, ld_sens = plot_metric_by_study(df, "LD_max_theoretical_cruise", "Theoretical max L/D", OUT_DIR, "LDmax_vs_delta")
    _, sm_sens = plot_metric_by_study(df, "SM_cruise", "Static margin (cruise)", OUT_DIR, "StaticMargin_vs_delta")
    _, fuel_sens = plot_metric_by_study(df, "residual_fuel_lbm", "Residual fuel (lbm)", OUT_DIR, "ResidualFuel_vs_delta")

    # One row per study, ranking each by how much its own linear trend
    # predicts LD_max/SM/residual_fuel move across the FULL delta range
    # actually tested. Two ways to read the size of that movement:
    #   *_main_effect        - the Design-of-Experiments term for a
    #     factor's response change from one end of its tested range to
    #     the other (see plot_style.robust_linear_trend()'s docstring);
    #     comparable ACROSS STUDIES (degrees vs t/c ratio), since it's
    #     in each metric's own shared output units - but NOT across
    #     different metrics (L/D vs SM vs lbm are incompatible).
    #   *_sensitivity_pct    - the same movement as a percentage of that
    #     metric's own OBSERVED RANGE across the sweep (max-min of the
    #     raw values, not the single delta=0 baseline point) - unitless,
    #     so ALSO comparable across different metrics, and against
    #     rcs_compare_family.py's own sensitivity_pct columns, to relate
    #     the aero/mission cost of a parameter directly against its RCS
    #     benefit. Deliberately NOT normalized by the baseline value:
    #     static margin in particular is designed to sit close to zero,
    #     so a baseline-normalized percentage there can blow up toward
    #     +-infinity for an ordinary-sized change - normalizing by the
    #     sweep's own spread instead has no such failure mode.
    # *_r2 says how much to trust either number for a given study; CAN
    # be negative (see plot_style.robust_linear_trend()'s docstring for
    # exactly why - a real, correct result for a parameter with no real
    # linear effect, not a bug) - treat r2<=~0 the same as a low
    # positive one. Sort by |*_sensitivity_pct| in Excel/pandas to read
    # this as a ranked sensitivity table.
    all_studies = sorted(set(ld_sens) | set(sm_sens) | set(fuel_sens))
    sens_rows = []
    for study in all_studies:
        ld, sm, fuel = ld_sens.get(study), sm_sens.get(study), fuel_sens.get(study)
        any_sens = ld or sm or fuel
        sens_rows.append({
            "study": study,
            "LDmax_slope_per_delta": ld["slope"] if ld else None,
            "LDmax_r2": ld["r2"] if ld else None,
            "LDmax_main_effect": ld["main_effect"] if ld else None,
            "LDmax_sensitivity_pct": ld["sensitivity_pct"] if ld else None,
            "SM_slope_per_delta": sm["slope"] if sm else None,
            "SM_r2": sm["r2"] if sm else None,
            "SM_main_effect": sm["main_effect"] if sm else None,
            "SM_sensitivity_pct": sm["sensitivity_pct"] if sm else None,
            "ResidualFuel_slope_per_delta_lbm": fuel["slope"] if fuel else None,
            "ResidualFuel_r2": fuel["r2"] if fuel else None,
            "ResidualFuel_main_effect_lbm": fuel["main_effect"] if fuel else None,
            "ResidualFuel_sensitivity_pct": fuel["sensitivity_pct"] if fuel else None,
            "delta_min": any_sens["delta_min"] if any_sens else None,
            "delta_max": any_sens["delta_max"] if any_sens else None,
        })
    if sens_rows:
        sens_path = os.path.join(RESULTS_ROOT, "sensitivity_summary.csv")
        pd.DataFrame(sens_rows).to_csv(sens_path, index=False)
        print(f"✅ Sensitivity summary CSV: {sens_path}")
        _save_sensitivity_table_png(sens_rows, os.path.join(RESULTS_ROOT, "sensitivity_summary.png"))

    if other:
        print(f"\n⚠️  {len(other)} config(s) not done - see their own manifest JSON for status/error:")
        for e in other:
            print(f"   {e.get('tag', '?')}: {e.get('status', '?')}")
