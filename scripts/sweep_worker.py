# -*- coding: utf-8 -*-
"""
Created on Thu Aug  6 12:09:29 2026

@author: KK
"""

"""
sweep_worker.py — runs ONE sweep config, then exits.
Called as: python sweep_worker.py '<json config>'
run_rcs=False -> Stage 1 aero-only screening.
run_rcs=True  -> Stage 2 full aero + RCS sensitivity point.
"""
import sys, os, json, shutil

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    
import numpy as np
import pandas as pd

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


def _max_LD_from_csv(csv_path):
    df = pd.read_csv(csv_path)
    alpha = df["Alpha"].to_numpy()
    LD    = df["L/D"].to_numpy()
    CL    = df["CL"].to_numpy()
    mask  = np.isfinite(alpha) & np.isfinite(LD) & (alpha >= 0)
    alpha, LD, CL = alpha[mask], LD[mask], CL[mask]
    if len(alpha) < 3:
        i = int(np.argmax(LD))
        return float(LD[i]), float(CL[i]), float(alpha[i])
    coeffs = np.polyfit(alpha, LD, 2)
    fit_alpha = np.linspace(alpha.min(), alpha.max(), 400)
    fit_LD    = np.polyval(coeffs, fit_alpha)
    i_max = int(np.argmax(fit_LD))
    a_at_max = fit_alpha[i_max]
    return float(fit_LD[i_max]), float(np.interp(a_at_max, alpha, CL)), float(a_at_max)


def _write(path, entry):
    with open(path, "w") as f:
        json.dump(entry, f, indent=2)


def main():
    cfg = json.loads(sys.argv[1])
    tag = cfg["tag"]
    os.makedirs(cfg["manifest_dir"], exist_ok=True)
    manifest_path = os.path.join(cfg["manifest_dir"], f"{tag}.json")
    entry = {"tag": tag, "parm_overrides": cfg["parm_overrides"], "status": "running"}

    try:
        vsp.VSPCheckSetup()
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(cfg["vsp3"])
        vsp.Update()

        thin_set, thick_set = vsp_setup.apply_geom_sets(cfg["sets_file"])
        name_to_id = {vsp.GetGeomName(g): g for g in vsp.FindGeoms()}

        # parm_overrides: list of [geom_name, surf_idx, section_idx, parm_name, value]
        applied = {}
        for geom_name, surf_idx, section_idx, parm, val in cfg["parm_overrides"]:
            gid = name_to_id[geom_name]
            pid = _find_section_parm(gid, surf_idx, section_idx, parm)
            vsp.SetParmVal(pid, val)
            applied[f"{geom_name}/{parm}/sec{section_idx}"] = vsp.GetParmVal(pid)
        vsp.Update()
        entry["applied_parms"] = applied

        wing_id = name_to_id[cfg.get("ref_wing", "Main_Wing")]

        # ── AERO ──────────────────────────────────────────────────────────
        polar_dst = vsp_setup.run_vspaero_aero(
            wing_id       = wing_id,
            alpha_start   = cfg["alpha_start"], alpha_end = cfg["alpha_end"],
            alpha_npts    = cfg["alpha_npts"],
            mach_start    = cfg["mach"], mach_end = cfg["mach"], mach_npts = 1,
            re_cref_start = cfg["re_cref"], wake_iters = cfg["wake_iters"],
            thin_geom_set = thin_set, thick_geom_set = thick_set,
            ref_mode      = "auto",
            run_name      = tag,
        )
        if polar_dst is None:
            entry["status"] = "aero_failed"; _write(manifest_path, entry); return

        aero_dir = os.path.join(cfg["sweep_dir"], "aero")
        os.makedirs(aero_dir, exist_ok=True)
        tagged_csv = os.path.join(aero_dir, f"{tag}.csv")
        shutil.copy2(polar_dst.replace(".polar", ".csv"), tagged_csv)
        entry["aero_csv"] = tagged_csv

        df_check = pd.read_csv(tagged_csv)
        if (df_check["CDtot"] < 0).any():
            entry["status"] = "aero_diverged"
            entry["note"] = "Negative CDtot detected — VSPAero wake iteration did not converge"
            _write(manifest_path, entry)
            return

        max_LD, cl_at_max, alpha_at_max = _max_LD_from_csv(tagged_csv)
        entry["max_LD"], entry["CL_at_max_LD"], entry["alpha_at_max_LD"] = max_LD, cl_at_max, alpha_at_max

        # ── RCS (Stage 2 only) ────────────────────────────────────────────
        if cfg.get("run_rcs", False):
            stl_name = f"{tag}.stl"
            stl_out  = vsp_setup.stl_path(stl_name)
            vsp_setup.export_stl_cfdmesh(
                out_stl_path=stl_out, freq_ghz=cfg["freq_ghz"],
                min_edge_factor=cfg["min_edge_factor"], max_edge_factor=cfg["max_edge_factor"],
                max_gap_factor=cfg["max_gap_factor"], growth_ratio=cfg["growth_ratio"],
                num_circle_segs=cfg["num_circle_segs"],
            )
            import run_openrcs
            rcs_out = run_openrcs.run_openrcs_pipeline(
                stl_path=stl_out, results_dir=os.path.join(cfg["sweep_dir"], "rcs"),
                freq=cfg["freq_ghz"], pol=cfg.get("pol", "both"), cuts=cfg.get("cuts", "azimuth"),
                az_range=cfg.get("az_range", "half"), delp=cfg.get("delp", 1.0),
            )
            if not rcs_out:
                entry["status"] = "rcs_failed"; _write(manifest_path, entry); return

            rcs_tagged = {}
            for k, path in rcs_out.items():
                if not path or k == "results_dir": continue
                ext = os.path.splitext(path)[1]
                new_path = os.path.join(os.path.dirname(path), f"{tag}_{k}{ext}")
                os.replace(path, new_path)
                rcs_tagged[k] = new_path
            entry["rcs_outputs"] = rcs_tagged

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