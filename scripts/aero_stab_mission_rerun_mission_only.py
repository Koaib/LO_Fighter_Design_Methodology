# -*- coding: utf-8 -*-
"""
aero_stab_mission_rerun_mission_only.py — recomputes mission_results (and
mission/<tag>.md) for every already-finished config under Results/
AeroStabMissionStudy, WITHOUT touching the aero grid or stability_points.

For the one-off situation where aero_stab_mission_driver.py was run with
wrong mission-only settings (cruise_mach/cruise_altitude_ft/design_range_nmi/
engine_*) but the aero grid AND the weight basis (gross_mass_lbm/
fuel_capacity_lbm) were fine - so stability_points (which depend only on
wing_area_ft2 + gross_mass_lbm, both untouched) has nothing wrong to fix,
only the Raymer mission check itself does. aero_stab_mission_driver.py's
own manifest-status skip (see its run_one()) can't do a mission-only
redo: it's all-or-nothing per config, and if forced to rerun it goes
through aero_stab_mission_worker.py, which launches a full OpenVSP
session per config just to re-read wing_area_ft2 - already sitting in the
manifest - and would only skip re-running VSPAero if the manifest's
aero_points survives untouched, which is fragile to rely on by hand
across every manifest.

This script instead reads each manifest directly, reuses its aero_points/
wing_area_ft2/aero_dir/stability_points as-is (never re-invokes VSPAero,
OpenVSP, or the stability calc), and recomputes only mission_results via
Raymer_sizing_based_mission_check.run_raymer_mission_check() - a pure
function of its args plus files under aero_search_dir, mirroring
aero_stab_mission_worker.py's own call exactly. stability_plot_path's PNG
is untouched too, for the same reason it always was: it only plots raw
CMytot vs Alpha per aero CSV, independent of any mission/weight setting.

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

import aero_stab_mission_driver as driver
import Raymer_sizing_based_mission_check as raymer

MISSION_KWARGS = (
    "gross_mass_lbm", "fuel_capacity_lbm", "design_range_nmi",
    "cruise_mach", "cruise_altitude_ft", "mach_list", "altitude_list",
    "custom_engine_deck_path", "engine_t_sl_dry_lbf", "engine_t_sl_ab_lbf",
    "engine_throttle_ratio", "engine_type", "num_engines",
)
SKIP_STATUSES = {"aero_failed", "aero_diverged", "running"}


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
