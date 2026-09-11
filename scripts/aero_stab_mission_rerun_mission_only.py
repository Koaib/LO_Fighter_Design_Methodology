# -*- coding: utf-8 -*-
"""
aero_stab_mission_rerun_mission_only.py — recomputes stability_points +
mission_results (and mission/<tag>.md) for every already-finished config
under Results/AeroStabMissionStudy, WITHOUT touching the aero grid.

For the one-off situation where aero_stab_mission_driver.py was run with
wrong mission-only settings (cruise_mach/cruise_altitude_ft/design_range_nmi/
gross_mass_lbm/fuel_capacity_lbm/engine_*) but the aero grid itself
(mach_list/altitude_list/alpha range/re_cref/wake_iters/geometry deltas)
was fine. aero_stab_mission_driver.py's own manifest-status skip (see its
run_one()) can't do a mission-only redo: it's all-or-nothing per config,
and if forced to rerun it goes through aero_stab_mission_worker.py, which
launches a full OpenVSP session per config just to re-read wing_area_ft2 -
already sitting in the manifest - and would only skip re-running VSPAero
if the manifest's aero_points survives untouched, which is fragile to
rely on by hand across every manifest.

This script instead reads each manifest directly, reuses its aero_points/
wing_area_ft2/aero_dir as-is (never re-invokes VSPAero or OpenVSP), and
recomputes only the two things that actually depend on mission/weight
settings: stability_points (isa_atmosphere/compute_static_margin - pure
numpy/pandas over the existing aero CSVs) and mission_results (Raymer_
sizing_based_mission_check.run_raymer_mission_check() - pure function of
its args plus files under aero_search_dir). Both mirror aero_stab_mission_
worker.py's own calls exactly, just without the geometry/aero machinery
around them. stability_plot_path's PNG is untouched on purpose - it only
plots raw CMytot vs Alpha per aero CSV, independent of any mission/weight
setting, so there's nothing in it to go stale.

BEFORE RUNNING: fix the wrong constants in aero_stab_mission_driver.py
first (this script imports that module and reads its current BASE dict
live, so whatever's set there when you run this is what gets applied).
If cruise_mach/cruise_altitude_ft changed, also check aero_stab_mission_
compare_family.py's own hardcoded CRUISE_MACH/CRUISE_ALTITUDE_FT constants
match, since that's what picks which grid point lands in the summary CSV.

Processes every manifest that finished its aero grid, whether it
previously ended in "done" or "error" - an "error" status can itself have
been the wrong mission settings' fault (e.g. a spurious thrust/lift-margin
exception), so it's worth a second try here too, not just re-polishing
already-"done" configs. Only "aero_failed"/"aero_diverged"/"running"
(aero itself never finished) are skipped, since there's no aero data yet
to run a mission check against.

Run from anywhere: `python aero_stab_mission_rerun_mission_only.py`
Safe to re-run - always overwrites by tag, never accumulates.
"""
import sys, json, traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import vsp_setup
import aero_stab_mission_driver as driver
import Raymer_sizing_based_mission_check as raymer

MISSION_KWARGS = (
    "gross_mass_lbm", "fuel_capacity_lbm", "design_range_nmi",
    "cruise_mach", "cruise_altitude_ft", "mach_list", "altitude_list",
    "custom_engine_deck_path", "engine_t_sl_dry_lbf", "engine_t_sl_ab_lbf",
    "engine_throttle_ratio", "engine_type", "num_engines",
)
SKIP_STATUSES = {"aero_failed", "aero_diverged", "running"}


def _recompute_stability(entry):
    weight_n = driver.BASE["gross_mass_lbm"] * 0.45359237 * 9.80665
    wing_area_m2 = entry["wing_area_ft2"] * 0.09290304
    stability_points = []
    for pt in entry["aero_points"]:
        _, rho, _, a_sound = vsp_setup.isa_atmosphere(pt["alt_ft"])
        v_mps = pt["mach"] * a_sound
        q_pa = 0.5 * rho * v_mps ** 2
        cl_target = weight_n / (q_pa * wing_area_m2)
        sm, sm_r2 = vsp_setup.compute_static_margin(pt["csv"], cl_target)
        stability_points.append({
            "mach": pt["mach"], "alt_ft": pt["alt_ft"],
            "CL_target": cl_target, "SM": sm, "SM_R2": sm_r2,
        })
    return stability_points


def _recompute_mission(entry, mission_dir):
    mission_results = raymer.run_raymer_mission_check(
        geom_stem=entry["tag"], wing_area_ft2=entry["wing_area_ft2"],
        aero_search_dir=entry["aero_dir"],
        **{k: driver.BASE[k] for k in MISSION_KWARGS},
    )
    mission_dir.mkdir(parents=True, exist_ok=True)
    mission_md_path = mission_dir / f"{entry['tag']}.md"
    mission_md_path.write_text(raymer.format_mission_results_md(mission_results, title=entry["tag"]))
    return mission_results, str(mission_md_path)


def main():
    manifest_paths = sorted(driver.RESULTS_ROOT.glob("*/manifest/*.json"))
    if not manifest_paths:
        print(f"No manifests found under {driver.RESULTS_ROOT}"); return

    n_done = n_skipped = n_error = 0
    for path in manifest_paths:
        entry = json.loads(path.read_text())
        tag = entry.get("tag", path.stem)

        if entry.get("status") in SKIP_STATUSES or not entry.get("aero_points"):
            print(f"skip {tag} — aero incomplete (status={entry.get('status')})")
            n_skipped += 1
            continue

        try:
            entry["stability_points"] = _recompute_stability(entry)
            mission_dir = path.parent.parent / "mission"
            mission_results, mission_md_path = _recompute_mission(entry, mission_dir)
            entry["mission_results"] = mission_results
            entry["mission_md_path"] = mission_md_path
            entry["status"] = "done"
            entry.pop("error", None)
            path.write_text(json.dumps(entry, indent=2))
            print(f"OK {tag} — feasible={mission_results.get('feasible')}, "
                  f"climb_completed={mission_results.get('climb_completed')}")
            n_done += 1
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = f"{e}\n{traceback.format_exc()}"
            path.write_text(json.dumps(entry, indent=2))
            print(f"ERROR {tag} — {e}")
            n_error += 1

    print(f"\n{n_done} updated, {n_skipped} skipped (aero incomplete), {n_error} errored.")
    print("Run aero_stab_mission_compare_family.py next to rebuild the combined summary CSV + plots.")


if __name__ == "__main__":
    main()
