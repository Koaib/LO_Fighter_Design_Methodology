# -*- coding: utf-8 -*-
"""
doe_check_status.py — scans Results/DoE/{aero_stab_mission,rcs}/manifest/
for every DOE_* tag and reports status on both sides: done / a named
failure / not yet run. Read-only - doesn't touch or re-run anything,
safe to run any time from any machine that can see the shared storage.

Usage:
    python doe_check_status.py
"""
import json
import doe_config as cfg

AERO_MANIFEST_DIR = cfg.DOE_ROOT / "aero_stab_mission" / "manifest"
RCS_MANIFEST_DIR  = cfg.DOE_ROOT / "rcs" / "manifest"


def _read_status(manifest_dir, tag):
    path = manifest_dir / f"{tag}.json"
    if not path.exists():
        return "not_run", None
    try:
        with open(path) as f:
            entry = json.load(f)
    except (json.JSONDecodeError, KeyError):
        # Manifest exists but is empty/truncated right now - almost always
        # means the worker is mid-checkpoint-write THIS INSTANT (its own
        # _write() truncates-then-writes, not atomic - same reasoning as
        # aero_stab_mission_worker.py's own comment on this). Not real
        # corruption - just re-run this script a bit later.
        return "writing_now", None
    note = entry.get("note") or entry.get("error", "")
    return entry.get("status", "?"), (note[:120] if note else None)

if __name__ == "__main__":
    import doe_run
    tags = [t for t, _ in doe_run.load_design()]

    aero_counts, rcs_counts, problems = {}, {}, []
    for tag in tags:
        a_status, a_note = _read_status(AERO_MANIFEST_DIR, tag)
        r_status, r_note = _read_status(RCS_MANIFEST_DIR, tag)
        aero_counts[a_status] = aero_counts.get(a_status, 0) + 1
        rcs_counts[r_status] = rcs_counts.get(r_status, 0) + 1
        if a_status != "done" or r_status != "done":
            problems.append((tag, a_status, a_note, r_status, r_note))

    print(f"Aero/mission side: {aero_counts}")
    print(f"RCS side:          {rcs_counts}")
    print(f"\n{len(problems)} of {len(tags)} tags not fully done on both sides:")
    for tag, a_status, a_note, r_status, r_note in problems:
        print(f"  {tag}: aero={a_status}" + (f" ({a_note})" if a_note else "")
              + f"  rcs={r_status}" + (f" ({r_note})" if r_note else ""))
