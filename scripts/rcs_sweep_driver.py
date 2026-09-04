# -*- coding: utf-8 -*-
"""
rcs_sweep_driver.py — RCS-only shaping-parameter sensitivity study.

For each shaping parameter, one at a time (one-at-a-time deltas from
baseline, NOT full-factorial across parameters simultaneously): applies
each delta to the baseline geometry, exports a CFD-mesh STL, runs it
through OpenRCS (azimuth + frontal-sector cuts, TE-z only), and — once
every delta for that parameter has finished — produces:
  1. mean azimuth RCS  vs. delta   (line plot)
  2. mean frontal RCS  vs. delta   (line plot)
  3. azimuth polar RCS, all deltas overlaid on one polar plot
  4. summary_<param>.csv — delta, means, and every raw output file path,
     so a later trade-off study can reuse this RCS data without
     re-running the (expensive) solver.

Mirrors sweep_driver.py/sweep_worker.py's proven subprocess-per-config +
manifest-based skip/resume pattern, stripped of every aero step — see
rcs_sweep_worker.py. Results land under Results/RCS_SensitivityStudy/,
kept separate from the existing Results/SensitivityStudy/ aero sweep.

Config choices below (pol="TE-z", cuts="azimuth+frontal", az_range="half")
were confirmed with the user; az_range="half" assumes every delta stays
left-right symmetric (both sides moved together) — a delta that breaks
symmetry (e.g. canting only one of two vertical tails) needs
az_range="full" for that specific parameter, or its azimuth mean will
only ever see one side of the aircraft.

Δ=0.0 (baseline) is run exactly ONCE, shared across every parameter —
call run_baseline() before any run_parameter() calls. Every parameter's
delta list should still list 0.0 (it's the anchor point on the plots),
but build_param_configs() skips spawning a worker for it and
_load_done_manifests() splices in the shared baseline manifest instead
— applying "+0" to any parameter produces the identical untouched
geometry, so re-running the (expensive) RCS solve on it once per
parameter would be pure waste.
"""
import subprocess, json, os, sys, csv
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_config import GEOMETRY_DIR, IMPORT_FILE
import run_openrcs  # reused for _parse_dat / _azimuth_to_full_circle — avoids
                     # duplicating the .dat-parsing logic for the polar overlay

VSP3_FILE = str(Path(GEOMETRY_DIR) / IMPORT_FILE)
SETS_FILE = str(Path(GEOMETRY_DIR) / (Path(IMPORT_FILE).stem + "_sets.json"))
# Same "<geometry stem>_sweep_params.json" convention as the existing aero
# sweep_driver.py, but derived from pipeline_config.IMPORT_FILE instead of
# a hardcoded filename, so it always follows whatever geometry main.py is
# currently pointed at.
SWEEP_PARAMS_FILE = str(Path(GEOMETRY_DIR) / (Path(IMPORT_FILE).stem + "_sweep_params.json"))

with open(SWEEP_PARAMS_FILE) as f:
    SWEEP_PARAMS = json.load(f)

RESULTS_ROOT = ROOT_DIR / "Results" / "RCS_SensitivityStudy"
LOG_ROOT     = RESULTS_ROOT / "_logs"
LOG_ROOT.mkdir(parents=True, exist_ok=True)

TIMEOUT_SEC = 60 * 60   # per-delta wall-clock cap; frontal cut (61x7=427 pts) is the slow part

# Same CFD-mesh settings as main.py's USE_CFD_MESH block, TE-z-only /
# azimuth+frontal cuts per the confirmed sensitivity-study scope.
# frontal_delt=5.0 matches Touzopoulos 2017's own elevation resolution
# (theirs is 5 deg, ours is now the same) and cuts the frontal run's
# point count ~4.4x (31 theta rows -> 7); frontal_delp stays at 1.0
# (azimuth-direction) since narrow specular flashes are the concern
# there, same reasoning as keeping the azimuth cut itself at delp=1.0.
BASE = dict(
    vsp3=VSP3_FILE, sets_file=SETS_FILE,
    freq_ghz=12.0, pol="TE-z", cuts="azimuth+frontal",
    az_range="half", delp=1.0,
    frontal_delp=1.0, frontal_delt=5.0,
    min_edge_factor=3, max_edge_factor=1, max_gap_factor=3,
    growth_ratio=1.6, num_circle_segs=12.0,
)

# Delta=0.0 is the SAME physical geometry no matter which parameter's
# sweep it nominally belongs to — applying "+0" to VTCant vs. WingTwist
# vs. anything else all produce the untouched baseline aircraft. Running
# it once here and reusing the result as every parameter's Δ=0 anchor
# point avoids paying for the (expensive) RCS solve on the identical
# baseline geometry once per parameter. See run_baseline() /
# build_param_configs()'s d==0.0 skip / _load_done_manifests()'s splice.
BASELINE_ROOT = RESULTS_ROOT / "_baseline"


def build_baseline_config():
    return {
        **BASE, "tag": "baseline", "param": "baseline", "delta": 0.0,
        "parm_overrides": [],
        "results_root": str(BASELINE_ROOT),
        "manifest_dir": str(BASELINE_ROOT / "manifest"),
    }


def run_baseline():
    """Runs the shared Δ=0 baseline once (manifest-skip makes repeat calls free)."""
    (BASELINE_ROOT / "rcs").mkdir(parents=True, exist_ok=True)
    (BASELINE_ROOT / "stl").mkdir(parents=True, exist_ok=True)
    cfg = build_baseline_config()
    if not run_one(cfg):
        raise RuntimeError(
            "Baseline RCS run failed — every parameter's Δ=0 anchor point "
            "depends on it. Check Results/RCS_SensitivityStudy/_logs/baseline.log"
        )
    return cfg


def _load_baseline_manifest():
    mpath = BASELINE_ROOT / "manifest" / "baseline.json"
    if not mpath.exists():
        raise FileNotFoundError(
            "No shared baseline manifest found — call run_baseline() before "
            "any run_parameter() call."
        )
    with open(mpath) as f:
        return json.load(f)


def _override(param_key, delta):
    spec = SWEEP_PARAMS[param_key]
    return [spec["geom"], spec["surf"], spec["section"], spec["parm"], spec["baseline"] + delta]


def build_param_configs(param_key, deltas, results_root, extra_param_keys=None):
    configs = []
    for d in deltas:
        if d == 0.0:
            continue   # shared baseline covers this — see run_baseline()
        overrides = [_override(param_key, d)]
        for extra_key in (extra_param_keys or []):
            overrides.append(_override(extra_key, d))
        tag = f"{param_key}_{d:+.2f}"
        configs.append({
            **BASE, "tag": tag, "param": param_key, "delta": d,
            "parm_overrides": overrides,
            "results_root": str(results_root),
            "manifest_dir": str(results_root / "manifest"),
        })
    return configs


def run_one(cfg, retry=True):
    manifest_dir = Path(cfg["manifest_dir"])
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_dir / f"{cfg['tag']}.json"
    if manifest_file.exists():
        with open(manifest_file) as f:
            if json.load(f).get("status") == "done":
                print(f"skip {cfg['tag']} — already done"); return True

    log_path = LOG_ROOT / f"{cfg['tag']}.log"
    worker = str(SCRIPT_DIR / "rcs_sweep_worker.py")
    with open(log_path, "w", encoding="utf-8") as logf:
        try:
            subprocess.run([sys.executable, worker, json.dumps(cfg)],
                            stdout=logf, stderr=subprocess.STDOUT, timeout=TIMEOUT_SEC, check=True)
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT — {cfg['tag']} skipped (see {log_path})"); return False
        except subprocess.CalledProcessError:
            print(f"FAILED — {cfg['tag']}, see {log_path}"); return False

    if not manifest_file.exists():
        print(f"RAN BUT NO MANIFEST — {cfg['tag']}"); return False
    with open(manifest_file) as f:
        status = json.load(f).get("status")
    if status == "done":
        print(f"OK {cfg['tag']}"); return True

    if status == "rcs_failed" and retry:
        print(f"RETRYING (possible file-lock race) — {cfg['tag']}")
        manifest_file.unlink(missing_ok=True)
        return run_one(cfg, retry=False)   # one retry only, no infinite loop

    print(f"RAN BUT NOT DONE ({status}) — {cfg['tag']}, see {log_path}"); return False


# ── per-parameter outputs (plots + summary CSV) ────────────────────────────

def _load_done_manifests(param_key, deltas, results_root):
    """Returns [(delta, manifest_dict), ...] sorted by delta, done runs only.
    Δ=0.0 is spliced in from the shared baseline manifest (see
    run_baseline()) rather than a per-parameter "<param>_+0.00" file,
    since build_param_configs() never runs that case per-parameter."""
    manifest_dir = results_root / "manifest"
    rows = []
    for d in deltas:
        if d == 0.0:
            try:
                rows.append((0.0, _load_baseline_manifest()))
            except FileNotFoundError:
                print(f"  [outputs] no shared baseline manifest — skipping Δ=0 for {param_key}")
            continue
        tag = f"{param_key}_{d:+.2f}"
        mpath = manifest_dir / f"{tag}.json"
        if not mpath.exists():
            print(f"  [outputs] no manifest for {tag} — skipping"); continue
        with open(mpath) as f:
            entry = json.load(f)
        if entry.get("status") != "done":
            print(f"  [outputs] {tag} status={entry.get('status')!r} — skipping"); continue
        rows.append((d, entry))
    return sorted(rows, key=lambda r: r[0])


def _plot_mean_vs_delta(rows, tag_key, param_key, ylabel, out_path):
    deltas = [d for d, e in rows if tag_key in e.get("means", {})]
    means  = [e["means"][tag_key] for d, e in rows if tag_key in e.get("means", {})]
    if not deltas:
        print(f"  [outputs] no {tag_key} means to plot for {param_key}"); return None

    fig, ax = plt.subplots(figsize=(7, 4.5), facecolor="white")
    ax.set_facecolor("white")
    ax.plot(deltas, means, color="steelblue", lw=1.4, marker="o", markersize=5, zorder=3)
    baseline_val = np.mean(means)
    if 0.0 in deltas:
        i0 = deltas.index(0.0)
        baseline_val = means[i0]
        ax.plot(deltas[i0], means[i0], marker="o", markersize=9,
                markerfacecolor="none", markeredgecolor="crimson", markeredgewidth=1.6,
                zorder=4, label="baseline (Δ=0)")
        ax.legend(fontsize=9)
    ax.axhline(baseline_val, color="grey", lw=0.6, linestyle=":", zorder=1)
    ax.set_xlabel(f"{param_key}  Δ", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.set_title(f"{param_key} — {ylabel} vs. Δ", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved -> {out_path.name}")
    return out_path


def _plot_azimuth_polar_overlay(rows, param_key, out_path):
    """
    All deltas' azimuth cuts (TE-z co-pol = Sph) overlaid on one polar plot.
    Reuses run_openrcs's own half->full-circle mirror and dat parser so this
    stays visually consistent with the single-run polar maps.
    """
    curves = []
    for d, e in rows:
        dat_path = e.get("rcs_outputs", {}).get("AZ_TE")
        if not dat_path or not os.path.isfile(dat_path):
            continue
        parsed = run_openrcs._parse_dat(dat_path)
        if not len(parsed["sph"]):
            continue
        phi_full, sph_full = run_openrcs._azimuth_to_full_circle(parsed["phi_vals"], parsed["sph"])
        curves.append((d, phi_full, sph_full))
    if not curves:
        print(f"  [outputs] no azimuth .dat files to overlay for {param_key}"); return None

    all_sph = np.concatenate([c[2] for c in curves])
    rcs_max = np.ceil(np.nanmax(all_sph) / 10) * 10
    rcs_min = rcs_max - 60.0

    fig = plt.figure(figsize=(7.5, 7.5), facecolor="#e8e8e8")
    ax = fig.add_subplot(111, polar=True, facecolor="#e8e8e8")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    # Diverging colormap centred on delta=0 so negative/positive deltas read
    # as opposite hues and the baseline (if present) is visually neutral.
    max_abs_delta = max(abs(d) for d, _, _ in curves) or 1.0
    cmap = matplotlib.colormaps["coolwarm"]

    def _rcs_to_r(rcs):
        return np.clip((rcs - rcs_min) / (rcs_max - rcs_min), 0.0, 1.0)

    ring_vals = np.linspace(rcs_min, rcs_max, 7)
    ring_angles = np.linspace(0, 2 * np.pi, 361)
    for rv in ring_vals:
        rr = _rcs_to_r(rv)
        ax.plot(ring_angles, np.full_like(ring_angles, rr), color="grey", lw=0.5, zorder=1)
        if rr > 0.05:
            ax.text(np.deg2rad(105), rr, f"{rv:.0f}", ha="left", va="center",
                    fontsize=7, color="dimgrey", zorder=6)
    for sd in range(0, 360, 30):
        ax.plot([np.deg2rad(sd), np.deg2rad(sd)], [0, 1], color="grey", lw=0.5, zorder=1)

    for d, phi_full, sph_full in curves:
        color = "black" if d == 0.0 else cmap(0.5 + 0.5 * d / max_abs_delta)
        r = _rcs_to_r(sph_full)
        t = np.append(np.deg2rad(phi_full), np.deg2rad(phi_full[0]))
        r = np.append(r, r[0])
        ax.plot(t, r, color=color, lw=1.6 if d == 0.0 else 1.0,
                alpha=1.0 if d == 0.0 else 0.85, zorder=5,
                label=f"Δ={d:+.2f}" + ("  (baseline)" if d == 0.0 else ""))

    ax.legend(loc="lower left", bbox_to_anchor=(-0.15, -0.15), fontsize=7.5, framealpha=0.7)
    spokes = {0: "0°\n(nose)", 90: "90°", 180: "180°\n(tail)", 270: "270°"}
    ax.set_xticks(np.deg2rad(list(spokes.keys())))
    ax.set_xticklabels(list(spokes.values()), fontsize=8)
    ax.set_yticks([])
    ax.grid(False)
    ax.spines["polar"].set_visible(False)
    ax.set_ylim(0, 1)
    fig.suptitle(f"{param_key} — Azimuth RCS overlay, all Δ  (TE-z co-pol Sφ, θ=90°)\n"
                 f"scale: {rcs_min:.0f} dBsm (centre) → {rcs_max:.0f} dBsm (rim)",
                 fontsize=10, y=1.0)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="#e8e8e8")
    plt.close(fig)
    print(f"  saved -> {out_path.name}")
    return out_path


def _write_summary_csv(rows, param_key, out_path):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["delta", "tag", "az_mean_TE_dBsm", "frontal_mean_TE_dBsm",
                    "stl_path", "az_dat_path", "frontal_dat_path"])
        for d, e in rows:
            means = e.get("means", {})
            rcs_out = e.get("rcs_outputs", {})
            w.writerow([
                d, e.get("tag"),
                means.get("AZ_TE", ""), means.get("FR_TE", ""),
                e.get("stl_path", ""),
                rcs_out.get("AZ_TE", ""), rcs_out.get("FR_TE", ""),
            ])
    print(f"  saved -> {out_path.name}")


def build_param_outputs(param_key, deltas, results_root):
    rows = _load_done_manifests(param_key, deltas, results_root)
    if not rows:
        print(f"[outputs] {param_key}: no completed deltas — nothing to plot"); return

    plots_dir = results_root / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    print(f"[outputs] {param_key}: building comparison plots from {len(rows)} completed deltas")

    _plot_mean_vs_delta(rows, "AZ_TE", param_key, "Mean Azimuth RCS (dBsm)",
                         plots_dir / f"{param_key}_AzimuthMean_vs_delta.png")
    _plot_mean_vs_delta(rows, "FR_TE", param_key, "Mean Frontal-Sector RCS (dBsm)",
                         plots_dir / f"{param_key}_FrontalMean_vs_delta.png")
    _plot_azimuth_polar_overlay(rows, param_key, plots_dir / f"{param_key}_AzimuthPolar_overlay.png")
    _write_summary_csv(rows, param_key, results_root / f"summary_{param_key}.csv")


# ── orchestration ───────────────────────────────────────────────────────────

def run_parameter(param_key, deltas, extra_param_keys=None):
    results_root = RESULTS_ROOT / param_key
    (results_root / "rcs").mkdir(parents=True, exist_ok=True)
    (results_root / "stl").mkdir(parents=True, exist_ok=True)

    configs = build_param_configs(param_key, deltas, results_root, extra_param_keys)
    results = {cfg["tag"]: run_one(cfg) for cfg in configs}
    print(json.dumps(results, indent=2))

    build_param_outputs(param_key, deltas, results_root)
    return results


if __name__ == "__main__":
    # Sample fill — reuses the exact param_key names and delta lists
    # sweep_driver.py's own Stage-2 (RUN_RCS=True) block already settled
    # on for an RCS-inclusive run, since those deltas were chosen with
    # solver cost already in mind. Each param_key must exist in
    # SWEEP_PARAMS_FILE (same geom/surf/section/parm/baseline schema the
    # aero sweep already uses) — swap these for your real N parameters
    # once you have them; the 0.0 in every list is the shared baseline
    # (see run_baseline()), not a per-parameter run.
    DELTAS_VT_CANT     = [0.0, -15, -8, 8, 15]
    DELTAS_WING_TWIST  = [0.0, -2, -1, 1, 2]
    DELTAS_WING_SWEEP  = [0.0, -12, -8, -4, 4, 8, 12]

    run_baseline()   # once, shared — every run_parameter() call below reuses it for Δ=0

    run_parameter("VTCant",         DELTAS_VT_CANT)
    run_parameter("WingTwist_sec1", DELTAS_WING_TWIST)
    run_parameter("WingSweep_sec1", DELTAS_WING_SWEEP,
                  extra_param_keys=["WingSweep_sec2", "HTSweep_sec1", "HTSweep_sec2"])
