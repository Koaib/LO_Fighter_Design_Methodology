# -*- coding: utf-8 -*-
"""
maneuver_metrics_extractor.py — specific excess power (Ps), sustained
load factor (n_s) and sustained turn rate at ONE fixed flight condition
(Mach 0.6, 15,000 ft, full afterburner, combat weight), computed from
EXISTING VSPAero outputs for every variant of the 5 sensitivity studies
plus the shared baseline.

Added late, for the faculty's "performance metrics" feedback ahead of
the defense - NOT a new solver run. Every number here is derived from
aero data aero_stab_mission_driver.py already generated; this script
only reads it differently. No OpenVSP/VSPAero/OpenRCS call, no existing
file modified.

REUSED, not reimplemented (per the brief):
  - vsp_setup.isa_atmosphere()                           — atmosphere
  - Raymer_sizing_based_mission_check.EngineLookup +
    build_engine_deck.build_deck(), same engine params
    aero_stab_mission_driver.py itself uses (17800/29100 lbf,
    throttle_ratio=1.07, low_bypass_mixed_flow_turbofan, 2 engines)
                                                           — engine deck
  - aero_stab_mission_compare_family.load_family()        — manifest
    loading, path resolution, per-study baseline splicing (same
    5-studies-plus-shared-baseline structure every other script uses)
  - aero_stab_mission_compare_family.build_summary_rows() — absolute
    parameter value per tag (same affine spec_baseline+delta identity)
  - aero_stab_mission_compare_family._point_at()          — exact
    (mach, alt) match against a variant's own aero_points list

CD(CL): linear interpolation of the variant's OWN converged CL-CDtot
sweep at EXACTLY Mach=0.6/15000ft (a real grid point - ALTITUDE_LIST
already includes 15000 ft, no altitude blending needed), sorted by CL -
mirrors Raymer_sizing_based_mission_check.AeroLookup.cd_for_cl()'s own
algorithm (same sort + np.interp), applied directly against the exact
CSV each variant's manifest already names, rather than re-discovering
it through AeroLookup's glob-based search - needed anyway to get this
slice's own CL bounds for the no-extrapolation check below, which
AeroLookup.cd_for_cl() alone doesn't expose.

NEVER EXTRAPOLATED: if the required CL at n=1 is outside this variant's
own tested CL range at this condition, Ps_1g is still computed (it
needs CL at n=1 only) but n_s is left as NaN with a flag; if the
*solve* for n_s would need CL beyond the tested range (thrust still
exceeds drag at the max tested CL), n_s is likewise left NaN with a
flag - never silently pulled from outside the data.
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import brentq

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import vsp_setup
import Raymer_sizing_based_mission_check as raymer
import aero_stab_mission_compare_family as compare_family

# ── flight condition (constants) ────────────────────────────────────────
MACH = 0.6
ALT_FT = 15000.0
THROTTLE = 1.0

W0_LBM = 83800.0
WF_CAP_LBM = 18065.0
W_COMBAT_LBM = W0_LBM - 0.5 * WF_CAP_LBM  # 74767.5 lbm, combat weight (50% internal fuel)

LBM_TO_KG = raymer.LBM_TO_KG
G = raymer.G
LBF_TO_N = raymer.LBF_TO_N
FT_TO_M = raymer.FT_TO_M

OUT_DIR = os.path.join(compare_family.RESULTS_ROOT, "Comparisons")


def _engine_lookup():
    """Same engine deck aero_stab_mission_driver.py itself builds (see
    that file's ENGINE_T_SL_DRY_LBF/ENGINE_T_SL_AB_LBF/ENGINE_THROTTLE_
    RATIO/ENGINE_TYPE/NUM_ENGINES - confirmed identical to
    Raymer_sizing_based_mission_check.run_raymer_mission_check()'s own
    defaults), rebuilt here (a few-millisecond, pure-formula write, not
    a solver run) rather than importing a private driver constant."""
    deck_path = raymer.build_deck(
        out_dir=os.path.join(vsp_setup.GENERATED_FILES, "engines"),
        deck_name="maneuver_metrics_f100_pw229.deck",
        t_sl_dry=17800.0, t_sl_ab=29100.0, throttle_ratio=1.07,
        engine_type="low_bypass_mixed_flow_turbofan",
    )
    return raymer.EngineLookup(deck_path, num_engines=2)


def _manifest_dir_for(entry):
    """This variant's own output dir for the maneuver manifest - a
    "maneuver/" dir SIBLING to manifest/ (same pattern aero_stab_
    mission_worker.py already uses for aero/, stability/ and mission/ -
    all siblings of manifest/, never inside it), NOT manifest/ itself.

    Writing into manifest/ was the original design (matching the brief's
    own "next to the existing manifest" wording literally) and caused a
    real, serious bug: aero_stab_mission_compare_family.load_family()
    globs manifest/*.json with NO filter beyond that - so on any SECOND
    run, it swept up this script's own previously-written
    <tag>_maneuver_manifest.json files as if they were additional aero
    manifests. Those files have no "aero_points" field, so they were
    (correctly, given what load_family() handed this script) flagged
    "no aero point found" - and because they sort alphabetically AFTER
    the real "<tag>.json" entry, processing them LATER silently
    overwrote that run's own correct earlier result with "missing".
    Confirmed directly: a real variant's SOURCE manifest had
    aero_points covering Mach=0.6/15000ft exactly, but this script's
    own prior output for that same tag, re-ingested as a fake "aero
    entry" by load_family(), had none - so the fake entry's "missing"
    clobbered the real entry's "done". Not a data problem - a self-
    inflicted one, from writing into a directory this script doesn't
    own the glob scope of. maneuver/ keeps manifest/ exclusively the
    real aero manifests, so this can't happen again regardless of how
    many times either script reruns.

    Prefers the real on-disk <study>/manifest/<tag>.json location (to
    find the right study/maneuver/ dir); falls back to the shared
    _baseline/maneuver/ dir for a per-study-SPLICED baseline row (see
    aero_stab_mission_compare_family._splice_baseline_for_study() -
    those rows are relabeled in memory only, no <study>/manifest/<tag>.json
    ever exists for them on disk)."""
    study_dir = os.path.join(compare_family.RESULTS_ROOT, entry["study"])
    tag_path = os.path.join(study_dir, "manifest", f"{entry['tag']}.json")
    if os.path.isfile(tag_path):
        return os.path.join(study_dir, "maneuver")
    return os.path.join(os.path.dirname(os.path.dirname(compare_family.BASELINE_MANIFEST)), "maneuver")


def compute_for_entry(entry, abs_val, engine, q, V, T_N, W_N):
    tag = entry.get("tag", "?")
    flags = []
    out = {
        "tag": tag, "study": entry.get("study"), "delta": entry.get("delta"),
        "parameter_value": abs_val, "status": "missing",
        "Mach": MACH, "altitude_ft": ALT_FT, "throttle": THROTTLE,
        "W_combat_N": W_N, "S_m2": None,
        "q_Pa": q, "V_ms": V, "T_N": T_N,
        "CL_1g": None, "D_1g_N": None, "Ps_1g_ms": None, "Ps_1g_fpm": None,
        "n_s": None, "CL_at_ns": None, "turn_rate_dps": None, "turn_radius_m": None,
        "drag_method": "linear_interp_CL_sorted", "n_s_parabolic_check": None,
        "flags": flags,
    }

    if entry.get("status") != "done":
        flags.append(f"variant status={entry.get('status')!r} (not done) - skipped")
        return out

    pt = compare_family._point_at(entry.get("aero_points", []), MACH, ALT_FT)
    if pt is None:
        flags.append(f"no aero point at Mach={MACH}, alt_ft={ALT_FT} - skipped")
        return out

    wing_area_ft2 = entry.get("wing_area_ft2")
    if not wing_area_ft2:
        flags.append("no wing_area_ft2 on this variant - skipped")
        return out
    S_m2 = wing_area_ft2 * (FT_TO_M ** 2)
    out["S_m2"] = S_m2

    try:
        df = pd.read_csv(pt["csv"])
    except Exception as e:
        flags.append(f"could not read {pt.get('csv')!r}: {e} - skipped")
        return out
    if "CL" not in df.columns or "CDtot" not in df.columns or df.empty:
        flags.append(f"{pt.get('csv')!r} has no usable CL/CDtot data - skipped")
        return out

    cl_arr = df["CL"].to_numpy(dtype=float)
    cd_arr = df["CDtot"].to_numpy(dtype=float)
    finite = np.isfinite(cl_arr) & np.isfinite(cd_arr)
    cl_arr, cd_arr = cl_arr[finite], cd_arr[finite]
    if len(cl_arr) < 2:
        flags.append("fewer than 2 valid (CL, CDtot) points - skipped")
        return out
    order = np.argsort(cl_arr)
    cl_sorted, cd_sorted = cl_arr[order], cd_arr[order]
    cl_min, cl_max = float(cl_sorted[0]), float(cl_sorted[-1])

    def cd_for_cl(cl):
        return float(np.interp(cl, cl_sorted, cd_sorted))

    def drag_N(n):
        cl = n * W_N / (q * S_m2)
        return q * S_m2 * cd_for_cl(cl), cl

    # this variant has converged data at the condition - from here on it
    # is "done" even if a flag below means n_s itself couldn't be solved.
    out["status"] = "done"

    CL1 = 1.0 * W_N / (q * S_m2)
    if CL1 < cl_min or CL1 > cl_max:
        flags.append(f"CL at 1g ({CL1:.4f}) outside tested range "
                      f"[{cl_min:.4f}, {cl_max:.4f}] - CL out of range, Ps_1g not computed")
    else:
        D1, _ = drag_N(1.0)
        Ps_1g = V * (T_N - D1) / W_N
        out["CL_1g"] = CL1
        out["D_1g_N"] = D1
        out["Ps_1g_ms"] = Ps_1g
        out["Ps_1g_fpm"] = Ps_1g * 196.850394
        # Plausibility guard, not a correctness check: D(1g) more than
        # 2x the available thrust at a cruise-ish CL (~0.3 for this
        # aircraft, well below stall) would be an extraordinary drag
        # coefficient for level flight - far more likely a noisy/outlier
        # CDtot point in this variant's own sweep landing right at CL1
        # than a real aerodynamic result. Interpolation still runs (CL1
        # IS inside the tested range, so this isn't extrapolation) and
        # Ps_1g is still reported for transparency - just flagged, not
        # silently trusted the same as a sane value.
        if D1 > 2.0 * T_N:
            flags.append(f"Ps_1g looks implausible: D(1g)={D1:.0f} N is >2x available "
                          f"thrust ({T_N:.0f} N) at CL_1g={CL1:.4f} - likely a noisy/outlier "
                          f"CDtot point in this variant's sweep near that CL, not a real "
                          f"result; check the raw CSV before using this number")

    n_upper = cl_max * q * S_m2 / W_N
    if n_upper <= 1.0:
        flags.append(f"max tested CL ({cl_max:.4f}) doesn't reach n=1 at this weight - "
                      f"CL out of range, n_s not computed")
    else:
        f_lo = T_N - drag_N(1.0)[0]
        f_hi = T_N - drag_N(n_upper)[0]
        if f_lo < 0:
            flags.append("cannot sustain 1g at this condition (D(1g) > T) - n_s not computed")
        elif f_hi > 0:
            flags.append(f"n_s would require CL beyond the tested max ({cl_max:.4f}) - "
                          f"CL out of range, n_s not computed (not extrapolated)")
        else:
            n_s = brentq(lambda n: T_N - drag_N(n)[0], 1.0, n_upper, xtol=1e-10)
            D_ns, CL_ns = drag_N(n_s)
            out["n_s"] = n_s
            out["CL_at_ns"] = CL_ns
            out["turn_rate_dps"] = math.degrees(G * math.sqrt(n_s ** 2 - 1) / V)
            out["turn_radius_m"] = V ** 2 / (G * math.sqrt(n_s ** 2 - 1))
            resid = abs(T_N - D_ns)
            if resid > 1e-3 * T_N:
                flags.append(f"brentq residual {resid:.2f} N exceeds 0.1% of T "
                              f"({1e-3 * T_N:.2f} N)")

    CD0, K = pt.get("CD0"), pt.get("K")
    if CD0 and K and CD0 > 0 and K > 0:
        n_sq = (T_N - q * S_m2 * CD0) * (q * S_m2) / (K * W_N ** 2)
        if n_sq > 0:
            out["n_s_parabolic_check"] = math.sqrt(n_sq)

    out["flags"] = flags
    return out


def main():
    print(f"Flight condition: Mach={MACH}, Alt={ALT_FT:.0f} ft, throttle={THROTTLE}")
    print(f"W_combat = {W_COMBAT_LBM} lbm (W0={W0_LBM} - 0.5*Wf_cap={WF_CAP_LBM})")

    T_K, rho, mu, a_sound = vsp_setup.isa_atmosphere(ALT_FT)
    V = MACH * a_sound
    q = 0.5 * rho * V ** 2
    print(f"Atmosphere: T={T_K:.2f} K, rho={rho:.5f} kg/m3, a={a_sound:.2f} m/s")
    print(f"V = {V:.3f} m/s   q = {q:.3f} Pa")

    engine = _engine_lookup()
    T_lbf, fuel_flow = engine.thrust_and_fuel_flow(MACH, ALT_FT, THROTTLE)
    T_N = T_lbf * LBF_TO_N
    print(f"Thrust (2 engines, full afterburner): {T_lbf:.1f} lbf = {T_N:.1f} N")

    W_N = W_COMBAT_LBM * LBM_TO_KG * G
    print(f"W_combat = {W_N:.1f} N")

    done, other = compare_family.load_family()
    print(f"\nFound {len(done)} finished config(s), {len(other)} not-done.")
    if not done:
        print("Nothing to process - run aero_stab_mission_driver.py first.")
        raise SystemExit(0)

    summary_rows = compare_family.build_summary_rows(done, MACH, ALT_FT)
    abs_val_by_tag = {r["tag"]: r["absolute_value"] for r in summary_rows}

    results = []
    files_written = []
    for entry in done:
        abs_val = abs_val_by_tag.get(entry.get("tag"))
        res = compute_for_entry(entry, abs_val, engine, q, V, T_N, W_N)
        results.append(res)

        manifest_dir = _manifest_dir_for(entry)
        os.makedirs(manifest_dir, exist_ok=True)
        out_path = os.path.join(manifest_dir, f"{entry.get('tag')}_maneuver_manifest.json")
        with open(out_path, "w") as f:
            json.dump(res, f, indent=2)
        files_written.append(out_path)
        flag_str = f" [{'; '.join(res['flags'])}]" if res["flags"] else ""
        n_s_str = "None" if res["n_s"] is None else f"{res['n_s']:.3f}"
        ps_str = "None" if res["Ps_1g_fpm"] is None else f"{res['Ps_1g_fpm']:.0f}"
        print(f"  {entry.get('tag'):28s} status={res['status']:8s} "
              f"n_s={n_s_str}  Ps_1g_fpm={ps_str}{flag_str}")

    # ── sanity checks ────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("SANITY CHECKS")
    print("=" * 72)

    # 1. CL_req at GROSS weight, this condition, must be 0.3303
    W0_N = W0_LBM * LBM_TO_KG * G
    S0_m2 = None
    baseline_entries = [e for e in done if e.get("delta") == 0.0]
    if baseline_entries:
        S0_ft2 = baseline_entries[0].get("wing_area_ft2")
        if S0_ft2:
            S0_m2 = S0_ft2 * (FT_TO_M ** 2)
    if S0_m2:
        CL_req_gross = W0_N / (q * S0_m2)
        ok1 = abs(CL_req_gross - 0.3303) < 5e-4
        print(f"1. CL_req @ W0, Mach={MACH}, {ALT_FT:.0f} ft = {CL_req_gross:.4f} "
              f"(expected 0.3303) -> {'PASS' if ok1 else 'FAIL'}")
        if not ok1:
            print("   STOPPING: sanity check 1 failed - do not trust the numbers below.")
            raise SystemExit(1)
    else:
        print("1. SKIPPED - no baseline wing_area_ft2 found")

    # 2. Baseline hand check against the parabolic polar
    baseline_res = next((r for r in results if r["delta"] == 0.0 and r["status"] == "done"), None)
    if baseline_res:
        print(f"2. Baseline hand check (parabolic polar CD0=0.035751, K=0.180887):")
        print(f"   computed n_s (table)      = {baseline_res['n_s']}")
        print(f"   computed n_s (parabolic)  = {baseline_res['n_s_parabolic_check']}  (expect ~2.9 g)")
        print(f"   computed turn_rate (deg/s)= {baseline_res['turn_rate_dps']}  (expect ~7.8 deg/s)")
        print(f"   computed Ps_1g (m/s)      = {baseline_res['Ps_1g_ms']}  "
              f"({baseline_res['Ps_1g_fpm']} ft/min)  (expect ~75 m/s, ~14700 ft/min)")
    else:
        print("2. SKIPPED - no done baseline result")

    # 3. |T - D(n_s)| < 0.1% of T for every variant with a valid n_s
    bad3 = [r for r in results if r["n_s"] is not None
            and any("residual" in f for f in r["flags"])]
    print(f"3. |T - D(n_s)| < 0.1% of T: {len(bad3)} violation(s) "
          f"out of {sum(1 for r in results if r['n_s'] is not None)} solved")

    # 4. Ps_1g > 0 exactly when n_s > 1
    mismatches = [r for r in results if r["Ps_1g_ms"] is not None and r["n_s"] is not None
                  and ((r["Ps_1g_ms"] > 0) != (r["n_s"] > 1.0))]
    print(f"4. Ps_1g>0 iff n_s>1: {len(mismatches)} mismatch(es) "
          f"(edge cases where n_s is NaN due to CL range aren't counted as violations)")

    # 5. valid-variant counts per study
    print("5. Variants with valid (done) metrics per study:")
    by_study = {}
    for r in results:
        by_study.setdefault(r["study"], [0, 0])
        by_study[r["study"]][1] += 1
        if r["status"] == "done" and r["n_s"] is not None:
            by_study[r["study"]][0] += 1
    for study, (valid, total) in sorted(by_study.items()):
        print(f"   {study:28s} {valid}/{total}")

    print("\n" + "=" * 72)
    print(f"Wrote {len(files_written)} maneuver manifest(s):")
    for p in files_written:
        print(f"  {p}")


if __name__ == "__main__":
    main()
