# -*- coding: utf-8 -*-
"""
fit_fix_comparison.py — one-off diagnostic + before/after report for the
Theil-Sen -> OLS trend-line switch in aero_stab_mission_compare_family.py
and maneuver_compare_family.py (plot_style.linear_fit() - see that
function's own docstring for why two different fits coexist in this
project: rcs_compare_family.py was NOT touched and still uses Theil-Sen
via plot_style.robust_linear_trend()).

Does two things, reading only already-computed manifests (same as every
other compare_family script - never re-runs a solver):

  1. DIAGNOSIS: for VT_Cant / residual fuel specifically, prints the
     exact x/y arrays aero_stab_mission_compare_family.plot_metric_by_
     study() now hands to the scatter call AND to plot_style.linear_fit()
     side by side, with an assertion that they match after only the
     finite-value mask - so the "fit computed on different data than
     what's plotted" concern is checked against real data, not just
     argued from reading the code.

  2. COMPARISON TABLE: for every (study, metric) across all 8 metrics
     (mean azimuth RCS, mean frontal RCS, L/D max, static margin,
     residual fuel, Ps at 1g, n_s, sustained turn rate), computes BOTH
     the OLD slope/R² (Theil-Sen, plot_style.robust_linear_trend - what
     every panel used before this fix) and the NEW slope/R² (OLS,
     plot_style.linear_fit - what aero_stab_mission_compare_family.py/
     maneuver_compare_family.py use now) from the SAME underlying
     points, flags which rows changed, and writes
     Results/fit_fix_comparison.csv. The two RCS metrics are computed
     the same way in both the OLD and NEW columns (Theil-Sen both
     times) and always show CHANGED=No, since rcs_compare_family.py
     itself was not part of this fix - included so the table still
     covers "all metrics" as asked, with that scope limit visible in
     the data instead of asserted in prose.

Run this AFTER re-running aero_stab_mission_compare_family.py and
maneuver_metrics_extractor.py/maneuver_compare_family.py themselves (it
only reads what they've already written) - see the README printed at
the bottom of a run for the exact command sequence.

Usage: python3 fit_fix_comparison.py
"""
import os

import numpy as np
import pandas as pd

import plot_style
import aero_stab_mission_compare_family as cf
import maneuver_compare_family as mcf
import rcs_compare_family as rcs_family

CRUISE_MACH, CRUISE_ALTITUDE_FT = 0.6, 30000.0
CHANGED_PCT_TABLE = 5.0     # per-row CHANGED? flag in the table (user's STEP 4 spec)
CHANGED_PCT_SUMMARY = 20.0  # headline "worth worrying about" list at the end


def _old_new_slope_r2(x, y):
    """(old_slope, old_r2, new_slope, new_r2, n) for one (x, y) pair -
    old = Theil-Sen (plot_style.robust_linear_trend), new = OLS
    (plot_style.linear_fit). Both are translation-invariant in x
    (shifting x by a constant leaves slope/R² unchanged - verified for
    Theil-Sen earlier in this project and for linear_fit() in this
    fix's own synthetic tests), so which x representation (delta vs
    absolute value) is passed in does not affect this comparison -
    delta is used uniformly below since it needs no per-study baseline
    lookup to compute."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = int((np.isfinite(x) & np.isfinite(y)).sum())

    old_slope = old_r2 = None
    if n >= 2:
        xt, yt, r2 = plot_style.robust_linear_trend(x, y)
        old_slope = (yt[1] - yt[0]) / (xt[1] - xt[0]) if xt[1] != xt[0] else 0.0
        old_r2 = r2

    new_slope = new_r2 = None
    fit = plot_style.linear_fit(x, y)
    if fit is not None:
        new_slope, _intercept, new_r2, _xs, _ys, _n = fit

    return old_slope, old_r2, new_slope, new_r2, n


def _changed(old, new, pct_threshold):
    """True if old/new differ by more than pct_threshold%, or flipped
    sign (crossing zero counts as a sign flip even if one side IS
    zero - any nonzero vs exactly zero is as big a qualitative change as
    this table can show)."""
    if old is None or new is None:
        return False
    if old == 0 and new == 0:
        return False
    if old == 0 or new == 0:
        return True
    if (old < 0) != (new < 0):
        return True
    return abs(new - old) / abs(old) * 100.0 > pct_threshold


def diagnose_vt_cant_residual_fuel():
    print("=" * 78)
    print("STEP 2 DIAGNOSIS — VT_Cant / residual fuel: fit arrays vs plot arrays")
    print("=" * 78)
    done, _ = cf.load_family(["VT_Cant"])
    if not done:
        print("  (no VT_Cant manifests found on this machine - skipping)")
        print()
        return
    rows = cf.build_summary_rows(done, CRUISE_MACH, CRUISE_ALTITUDE_FT)
    df = pd.DataFrame(rows)
    sub = df[df["study"] == "VT_Cant"].sort_values("delta")
    sub = sub[sub["residual_fuel_lbm"].notna()]
    if sub.empty:
        print("  (no residual_fuel_lbm data for VT_Cant - skipping)")
        print()
        return

    # These next 4 lines are COPIED VERBATIM from aero_stab_mission_
    # compare_family.plot_metric_by_study() - not a reimplementation,
    # so this diagnosis can't drift from what that function actually
    # does.
    abs_sub = sub[sub["absolute_value"].notna()]
    use_abs = not abs_sub.empty
    spec_baseline = float(abs_sub["absolute_value"].iloc[0] - abs_sub["delta"].iloc[0]) if use_abs else None
    x_raw = (sub["delta"] + spec_baseline) if use_abs else sub["delta"]
    x_plot = x_raw.to_numpy(dtype=float)
    y_plot = sub["residual_fuel_lbm"].to_numpy(dtype=float)

    print(f"  n points plotted:           {len(x_plot)}")
    print(f"  x used for PLOT (scatter):  {np.array2string(x_plot, precision=4)}")
    print(f"  y used for PLOT (scatter):  {np.array2string(y_plot, precision=2)}")

    fit = plot_style.linear_fit(x_plot, y_plot)
    if fit is None:
        print("  (fewer than 3 finite points - no trend line drawn, nothing to compare)")
        print()
        return

    slope, intercept, r2, xs, ys, n = fit
    print(f"  x used for FIT (linear_fit): {np.array2string(xs, precision=4)}")
    print(f"  y used for FIT (linear_fit): {np.array2string(ys, precision=2)}")

    finite_mask = np.isfinite(x_plot) & np.isfinite(y_plot)
    assert np.array_equal(x_plot[finite_mask], xs), "x mismatch between plot and fit!"
    assert np.array_equal(y_plot[finite_mask], ys), "y mismatch between plot and fit!"
    assert 0.0 <= r2 <= 1.0, f"R2={r2} outside [0,1]!"
    pred_at_mean = slope * xs.mean() + intercept
    assert abs(pred_at_mean - ys.mean()) < 1e-6, "OLS line does not pass through the data mean!"

    print(f"  slope={slope:.4f}  intercept={intercept:.4f}  r2={r2:.4f}")
    print("  VERIFIED: fit's xs/ys are identical to what's plotted (after only the finite mask).")
    print("  VERIFIED: 0 <= r2 <= 1.")
    print(f"  VERIFIED: line at x.mean()={xs.mean():.4f} predicts {pred_at_mean:.4f}, "
          f"matching y.mean()={ys.mean():.4f} to 1e-6.")
    print()


def _aero_maneuver_rows():
    """[{study, metric, old_slope, old_r2, new_slope, new_r2, n}, ...]
    for L/D max, static margin, residual fuel (aero_stab_mission_
    compare_family.py) and Ps_1g, n_s, turn_rate (maneuver_compare_
    family.py) - same EXCLUDED_DELTAS filtering __main__ itself applies
    for the aero metrics, same loaders either file's own __main__ uses."""
    out = []

    aero_done, _ = cf.load_family()
    aero_df = pd.DataFrame(cf.build_summary_rows(aero_done, CRUISE_MACH, CRUISE_ALTITUDE_FT))
    if not aero_df.empty:
        for study, excluded in cf.EXCLUDED_DELTAS.items():
            mask = (aero_df["study"] == study) & (aero_df["delta"].isin(excluded))
            aero_df = aero_df[~mask]

    aero_metrics = [("LD_max_theoretical_cruise", "ld_max"),
                     ("SM_cruise", "static_margin"),
                     ("residual_fuel_lbm", "residual_fuel")]
    for study in (sorted(aero_df["study"].dropna().unique()) if not aero_df.empty else []):
        sub = aero_df[aero_df["study"] == study].sort_values("delta")
        for col, label in aero_metrics:
            s = sub[sub[col].notna()]
            if s.empty:
                continue
            old_slope, old_r2, new_slope, new_r2, n = _old_new_slope_r2(s["delta"], s[col])
            out.append({"study": study, "metric": label, "old_slope": old_slope, "old_r2": old_r2,
                        "new_slope": new_slope, "new_r2": new_r2, "n": n, "method": "Theil-Sen -> OLS"})

    maneuver_rows = mcf.load_maneuver_family()
    maneuver_df = mcf._maneuver_dataframe(maneuver_rows)
    maneuver_metrics = [("Ps_1g_fpm", "ps_1g"), ("n_s", "n_s"), ("turn_rate_dps", "turn_rate")]
    if not maneuver_df.empty:
        for study in sorted(maneuver_df["study"].dropna().unique()):
            sub = maneuver_df[maneuver_df["study"] == study].sort_values("delta")
            for col, label in maneuver_metrics:
                s = sub[sub[col].notna()]
                if s.empty:
                    continue
                old_slope, old_r2, new_slope, new_r2, n = _old_new_slope_r2(s["delta"], s[col])
                out.append({"study": study, "metric": label, "old_slope": old_slope, "old_r2": old_r2,
                            "new_slope": new_slope, "new_r2": new_r2, "n": n, "method": "Theil-Sen -> OLS"})
    return out


def _rcs_rows():
    """Same (study, metric, ...) shape as _aero_maneuver_rows(), but for
    mean azimuth/frontal RCS - computed via rcs_compare_family.py's own
    loader, through plot_style.robust_linear_trend() for BOTH the old
    and new columns (rcs_compare_family.py is out of scope for this fix
    - see module docstring), so these rows always show CHANGED=No."""
    out = []
    if not rcs_family.RESULTS_ROOT.is_dir():
        return out
    studies = sorted(p.name for p in rcs_family.RESULTS_ROOT.iterdir()
                      if p.is_dir() and not p.name.startswith("_") and (p / "manifest").is_dir())
    for study in studies:
        results_root = rcs_family.RESULTS_ROOT / study
        rows = rcs_family.load_family(study, results_root)
        rows3, spec_baseline = rcs_family._add_absolute_values(rows)
        excluded = rcs_family.EXCLUDED_DELTAS.get(study, set())
        for tag_key, label in (("AZ_TE", "az_rcs"), ("FR_TE", "frontal_rcs")):
            deltas = [d for d, e, _ in rows3 if tag_key in e.get("means", {}) and d not in excluded]
            means = [e["means"][tag_key] for d, e, _ in rows3 if tag_key in e.get("means", {}) and d not in excluded]
            if not deltas:
                continue
            old_slope, old_r2, _ns, _nr, n = _old_new_slope_r2(deltas, means)
            out.append({"study": study, "metric": label, "old_slope": old_slope, "old_r2": old_r2,
                        "new_slope": old_slope, "new_r2": old_r2, "n": n,
                        "method": "Theil-Sen (unchanged - rcs_compare_family.py out of scope)"})
    return out


def main():
    diagnose_vt_cant_residual_fuel()

    print("=" * 78)
    print("STEP 4 — old (Theil-Sen) vs new (OLS) slope/R² per study x metric")
    print("=" * 78)
    rows = _rcs_rows() + _aero_maneuver_rows()
    if not rows:
        print("  No manifests found on this machine - run the pipeline scripts first, "
              "then re-run this script.")
        return

    for r in rows:
        r["slope_changed"] = _changed(r["old_slope"], r["new_slope"], CHANGED_PCT_TABLE)

    df = pd.DataFrame(rows)
    df = df.sort_values(["study", "metric"]).reset_index(drop=True)

    def fmt(v):
        return "N/A" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.4g}"

    print(f"\n{'study':<22} {'metric':<14} {'old slope':>12} {'new slope':>12} "
          f"{'old R2':>8} {'new R2':>8} {'N':>4}  CHANGED?")
    print("-" * 100)
    for _, r in df.iterrows():
        print(f"{r['study']:<22} {r['metric']:<14} {fmt(r['old_slope']):>12} {fmt(r['new_slope']):>12} "
              f"{fmt(r['old_r2']):>8} {fmt(r['new_r2']):>8} {r['n']:>4}  "
              f"{'YES' if r['slope_changed'] else 'no'}")

    out_path = os.path.join(cf.RESULTS_ROOT, "..", "fit_fix_comparison.csv")
    out_path = os.path.normpath(out_path)
    df.to_csv(out_path, index=False)
    print(f"\n✅ Comparison table CSV: {out_path}")

    print("\n" + "=" * 78)
    print(f"Plots that changed (slope sign-flip or >{CHANGED_PCT_SUMMARY:.0f}% change):")
    print("=" * 78)
    big_changes = [r for _, r in df.iterrows() if _changed(r["old_slope"], r["new_slope"], CHANGED_PCT_SUMMARY)]
    if not big_changes:
        print("  None - every study/metric's slope stayed within "
              f"{CHANGED_PCT_SUMMARY:.0f}% and kept its sign under the OLS refit.")
    else:
        for r in big_changes:
            sign_flip = (r["old_slope"] is not None and r["new_slope"] is not None
                         and (r["old_slope"] < 0) != (r["new_slope"] < 0))
            pct = (abs(r["new_slope"] - r["old_slope"]) / abs(r["old_slope"]) * 100.0
                   if r["old_slope"] not in (None, 0) and r["new_slope"] is not None else None)
            reason = "sign flip" if sign_flip else (f"{pct:.0f}% change" if pct is not None else "N/A->value or value->N/A")
            print(f"  {r['study']} / {r['metric']}: old={fmt(r['old_slope'])} -> new={fmt(r['new_slope'])} ({reason})")


if __name__ == "__main__":
    main()
