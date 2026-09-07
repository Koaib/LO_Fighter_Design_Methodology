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
JSON under Results/AeroStabMissionStudy/manifest/ if a deeper look at a
specific point/config is ever needed.
"""
import glob
import json
import os

import matplotlib.pyplot as plt
import pandas as pd

RESULTS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Results", "AeroStabMissionStudy")
MANIFEST_GLOB = os.path.join(RESULTS_ROOT, "manifest", "*.json")
OUT_DIR = os.path.join(RESULTS_ROOT, "Comparisons")


def load_family(manifest_glob=MANIFEST_GLOB):
    """Reads every manifest JSON, returns (done_entries, other_entries).
    other_entries (status != "done") are returned too, not silently
    dropped, so a caller can report what's still missing/failed rather
    than just seeing a shorter-than-expected table."""
    done, other = [], []
    for path in sorted(glob.glob(manifest_glob)):
        with open(path) as f:
            entry = json.load(f)
        (done if entry.get("status") == "done" else other).append(entry)
    return done, other


def _point_at(points, mach, alt_ft, tol=1e-6):
    for p in points:
        if abs(p["mach"] - mach) < tol and abs(p["alt_ft"] - alt_ft) < tol:
            return p
    return None


def build_summary_rows(entries, cruise_mach, cruise_altitude_ft):
    rows = []
    for e in entries:
        aero_pt = _point_at(e.get("aero_points", []), cruise_mach, cruise_altitude_ft)
        stab_pt = _point_at(e.get("stability_points", []), cruise_mach, cruise_altitude_ft)
        mr = e.get("mission_results", {})
        rows.append({
            "study": e["study"], "delta": e["delta"], "tag": e["tag"],
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


def plot_metric_by_study(df, metric, ylabel, out_path):
    studies = sorted(df["study"].dropna().unique())
    if not studies:
        print(f"   (nothing to plot for {metric} - no studies found)")
        return
    fig, axes = plt.subplots(1, len(studies), figsize=(5 * len(studies), 5), sharey=True)
    if len(studies) == 1:
        axes = [axes]
    for ax, study in zip(axes, studies):
        sub = df[df["study"] == study].sort_values("delta")
        sub = sub[sub[metric].notna()]
        if sub.empty:
            ax.set_title(f"{study} (no data)")
            continue
        ax.plot(sub["delta"], sub[metric], "-o", ms=5)
        baseline = sub[sub["delta"].abs() < 1e-9]
        if not baseline.empty:
            ax.plot(baseline["delta"], baseline[metric], "r*", ms=14, label="baseline (delta=0)")
            ax.legend()
        ax.set_xlabel("delta")
        ax.set_title(study)
        ax.grid(True, ls="--", alpha=0.6)
    axes[0].set_ylabel(ylabel)
    fig.suptitle(f"{ylabel} vs. shaping delta, by study")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"   ✅ {out_path}")


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
    CRUISE_MACH, CRUISE_ALTITUDE_FT = 0.6, 35000.0

    rows = build_summary_rows(done, CRUISE_MACH, CRUISE_ALTITUDE_FT)
    df = pd.DataFrame(rows)
    summary_path = os.path.join(RESULTS_ROOT, "summary_aero_stab_mission.csv")
    df.to_csv(summary_path, index=False)
    print(f"✅ Combined summary CSV: {summary_path}")

    plot_metric_by_study(df, "LD_max_theoretical_cruise", "Theoretical max L/D", os.path.join(OUT_DIR, "ld_max_vs_delta.png"))
    plot_metric_by_study(df, "SM_cruise", "Static margin (cruise)", os.path.join(OUT_DIR, "sm_vs_delta.png"))
    plot_metric_by_study(df, "residual_fuel_lbm", "Residual fuel (lbm)", os.path.join(OUT_DIR, "residual_fuel_vs_delta.png"))

    if other:
        print(f"\n⚠️  {len(other)} config(s) not done - see their own manifest JSON for status/error:")
        for e in other:
            print(f"   {e.get('tag', '?')}: {e.get('status', '?')}")
