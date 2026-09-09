# -*- coding: utf-8 -*-
"""
aero_stab_mission_worker.py — runs ONE swept configuration, then exits.
Called as: python aero_stab_mission_worker.py '<json config>'

Per config: applies the parameter override(s) to the baseline geometry,
runs the FULL Mach x Altitude aero grid (same points main.py's own
TRIGGER AERO PIPELINE sweeps for the un-swept baseline), computes static
margin at each of those points, then runs the real Raymer (Ch 19)
mission-feasibility check on this config's own aero data. Writes ONE
manifest JSON per config holding every number computed - no separate
SUMMARY CSV here, by design: aero_stab_mission_compare_family.py
aggregates across every config's manifest into whatever summary tables/
plots are needed ACROSS configs, the same division of responsibility
rcs_sweep_worker.py/rcs_compare_family.py already use. That's different
from a per-config human-readable artifact, though: this worker also
writes a Cm-vs-Alpha stability plot (stability/<tag>_cm_alpha.png) and a
mission-feasibility .md report (mission/<tag>.md) for THIS config alone,
mirroring aero_dir's per-study "aero/" folder - both are cheap pure
formatting/plotting steps over numbers already computed here, not new
analysis.

Geometry-override mechanism (_find_section_parm, the geom/sets-loading
sequence) is the same proven pattern already used by sweep_worker.py and
rcs_sweep_worker.py - copied here rather than imported, since none of
these worker scripts share code with each other by this project's own
design choice (see Raymer_sizing_based_mission_check.py's module
docstring for the same reasoning applied to its own aero/engine lookup
classes).

WING AREA: each config's OWN live wing_area_ft2 (read AFTER applying
this config's override, via vsp_setup.get_wing_reference_params) feeds
both the stability CL_TARGET calc and the mission check's wing_area_ft2
argument - exactly how main.py's own live TEST_WING_AREA_FT2 feeds both
of those in the single-geometry pipeline. Mass basis (gross_mass_lbm/
fuel_capacity_lbm, arriving already-computed in cfg from the driver) is
held FROZEN across every config on purpose - see
aero_stab_mission_driver.py's own comment on why.

MISSION EXCEPTIONS: run_raymer_mission_check() catches climb-throttle
shortfalls internally (returns climb_completed=False) but does NOT catch
a cruise thrust shortfall, a lift-margin shortfall, or climb+descent
distance exceeding the design range - those still raise. This worker's
outer try/except still catches them (status="error", exception text in
entry["error"]), so a single infeasible-in-an-unusual-way config can
never crash the whole sweep - it just needs a human (or
compare_family.py) to read that config's own error text rather than a
clean climb_completed=False/feasible=False field.
"""
import sys, os, json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
    # Sibling of manifest/, under this config's own study (or _baseline)
    # root - e.g. .../VT_Cant/manifest -> .../VT_Cant/aero. Passed to
    # both run_vspaero_aero() (so the raw .polar/.csv/3 PNGs land here
    # instead of the shared, project-wide Results/Aero/ used by main.py's
    # own runs) and run_raymer_mission_check()'s aero_search_dir (so the
    # mission check's AeroLookup actually finds them again afterward -
    # without threading this through too, the write-side redirect alone
    # would make every config's mission check fail with FileNotFoundError).
    aero_dir = os.path.join(os.path.dirname(cfg["manifest_dir"]), "aero")
    # Same sibling-of-manifest/ pattern as aero_dir, one folder each for
    # the two per-config artifacts added alongside it: a Cm-vs-Alpha
    # stability plot and a human-readable mission-feasibility .md report -
    # both cheap, pure-visualization/formatting steps over data already
    # computed below (no new VSPAero calls), unlike aero_dir's contents.
    stability_dir = os.path.join(os.path.dirname(cfg["manifest_dir"]), "stability")
    mission_dir = os.path.join(os.path.dirname(cfg["manifest_dir"]), "mission")
    os.makedirs(stability_dir, exist_ok=True)
    os.makedirs(mission_dir, exist_ok=True)
    entry = {"tag": tag, "study": cfg["study"], "delta": cfg["delta"],
              "parm_overrides": cfg["parm_overrides"], "aero_dir": aero_dir, "status": "running"}

    # Checkpoint/resume: the aero grid below is 9 VSPAero calls, the
    # expensive part of this whole config - a crash on point 7 of 9
    # shouldn't force points 1-6 to be redone. If a manifest already
    # exists for this tag (status "running" or "error" from a prior
    # crashed attempt - a "done" one would already have been skipped by
    # the driver before this process was even spawned), reuse whatever
    # aero points it already recorded instead of re-running VSPAero for
    # them. Unlike rcs_sweep_worker.py's own checkpointing (which keys
    # off whether each stage's OUTPUT FILE already exists on disk, so it
    # survives the driver deleting the manifest before a retry), this
    # keys off the manifest itself - simpler to reason about, but it
    # ONLY works if aero_stab_mission_driver.py's retry path leaves the
    # manifest in place (it does - see that file's run_one()).
    already_done_points = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                prior = json.load(f)
            for pt in prior.get("aero_points", []):
                already_done_points[(pt["mach"], pt["alt_ft"])] = pt
        except (json.JSONDecodeError, KeyError):
            pass   # corrupt/partial write from a crash mid-_write() - just start over
        if already_done_points:
            print(f"Resuming {tag}: {len(already_done_points)} aero point(s) already done")

    try:
        vsp.VSPCheckSetup()
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(cfg["vsp3"])
        vsp.Update()

        thin_set, thick_set = vsp_setup.apply_geom_sets(cfg["sets_file"])
        name_to_id = {vsp.GetGeomName(g): g for g in vsp.FindGeoms()}

        applied = {}
        for geom_name, surf_idx, section_idx, parm, val in cfg["parm_overrides"]:
            gid = name_to_id[geom_name]
            pid = _find_section_parm(gid, surf_idx, section_idx, parm)
            vsp.SetParmVal(pid, val)
            applied[f"{geom_name}/{parm}/sec{section_idx}"] = vsp.GetParmVal(pid)
        vsp.Update()
        entry["applied_parms"] = applied

        wing_id = name_to_id[cfg["ref_wing"]]

        # This config's OWN live wing reference - see module docstring
        # for why this (not the frozen mass-basis area) feeds stability
        # and the mission check.
        wing_area_ft2, wing_span_ft, wing_ar = vsp_setup.get_wing_reference_params(wing_id)
        entry["wing_area_ft2"] = wing_area_ft2
        entry["wing_aspect_ratio"] = wing_ar

        # ── AERO: full Mach x Altitude grid, same run_name convention
        # main.py's own TRIGGER AERO PIPELINE uses, so build_polar_arrays/
        # AeroLookup can find all 9 points later using this config's tag
        # as if it were a geom_stem. Points already recorded by a prior
        # crashed attempt (already_done_points, built above) are reused
        # as-is rather than re-run; the manifest is written after EVERY
        # new point (not just at the end) so a crash here never loses
        # more than the one point in progress.
        aero_points = []
        for ALT in cfg["altitude_list"]:
            for M in cfg["mach_list"]:
                prior_pt = already_done_points.get((M, ALT))
                if prior_pt is not None:
                    aero_points.append(prior_pt)
                    continue

                thick_set_this_run = thick_set if M < 1.0 else vsp.SET_NONE
                polar_dst, CD0, K, r2 = vsp_setup.run_vspaero_aero(
                    wing_id=wing_id, altitude_ft=ALT,
                    alpha_start=cfg["alpha_start"], alpha_end=cfg["alpha_end"], alpha_npts=cfg["alpha_npts"],
                    mach_start=M, mach_end=M, mach_npts=1,
                    re_cref_start=cfg["re_cref"], wake_iters=cfg["wake_iters"],
                    thin_geom_set=thin_set, thick_geom_set=thick_set_this_run,
                    ref_mode="auto", x_cg=cfg["x_cg"], y_cg=cfg["y_cg"], z_cg=cfg["z_cg"],
                    run_name=f"{tag}_M{M:.2f}_ALT{int(ALT)}",
                    output_dir=aero_dir,
                )
                if polar_dst is None:
                    entry["aero_points"] = aero_points
                    entry["status"] = "aero_failed"
                    entry["note"] = f"VSPAero failed at M={M}, ALT={ALT} ft"
                    _write(manifest_path, entry); return

                aero_csv = polar_dst.replace(".polar", ".csv")
                df_check = pd.read_csv(aero_csv)
                if (df_check["CDtot"] < 0).any():
                    entry["aero_points"] = aero_points
                    entry["status"] = "aero_diverged"
                    entry["note"] = f"Negative CDtot at M={M}, ALT={ALT} ft - wake iteration did not converge"
                    _write(manifest_path, entry); return

                ld_max_theoretical = (1.0 / (2.0 * (CD0 * K) ** 0.5)) if (CD0 and K and CD0 > 0 and K > 0) else None
                aero_points.append({
                    "mach": M, "alt_ft": ALT, "csv": aero_csv,
                    "CD0": CD0, "K": K, "R2": r2, "LD_max_theoretical": ld_max_theoretical,
                })
                entry["aero_points"] = aero_points
                _write(manifest_path, entry)   # checkpoint - survives a crash on the NEXT point
        entry["aero_points"] = aero_points

        # ── STABILITY: static margin at each of the same 9 points -
        # level-flight CL for the FROZEN gross_mass_lbm on THIS config's
        # own live wing_area_ft2, same formula as main.py's Stability
        # section.
        weight_n = cfg["gross_mass_lbm"] * 0.45359237 * 9.80665
        wing_area_m2 = wing_area_ft2 * 0.09290304
        stability_points = []
        for pt in aero_points:
            _, rho, _, a_sound = vsp_setup.isa_atmosphere(pt["alt_ft"])
            v_mps = pt["mach"] * a_sound
            q_pa = 0.5 * rho * v_mps ** 2
            cl_target = weight_n / (q_pa * wing_area_m2)
            sm, sm_r2 = vsp_setup.compute_static_margin(pt["csv"], cl_target)
            stability_points.append({
                "mach": pt["mach"], "alt_ft": pt["alt_ft"],
                "CL_target": cl_target, "SM": sm, "SM_R2": sm_r2,
            })
        entry["stability_points"] = stability_points

        # Cm vs Alpha, faceted by altitude (same layout main.py's own
        # aero overlay plots use) - one line per Mach per panel, reusing
        # the CMytot column already sitting in each aero point's own CSV
        # (written above by run_vspaero_aero()), no new computation.
        # One plot per CONFIG here, not per (Mach, Altitude) point like
        # main.py's own Stability section does - 9 plots x 49 configs
        # would be disproportionate for a sensitivity sweep; the faceted
        # layout keeps all 9 points visible in one image per config.
        altitudes_sorted = sorted({pt["alt_ft"] for pt in aero_points})
        fig, axes = plt.subplots(1, len(altitudes_sorted), figsize=(5 * len(altitudes_sorted), 5), sharey=True)
        if len(altitudes_sorted) == 1:
            axes = [axes]
        for ax, ALT in zip(axes, altitudes_sorted):
            for pt in aero_points:
                if pt["alt_ft"] != ALT:
                    continue
                df_pt = pd.read_csv(pt["csv"])
                if df_pt["CMytot"].isna().all():
                    continue
                ax.plot(df_pt["Alpha"], df_pt["CMytot"], "-o", ms=4, label=f"M={pt['mach']:.2f}")
            ax.set_xlabel("Alpha (deg)"); ax.set_title(f"{int(ALT)} ft")
            ax.legend(); ax.grid(True, ls="--", alpha=0.6)
        axes[0].set_ylabel("Cm")
        fig.suptitle(f"Cm vs Alpha — {tag}")
        fig.tight_layout()
        cm_alpha_path = os.path.join(stability_dir, f"{tag}_cm_alpha.png")
        fig.savefig(cm_alpha_path, dpi=150)
        plt.close(fig)
        entry["stability_plot_path"] = cm_alpha_path

        # ── MISSION: real Raymer Ch 19 feasibility check on THIS config's
        # own aero data (geom_stem=tag -> AeroLookup finds exactly the 9
        # files just written above, nothing from the baseline run or any
        # other config - aero_search_dir=aero_dir points it at THIS
        # config's own per-study aero/ folder, matching where the loop
        # above actually wrote them).
        import Raymer_sizing_based_mission_check as raymer
        mission_results = raymer.run_raymer_mission_check(
            geom_stem=tag, wing_area_ft2=wing_area_ft2,
            gross_mass_lbm=cfg["gross_mass_lbm"], fuel_capacity_lbm=cfg["fuel_capacity_lbm"],
            design_range_nmi=cfg["design_range_nmi"],
            cruise_mach=cfg["cruise_mach"], cruise_altitude_ft=cfg["cruise_altitude_ft"],
            mach_list=cfg["mach_list"], altitude_list=cfg["altitude_list"],
            custom_engine_deck_path=cfg["custom_engine_deck_path"],
            engine_t_sl_dry_lbf=cfg["engine_t_sl_dry_lbf"], engine_t_sl_ab_lbf=cfg["engine_t_sl_ab_lbf"],
            engine_throttle_ratio=cfg["engine_throttle_ratio"], engine_type=cfg["engine_type"],
            num_engines=cfg["num_engines"],
            aero_search_dir=aero_dir,
        )
        entry["mission_results"] = mission_results

        mission_md_path = os.path.join(mission_dir, f"{tag}.md")
        with open(mission_md_path, "w", encoding="utf-8") as f:
            f.write(raymer.format_mission_results_md(mission_results, title=tag))
        entry["mission_md_path"] = mission_md_path

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
