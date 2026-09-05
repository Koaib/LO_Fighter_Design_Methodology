# -*- coding: utf-8 -*-
"""
Created on Thu Aug  6 12:11:30 2026

@author: KK
"""

import json, glob, sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
ROOT_DIR     = SCRIPT_DIR.parent
MANIFEST_DIR = ROOT_DIR / "Results" / "SensitivityStudy" / "Manifest"
OUT_DIR      = ROOT_DIR / "Results" / "SensitivityStudy" / "Comparisons"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_family(prefix):
    entries = []
    for f in sorted(glob.glob(str(MANIFEST_DIR / f"{prefix}_*.json"))):
        with open(f) as fh:
            e = json.load(fh)
        if e.get("status") == "done":
            entries.append(e)
    return entries


def _delta(tag, prefix):
    return float(tag.replace(f"{prefix}_", ""))


def overlay_curves(entries, prefix):
    fig1, ax1 = plt.subplots(figsize=(7,5))
    fig2, ax2 = plt.subplots(figsize=(7,5))
    fig3, ax3 = plt.subplots(figsize=(7,5))
    for e in sorted(entries, key=lambda e: _delta(e["tag"], prefix)):
        df = pd.read_csv(e["aero_csv"])
        label = f"{_delta(e['tag'], prefix):+.1f}°"
        ax1.plot(df["CDtot"], df["CL"], "-o", ms=3, label=label)
        ax2.plot(df["Alpha"], df["CL"], "-o", ms=3, label=label)
        line, = ax3.plot(df["Alpha"], df["L/D"], "-o", ms=3, label=label)
        ax3.plot(e["alpha_at_max_LD"], e["max_LD"], "*", ms=14, color=line.get_color(),
                  markeredgecolor="black", markeredgewidth=0.6)
    ax1.set_xlabel("CD"); ax1.set_ylabel("CL"); ax1.set_title(f"Drag Polar — {prefix}")
    ax1.legend(title="Δ"); ax1.grid(True, ls="--", alpha=0.6)
    ax2.set_xlabel("Alpha (deg)"); ax2.set_ylabel("CL"); ax2.set_title(f"CL-Alpha — {prefix}")
    ax2.legend(title="Δ"); ax2.grid(True, ls="--", alpha=0.6)
    ax3.set_xlabel("Alpha (deg)"); ax3.set_ylabel("L/D"); ax3.set_title(f"L/D-Alpha — {prefix}")
    ax3.legend(title="Δ"); ax3.grid(True, ls="--", alpha=0.6)
    fig1.tight_layout(); fig1.savefig(OUT_DIR / f"{prefix}_drag_polar_overlay.png", dpi=150)
    fig2.tight_layout(); fig2.savefig(OUT_DIR / f"{prefix}_cl_alpha_overlay.png", dpi=150)
    fig3.tight_layout(); fig3.savefig(OUT_DIR / f"{prefix}_ld_alpha_overlay.png", dpi=150)
    plt.close(fig1); plt.close(fig2); plt.close(fig3)


def threshold_curve(entries, prefix):
    deltas = sorted(_delta(e["tag"], prefix) for e in entries)
    ld = {_delta(e["tag"], prefix): e["max_LD"] for e in entries}
    if 0.0 not in ld:
        raise ValueError(f"No baseline (delta=0.0) entry found for '{prefix}' — "
                          f"make sure 0.0 is included in DELTAS.")
    baseline_max_LD = ld[0.0]
    pct = [100.0 * (baseline_max_LD - ld[d]) / baseline_max_LD for d in deltas]
    fig, ax = plt.subplots(figsize=(7,5))
    ax.plot(deltas, pct, "-o", color="darkred")
    ax.axhline(2.0, color="grey", ls="--", label="2% threshold")
    ax.axhline(3.0, color="grey", ls=":", label="3% threshold")
    ax.set_xlabel("Parameter Δ (deg)"); ax.set_ylabel("Max L/D loss (%)")
    ax.set_title(f"Aero degradation vs Δ — {prefix}")
    ax.legend(); ax.grid(True, ls="--", alpha=0.6)
    fig.tight_layout(); fig.savefig(OUT_DIR / f"{prefix}_threshold_curve.png", dpi=150)
    plt.close(fig)
    return dict(zip(deltas, pct))


if __name__ == "__main__":
    prefix = sys.argv[1]
    entries = load_family(prefix)
    if not entries:
        print(f"No completed runs for '{prefix}'"); sys.exit(1)
    overlay_curves(entries, prefix)
    print(json.dumps(threshold_curve(entries, prefix), indent=2))