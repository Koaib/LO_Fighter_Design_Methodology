# -*- coding: utf-8 -*-
"""
repair_manifest_paths.py — one-off migration: rewrites the absolute
paths already baked into EXISTING manifest JSON files (stl_path/
rcs_outputs for the RCS sweep; aero_dir/aero_points[*]["csv"]/
stability_plot_path/mission_md_path for the aero+stability+mission
sweep) into paths relative to that manifest's own results_root (its own
study/_baseline directory) - matching what rcs_sweep_worker.py/
aero_stab_mission_worker.py now write for every NEW run.

WHY THIS EXISTS: that worker-side fix only changes what FUTURE runs
write. It does not retroactively touch manifests already on disk, and
without it those old manifests still silently break (RCS: a missing
azimuth polar overlay plot) or hard-fail (aero_stab_mission_rerun_
mission_only.py: FileNotFoundError) the moment Results/
RCS_SensitivityStudy/ or Results/AeroStabMissionStudy/ is copied to a
different machine or clone location.

RUN THIS ONCE, ON THE MACHINE WHERE THESE Results/ FOLDERS CURRENTLY
LIVE - before copying them anywhere else. It resolves each manifest's
own stored absolute path against wherever that manifest file itself
sits RIGHT NOW (not against the machine that originally generated it),
so it only works correctly run in place, pre-copy. After running this
here, both Results/ trees can be copied anywhere and rcs_compare_
family.py/aero_stab_mission_compare_family.py/aero_stab_mission_rerun_
mission_only.py will all still find their files.

Pure stdlib (pathlib, json, argparse) - no OpenVSP/OpenRCS/pandas/numpy
dependency, safe to run in any plain Python 3 environment that can see
the Results/ folder.

Usage:
    python repair_manifest_paths.py             # both Results/... trees, in place
    python repair_manifest_paths.py --dry-run    # print what would change, write nothing
"""
import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent

RCS_ROOT  = ROOT_DIR / "Results" / "RCS_SensitivityStudy"
AERO_ROOT = ROOT_DIR / "Results" / "AeroStabMissionStudy"


def _rel(path_str, results_root):
    """Best-effort, conservative rewrite: only touches a value that is
    (a) actually an absolute path AND (b) genuinely lives under
    results_root on THIS machine right now (Path.relative_to() raises
    ValueError otherwise). Anything else - already relative (a manifest
    a previous run of this script, or a fresh worker run, already fixed),
    or absolute but pointing somewhere unrelated - is left untouched
    rather than guessed at. Returns (value_to_store, changed: bool)."""
    p = Path(path_str)
    if not p.is_absolute():
        return path_str, False
    try:
        rel = p.relative_to(results_root)
    except ValueError:
        return path_str, False
    return str(rel), True


def repair_rcs_manifest(path: Path, dry_run: bool) -> int:
    results_root = path.parent.parent  # manifest/<tag>.json -> its own study/_baseline dir
    entry = json.loads(path.read_text())
    changed = 0

    if entry.get("stl_path"):
        new, did = _rel(entry["stl_path"], results_root)
        if did:
            entry["stl_path"] = new
            changed += 1

    for k, v in list(entry.get("rcs_outputs", {}).items()):
        if v:
            new, did = _rel(v, results_root)
            if did:
                entry["rcs_outputs"][k] = new
                changed += 1

    if changed and not dry_run:
        path.write_text(json.dumps(entry, indent=2))
    return changed


def repair_aero_manifest(path: Path, dry_run: bool) -> int:
    results_root = path.parent.parent  # manifest/<tag>.json -> its own study/_baseline dir
    entry = json.loads(path.read_text())
    changed = 0

    for key in ("aero_dir", "stability_plot_path", "mission_md_path"):
        if entry.get(key):
            new, did = _rel(entry[key], results_root)
            if did:
                entry[key] = new
                changed += 1

    for pt in entry.get("aero_points", []):
        if pt.get("csv"):
            new, did = _rel(pt["csv"], results_root)
            if did:
                pt["csv"] = new
                changed += 1

    if changed and not dry_run:
        path.write_text(json.dumps(entry, indent=2))
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                     help="Print what would change without writing anything.")
    args = ap.parse_args()

    total_manifests = 0
    total_fields = 0

    for root, repair_fn, label in (
        (RCS_ROOT, repair_rcs_manifest, "RCS_SensitivityStudy"),
        (AERO_ROOT, repair_aero_manifest, "AeroStabMissionStudy"),
    ):
        if not root.is_dir():
            print(f"(skip {label}: {root} not found)")
            continue
        manifest_paths = sorted(root.glob("*/manifest/*.json"))
        print(f"{label}: {len(manifest_paths)} manifest file(s) found under {root}")
        for p in manifest_paths:
            n = repair_fn(p, args.dry_run)
            total_manifests += 1
            total_fields += n
            if n:
                verb = "would rewrite" if args.dry_run else "rewrote"
                print(f"  {verb} {n} path field(s) in {p.relative_to(root)}")

    mode = "DRY RUN - nothing written" if args.dry_run else "done"
    print(f"\n{mode}: {total_fields} path field(s) rewritten across "
          f"{total_manifests} manifest(s) checked.")


if __name__ == "__main__":
    main()
