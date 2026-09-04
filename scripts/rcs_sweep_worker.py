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
"""
import sys, os, json, shutil

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vsp_setup
import openvsp as vsp


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


def main():
    cfg = json.loads(sys.argv[1])
    tag = cfg["tag"]
    os.makedirs(cfg["manifest_dir"], exist_ok=True)
    manifest_path = os.path.join(cfg["manifest_dir"], f"{tag}.json")
    entry = {
        "tag": tag, "param": cfg["param"], "delta": cfg["delta"],
        "parm_overrides": cfg["parm_overrides"], "status": "running",
    }

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
        # full-factorial combination of every parameter at once).
        applied = {}
        for geom_name, surf_idx, section_idx, parm, val in cfg["parm_overrides"]:
            gid = name_to_id[geom_name]
            pid = _find_section_parm(gid, surf_idx, section_idx, parm)
            vsp.SetParmVal(pid, val)
            applied[f"{geom_name}/{parm}/sec{section_idx}"] = vsp.GetParmVal(pid)
        vsp.Update()
        entry["applied_parms"] = applied

        # ── STL export (CFD mesh, same settings as main.py) ───────────────
        stl_dir = os.path.join(cfg["results_root"], "stl")
        os.makedirs(stl_dir, exist_ok=True)
        stl_out = os.path.join(stl_dir, f"{tag}.stl")
        vsp_setup.export_stl_cfdmesh(
            out_stl_path=stl_out, freq_ghz=cfg["freq_ghz"],
            min_edge_factor=cfg["min_edge_factor"], max_edge_factor=cfg["max_edge_factor"],
            max_gap_factor=cfg["max_gap_factor"], growth_ratio=cfg["growth_ratio"],
            num_circle_segs=cfg["num_circle_segs"],
        )
        entry["stl_path"] = stl_out

        # ── RCS ──────────────────────────────────────────────────────────
        import run_openrcs
        rcs_dir = os.path.join(cfg["results_root"], "rcs")
        rcs_out = run_openrcs.run_openrcs_pipeline(
            stl_path=stl_out, results_dir=rcs_dir,
            freq=cfg["freq_ghz"], pol=cfg.get("pol", "TE-z"),
            cuts=cfg.get("cuts", "azimuth+frontal"),
            az_range=cfg.get("az_range", "half"), delp=cfg.get("delp", 1.0),
        )
        if not rcs_out:
            entry["status"] = "rcs_failed"; _write(manifest_path, entry); return

        # Tag every output file with this delta's tag so multiple deltas'
        # outputs don't collide in the shared per-parameter rcs/ folder
        # (same rename-after-the-fact pattern as the aero sweep_worker.py's
        # Stage-2 RCS handling).
        rcs_tagged = {}
        for k, path in rcs_out.items():
            if k in ("results_dir", "means") or not path:
                continue
            ext = os.path.splitext(path)[1]
            new_path = os.path.join(os.path.dirname(path), f"{tag}_{k}{ext}")
            os.replace(path, new_path)
            rcs_tagged[k] = new_path
        entry["rcs_outputs"] = rcs_tagged
        entry["means"] = rcs_out.get("means", {})

        entry["status"] = "done"
        _write(manifest_path, entry)

    except Exception as e:
        import traceback
        entry["status"] = "error"
        entry["error"] = f"{e}\n{traceback.format_exc()}"
        _write(manifest_path, entry)
        raise


if __name__ == "__main__":
    main()
