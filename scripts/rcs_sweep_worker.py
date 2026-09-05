# -*- coding: utf-8 -*-
"""
rcs_sweep_worker.py — runs ONE (shaping parameter, delta) RCS-only job, then exits.
Called as: python rcs_sweep_worker.py '<json config>'

RCS-only counterpart to sweep_worker.py: no VSPAero, no aero analysis at
all. Loads the baseline geometry, applies exactly one parameter's delta,
exports the CFD-mesh STL (same settings as main.py), runs it through
run_openrcs.run_openrcs_pipeline(), and writes a manifest — same
subprocess-per-config / manifest-based resume pattern as the existing
aero sweep_worker.py, so an expensive multi-hour RCS sweep can be
interrupted and picked back up without re-running finished deltas.

── CHECKPOINTING (added for cluster runs with unreliable power) ───────────
Resume granularity used to be per-DELTA only: if a delta's worker got
killed mid-run — mesh export, azimuth solve, or frontal solve — the
WHOLE delta restarted from a fresh OpenVSP load next time, including
redoing an already-finished CFD mesh or azimuth solve. Wasteful, given
the azimuth + frontal PO solves are the expensive part.

Now there are THREE independently-resumable stages per delta:
  1. mesh     — CFD-mesh STL export (main.py-identical settings)
  2. azimuth  — run_openrcs_pipeline(cuts="azimuth", ...)
  3. frontal  — run_openrcs_pipeline(cuts="frontal", ...)
Each stage checks whether its own output already exists on disk BEFORE
doing the (expensive) work, and the manifest is written to disk right
after each stage completes — not just once at the very end — so a power
cut anywhere leaves a manifest that accurately reflects how far this
delta actually got, and a re-run of the same tag picks up from there.

Trade-off, stated plainly: splitting one combined "azimuth+frontal" call
into two separate calls means run_openrcs_pipeline's own mesh-LOADING
step (STL -> coordinates.txt/facets.txt — its own internal step, distinct
from OpenVSP's CFD-mesh EXPORT above) now runs twice per delta instead
of once, even on an uninterrupted run. Azimuth (181/361 pts) and
especially frontal (61x7=427 pts) PO solves dominate runtime, so this
should be a small tax relative to the resume time it buys — but it's a
real, deliberate cost, not a free lunch.

BUG FOUND & FIXED while adding this: run_openrcs_pipeline()'s returned
dict never actually exposed the raw per-angle .dat file paths — only
plot PNG/JPG paths (keys like "linear_az"/"polar_az_te"/"fig_3d"). The
"AZ_TE"/"FR_TE" .dat files it DOES write to results_dir get a timestamp
baked into their filename internally and were never renamed or tracked
anywhere outside the function. Net effect: entry["rcs_outputs"] never
actually contained the raw angle-by-angle data — only plot images — so
anything expecting a raw .dat path from a manifest (e.g. the azimuth
polar overlay in rcs_compare_family.py) was silently finding nothing.
Fixed here, worker-side only: right after each cut's solve, glob
results_dir for the newly-written timestamped .dat file(s) and rename
each to a clean, deterministic {tag}_{AZ|FR}_{TE|TM}.dat — which also
doubles as this stage's own checkpoint marker. run_openrcs.py itself is
NOT touched (it's validated against sphere/plate/almond) — this is
worker-side bookkeeping around it, nothing more.

One cosmetic side effect of splitting the calls: both the azimuth-only
and frontal-only calls each produce their own "mean_table" plot image
(same key). Left as-is these would collide on rename (frontal's would
silently overwrite azimuth's). Fixed by giving mean_table a cut-specific
name (azimuth_mean_table / frontal_mean_table) so both survive — the
actual numeric means (entry["means"]) were never affected by this
either way; this only affects the plot image.
"""
import sys, os, json, glob

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vsp_setup
import openvsp as vsp
import run_openrcs


def _find_section_parm(gid, surf_idx, section_idx, parm_name):
    xsec_surf_id = vsp.GetXSecSurf(gid, surf_idx)
    xsec_id = vsp.GetXSec(xsec_surf_id, section_idx)
    pid = vsp.GetXSecParm(xsec_id, parm_name)
    if not pid:
        raise ValueError(f"Parm '{parm_name}' not found on surf{surf_idx}/sec{section_idx}")
    return pid


def _write(path, entry):
    with open(path, "w") as f:
        json.dump(entry, f, indent=2)


def _export_mesh_checkpoint(cfg, tag, stl_dir, entry, manifest_path):
    """
    Stage 1/3. Skips OpenVSP's CFD-mesh export entirely if the final STL
    already exists on disk (from a previous attempt that got this far).
    Exports to a temp path first, then atomically renames to the final
    name — so a power cut DURING export can never leave a truncated file
    that looks "done" the next time this checkpoint is checked.
    """
    stl_out = os.path.join(stl_dir, f"{tag}.stl")
    if os.path.isfile(stl_out):
        print(f"  [checkpoint] mesh already exists for {tag} — skipping CFD-mesh export")
    else:
        tmp_out = stl_out + ".tmp"
        vsp_setup.export_stl_cfdmesh(
            out_stl_path=tmp_out, freq_ghz=cfg["freq_ghz"],
            min_edge_factor=cfg["min_edge_factor"], max_edge_factor=cfg["max_edge_factor"],
            max_gap_factor=cfg["max_gap_factor"], growth_ratio=cfg["growth_ratio"],
            num_circle_segs=cfg["num_circle_segs"],
        )
        os.replace(tmp_out, stl_out)   # atomic rename — only a complete export ever lands here

    entry["stl_path"] = stl_out
    entry.setdefault("checkpoints", {})["mesh"] = True
    _write(manifest_path, entry)
    return stl_out


def _expected_pol_tags(prefix, pol):
    pol_upper = pol.upper()
    tags = []
    if pol_upper in ("TE-Z", "BOTH"):
        tags.append(f"{prefix}_TE")
    if pol_upper in ("TM-Z", "BOTH"):
        tags.append(f"{prefix}_TM")
    return tags


def _run_cut_checkpoint(cfg, tag, stl_out, rcs_dir, cut_flag, entry, manifest_path):
    """
    Stage 2/3 (cut_flag="azimuth") or 3/3 (cut_flag="frontal").

    Checks for this cut's clean, deterministic .dat filename(s) first. If
    already present (from a previous attempt), skips the PO solve
    entirely and reconstructs this cut's means by re-parsing them —
    _parse_dat/_mean_total are both plain module-level functions in
    run_openrcs.py, safe to reuse without re-running anything.

    Otherwise calls run_openrcs_pipeline() for JUST this cut, then:
      (a) renames its plot outputs tag-wise, same pattern as before
      (b) globs rcs_dir for the newly-written timestamped raw .dat
          file(s) and renames each to the clean name — that rename IS
          the checkpoint marker for next time.

    Returns True if this cut is now done (checkpoint hit or fresh solve
    both count), False on a soft rcs_failed (see below) — callers must
    stop and NOT proceed to the next stage when this returns False.
    """
    prefix = {"azimuth": "AZ", "frontal": "FR"}[cut_flag]
    pol = cfg.get("pol", "TE-z")
    expected_dat_keys = _expected_pol_tags(prefix, pol)
    clean_dat_paths = {k: os.path.join(rcs_dir, f"{tag}_{k}.dat") for k in expected_dat_keys}

    outputs = entry.setdefault("rcs_outputs", {})
    means   = entry.setdefault("means", {})

    if expected_dat_keys and all(os.path.isfile(p) for p in clean_dat_paths.values()):
        print(f"  [checkpoint] {cut_flag} cut already done for {tag} — reusing existing .dat files")
        for k, path in clean_dat_paths.items():
            parsed = run_openrcs._parse_dat(path)
            outputs[k] = path
            means[k] = run_openrcs._mean_total(parsed["sth"], parsed["sph"])
    else:
        print(f"  [checkpoint] running {cut_flag} cut for {tag} ...")
        rcs_out = run_openrcs.run_openrcs_pipeline(
            stl_path=stl_out, results_dir=rcs_dir,
            freq=cfg["freq_ghz"], pol=pol, cuts=cut_flag,
            az_range=cfg.get("az_range", "half"), delp=cfg.get("delp", 1.0),
            frontal_delp=cfg.get("frontal_delp", 1.0),
            frontal_delt=cfg.get("frontal_delt", 1.0),
        )
        if not rcs_out:
            # Soft failure (e.g. a suspected file-lock race), not a Python
            # exception — write status="rcs_failed" and return normally
            # (exit code 0) instead of raising, so rcs_sweep_driver.py's
            # run_one() actually gets a chance to see this status and do
            # its one automatic retry. Raising here (as an earlier version
            # of this function did) makes the worker subprocess exit
            # non-zero, which run_one()'s `except subprocess.
            # CalledProcessError` branch catches and returns False from
            # BEFORE ever reading the manifest — silently disabling that
            # retry entirely. This was a real regression from the
            # checkpointing rewrite; restoring the old worker's plain-return
            # behaviour for this specific case fixes it.
            print(f"  {cut_flag} cut returned no output for {tag} (rcs_failed)")
            entry["status"] = "rcs_failed"
            _write(manifest_path, entry)
            return False

        # Plot images: rename tag-wise as before. "mean_table" is produced
        # by BOTH the azimuth and frontal calls (same key) -- give it a
        # cut-specific name here so the second call's file doesn't
        # silently overwrite the first's.
        for k, path in rcs_out.items():
            if k in ("results_dir", "means") or not path:
                continue
            ext = os.path.splitext(path)[1]
            out_key = f"{cut_flag}_{k}" if k == "mean_table" else k
            new_path = os.path.join(os.path.dirname(path), f"{tag}_{out_key}{ext}")
            os.replace(path, new_path)
            outputs[out_key] = new_path

        # Raw .dat files: written into rcs_dir with a timestamp baked into
        # the name, but never returned by run_openrcs_pipeline at all (see
        # module docstring). Glob for what this call just wrote and rename
        # to the clean, deterministic name -- this rename is the checkpoint.
        for k in expected_dat_keys:
            matches = sorted(
                glob.glob(os.path.join(rcs_dir, f"{tag}_{k}_*.dat")),
                key=os.path.getmtime,
            )
            if not matches:
                print(f"  WARNING: expected a {k} .dat file for {tag} but found none in {rcs_dir}")
                continue
            os.replace(matches[-1], clean_dat_paths[k])   # newest, in case >1 somehow exist
            outputs[k] = clean_dat_paths[k]

        means.update(rcs_out.get("means", {}))

    entry.setdefault("checkpoints", {})[cut_flag] = True
    _write(manifest_path, entry)
    return True


def main():
    cfg = json.loads(sys.argv[1])
    tag = cfg["tag"]
    os.makedirs(cfg["manifest_dir"], exist_ok=True)
    manifest_path = os.path.join(cfg["manifest_dir"], f"{tag}.json")

    # Resume an existing manifest if one is already on disk (e.g. left
    # behind by a power cut mid-run) instead of starting fresh, so
    # earlier stages' checkpoints/outputs/means survive the restart.
    if os.path.isfile(manifest_path):
        with open(manifest_path) as f:
            entry = json.load(f)
        print(f"  [checkpoint] resuming {tag} — checkpoints so far: "
              f"{entry.get('checkpoints', {})}")
    else:
        entry = {
            "tag": tag, "param": cfg["param"], "delta": cfg["delta"],
            "parm_overrides": cfg["parm_overrides"],
        }
    entry["status"] = "running"
    _write(manifest_path, entry)

    try:
        vsp.VSPCheckSetup()
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(cfg["vsp3"])
        vsp.Update()

        vsp_setup.apply_geom_sets(cfg["sets_file"])
        name_to_id = {vsp.GetGeomName(g): g for g in vsp.FindGeoms()}

        # parm_overrides: list of [geom_name, surf_idx, section_idx, parm_name, value]
        # — same override mechanism as the existing aero sweep_worker.py,
        # applying ONLY this one parameter's delta (one-at-a-time, not a
        # full-factorial combination of every parameter at once). Always
        # re-applied on resume too -- it's cheap, and re-applying the same
        # values is harmless, so there's no need to checkpoint this step
        # separately from the mesh export it feeds into.
        applied = {}
        for geom_name, surf_idx, section_idx, parm, val in cfg["parm_overrides"]:
            gid = name_to_id[geom_name]
            pid = _find_section_parm(gid, surf_idx, section_idx, parm)
            vsp.SetParmVal(pid, val)
            applied[f"{geom_name}/{parm}/sec{section_idx}"] = vsp.GetParmVal(pid)
        vsp.Update()
        entry["applied_parms"] = applied

        stl_dir = os.path.join(cfg["results_root"], "stl")
        os.makedirs(stl_dir, exist_ok=True)
        rcs_dir = os.path.join(cfg["results_root"], "rcs")
        os.makedirs(rcs_dir, exist_ok=True)

        stl_out = _export_mesh_checkpoint(cfg, tag, stl_dir, entry, manifest_path)
        # A False return means a soft rcs_failed was already written to the
        # manifest by _run_cut_checkpoint (see its docstring) — stop here,
        # WITHOUT raising, so this process exits 0 and
        # rcs_sweep_driver.py's run_one() gets to see status="rcs_failed"
        # and do its one automatic retry.
        if not _run_cut_checkpoint(cfg, tag, stl_out, rcs_dir, "azimuth", entry, manifest_path):
            return
        if not _run_cut_checkpoint(cfg, tag, stl_out, rcs_dir, "frontal", entry, manifest_path):
            return

        entry["status"] = "done"
        entry.pop("error", None)   # clear any stale error from an earlier interrupted attempt
        _write(manifest_path, entry)

    except Exception as e:
        import traceback
        entry["status"] = "error"
        entry["error"] = f"{e}\n{traceback.format_exc()}"
        _write(manifest_path, entry)
        raise


if __name__ == "__main__":
    main()