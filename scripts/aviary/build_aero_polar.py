# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 19:02:48 2026

@author: KK
"""

"""
Reshapes existing VSPAero per-Mach-per-altitude aero CSVs
(Results/Aero/aero_*_M#_ALT#_*.csv) into the flat, unstructured arrays
Aviary's external aero mechanism expects. Only picks up files matching the
current M/ALT naming convention and the current expected grid — legacy
files (pre-altitude naming) and stale duplicate runs are skipped, keeping
only the newest file per (Mach, Altitude) pair.
"""

import os
import glob
import re
import numpy as np
import pandas as pd

import vsp_setup  # reuse existing path setup


def build_polar_arrays(geom_stem, expected_machs=None, expected_altitudes=None):
    pattern = os.path.join(vsp_setup.AERO_RESULTS_DIR, f"aero_{geom_stem}_M*.csv")
    all_files = glob.glob(pattern)
    if not all_files:
        raise FileNotFoundError(f"No aero CSVs found matching {pattern}. Run main.py first.")

    if expected_machs is None:
        expected_machs = {0.2, 0.4, 0.6}
    if expected_altitudes is None:
        expected_altitudes = {0.0, 15000.0, 35000.0}

    # Parse (mach, altitude, timestamp) from each filename, skip anything that
    # doesn't match the current M+ALT naming pattern (legacy pre-altitude files)
    name_re = re.compile(r"_M([0-9.]+)_ALT([0-9.]+)_(\d{8}_\d{6})\.csv$")
    parsed = {}  # (mach, alt) -> (timestamp_str, path)
    skipped_legacy = []

    for path in all_files:
        fname = os.path.basename(path)
        m = name_re.search(fname)
        if not m:
            skipped_legacy.append(fname)
            continue
        mach_val = float(m.group(1))
        alt_val = float(m.group(2))
        timestamp = m.group(3)

        if mach_val not in expected_machs or alt_val not in expected_altitudes:
            continue  # not part of the current grid — old/unrelated run

        key = (mach_val, alt_val)
        if key not in parsed or timestamp > parsed[key][0]:
            parsed[key] = (timestamp, path)  # keep only the newest per (Mach, Alt)

    if skipped_legacy:
        print(f"⚠️  Skipped {len(skipped_legacy)} file(s) not matching current M/ALT naming: {skipped_legacy}")

    csv_files = [p for _, p in parsed.values()]
    if not csv_files:
        raise FileNotFoundError(
            f"No files matched expected grid (Machs={expected_machs}, Altitudes={expected_altitudes}). "
            f"Check MACH_LIST/ALTITUDE_LIST in main.py match what you actually ran."
        )
    print(f"✅ Selected {len(csv_files)} files (latest per Mach/Altitude pair) out of {len(all_files)} found")

    altitude_list, mach_list, alpha_list, cl_list, cd_list = [], [], [], [], []

    for (mach_val, alt_val), (timestamp, path) in parsed.items():

        df = pd.read_csv(path)
        n_total = len(df)
        df = df.dropna(subset=["CL", "CDtot"])  # drop diverged/NaN rows
        n_valid = len(df)

        if n_valid < n_total:
            print(f"⚠️  M={mach_val}, ALT={alt_val}: {n_total - n_valid}/{n_total} points diverged (NaN), dropped")
        if n_valid < 3:
            print(f"⚠️  M={mach_val}, ALT={alt_val}: only {n_valid} valid points — too sparse, may cause extrapolation issues")

        for _, row in df.iterrows():
            altitude_list.append(alt_val)
            mach_list.append(mach_val)
            alpha_list.append(row["Alpha"])
            cl_list.append(row["CL"])
            cd_list.append(row["CDtot"])

    arrays = {
        "altitude": np.array(altitude_list),
        "mach":     np.array(mach_list),
        "alpha":    np.array(alpha_list),
        "cl":       np.array(cl_list),
        "cd":       np.array(cd_list),
    }
    print(f"✅ Built polar arrays from {len(csv_files)} Mach/Altitude files, {len(cl_list)} total points")
    return arrays

def reshape_to_grid(arrays):
    """
    Reshapes the flat (altitude, mach, alpha, cl, cd) arrays from
    build_polar_arrays() into the 3D (n_alt, n_mach, n_alpha) grids
    Aviary's GASP tabular_cruise mechanism expects.
    """
    alt = np.round(arrays["altitude"], 3)
    mach = np.round(arrays["mach"], 3)
    alpha = np.round(arrays["alpha"], 3)
    cl = arrays["cl"]
    cd = arrays["cd"]

    alt_vals = np.sort(np.unique(alt))
    mach_vals = np.sort(np.unique(mach))
    alpha_vals = np.sort(np.unique(alpha))

    n1, n2, n3 = len(alt_vals), len(mach_vals), len(alpha_vals)
    if n1 * n2 * n3 != len(cl):
        raise ValueError(
            f"Grid size mismatch: {n1}x{n2}x{n3}={n1*n2*n3} points expected, "
            f"but got {len(cl)}. Check that every (altitude, Mach) combo has "
            f"exactly {n3} alpha points — a diverged/dropped point will break this."
        )

    lift_grid = np.full((n1, n2, n3), np.nan)
    drag_grid = np.full((n1, n2, n3), np.nan)

    alt_idx = {v: i for i, v in enumerate(alt_vals)}
    mach_idx = {v: i for i, v in enumerate(mach_vals)}
    alpha_idx = {v: i for i, v in enumerate(alpha_vals)}

    for a, m, al, c_l, c_d in zip(alt, mach, alpha, cl, cd):
        i, j, k = alt_idx[a], mach_idx[m], alpha_idx[al]
        lift_grid[i, j, k] = c_l
        drag_grid[i, j, k] = c_d

    if np.isnan(lift_grid).any():
        n_missing = int(np.isnan(lift_grid).sum())
        raise ValueError(
            f"{n_missing} grid cell(s) missing data (NaN) — likely a diverged "
            f"alpha point dropped from one Mach/Altitude run. Grid must be complete."
        )

    print(f"✅ Reshaped to grid: altitude{list(alt_vals)}, mach{list(mach_vals)}, alpha{list(alpha_vals)}")
    return lift_grid, drag_grid


if __name__ == "__main__":
    TEST_GEOM_STEM = "SSAM_final_geom_to_be_used_NOT_scaled_by_19_nozzle_mod"
    arrays = build_polar_arrays(TEST_GEOM_STEM)
    for k, v in arrays.items():
        print(f"   {k}: {len(v)} points, range [{v.min():.4f}, {v.max():.4f}]")