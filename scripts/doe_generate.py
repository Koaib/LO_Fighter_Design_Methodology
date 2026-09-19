# -*- coding: utf-8 -*-
"""
doe_generate.py — one-time step: samples the 150-point Latin Hypercube
design and writes Results/DoE/doe_design_matrix.csv.

Run this ONCE, before distributing doe_run.py or any batch launcher
across machines. Separating generation from running removes the
multi-machine race entirely - no moment where two machines could both
try to create the CSV at the same time.

Usage:
    python doe_generate.py
"""
import os, csv
from scipy.stats.qmc import LatinHypercube, scale

import doe_config as cfg


def generate_design():
    if cfg.DESIGN_MATRIX_CSV.exists():
        print(f"{cfg.DESIGN_MATRIX_CSV} already exists - not overwriting. "
              f"Delete it first if you really want to resample.")
        return

    lo = [cfg.DOE_VARS[v]["range"][0] for v in cfg.VAR_NAMES]
    hi = [cfg.DOE_VARS[v]["range"][1] for v in cfg.VAR_NAMES]
    unit = LatinHypercube(d=len(cfg.VAR_NAMES), seed=cfg.SEED).random(n=cfg.N_POINTS)
    samples = scale(unit, lo, hi)

    tmp_path = str(cfg.DESIGN_MATRIX_CSV) + ".tmp"
    with open(tmp_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag"] + cfg.VAR_NAMES)
        for i, row in enumerate(samples):
            w.writerow([f"DOE_{i:04d}"] + list(row))
    os.replace(tmp_path, cfg.DESIGN_MATRIX_CSV)   # atomic write
    print(f"Design matrix written: {cfg.DESIGN_MATRIX_CSV} ({cfg.N_POINTS} points)")


if __name__ == "__main__":
    generate_design()
