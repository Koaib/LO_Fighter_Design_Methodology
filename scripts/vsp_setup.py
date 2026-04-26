# -*- coding: utf-8 -*-
"""
Created on Thu Apr 16 20:19:24 2026

@author: KK
"""

"""
Portable OpenVSP Setup
"""

import os
import sys

# =========================
# ROOT DIRECTORY (PORTABLE)
# =========================

# This file is inside: Design_Methodology/scripts/
# So go ONE level up → Design_Methodology
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# =========================
# PATH DEFINITIONS
# =========================

VSP_INSTALL = os.path.join(ROOT_DIR, "OpenVSP-3.49.0-win64")
VSP_FILES   = os.path.join(ROOT_DIR, "VSP_Files")
STP_FILES   = os.path.join(ROOT_DIR, "STP_Files")
STL_FILES = os.path.join(ROOT_DIR, "STL_Files")
POFACETS_DIR = os.path.join(ROOT_DIR, "POFACETS", "pofacets4.5", "pofacets4.5")


# =========================
# SAFETY CHECKS
# =========================

if not os.path.exists(VSP_INSTALL):
    raise FileNotFoundError(
        f"\n❌ OpenVSP folder NOT found.\nExpected at:\n{VSP_INSTALL}\n"
        "\n👉 Make sure your folder structure is:\n"
        "Design_Methodology/OpenVSP-3.49.0-win64"
    )

# Create output folder automatically
os.makedirs(VSP_FILES, exist_ok=True)

# =========================
# OPENVSP INITIALIZATION
# =========================

os.add_dll_directory(VSP_INSTALL)
sys.path.insert(0, os.path.join(VSP_INSTALL, "python", "openvsp"))

# =========================
# SAVE FUNCTION FOR VSP FILES
# =========================

def vsp_path(filename):
    """
    Returns full path inside VSP_Files folder
    """
    return os.path.join(VSP_FILES, filename)

# =========================
# SAVE FUNCTION FOR STP FILES
# =========================

def stp_path(filename):
    """
    Returns full path inside STP_Files folder
    """
    return os.path.join(STP_FILES, filename)

# =========================
# SAVE FUNCTION FOR STL FILES
# =========================

def stl_path(filename):
    """
    Returns full path inside STL_Files folder
    """
    return os.path.join(STL_FILES, filename)

# =========================
# OPTIONAL: AUTO NAMING
# =========================

import time

def auto_name(prefix="case"):
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.vsp3"


# =========================
# MATLAB RCS LAUNCHER
# =========================

import subprocess

MATLAB_SCRIPT = os.path.join(ROOT_DIR, "scripts", "run_rcs.m")

def run_matlab_rcs():
    """
    Launches MATLAB headlessly to run run_rcs.m after VSP export.
    Requires MATLAB to be on system PATH.
    To check: open cmd and type 'matlab -help'
    """
    script_dir  = os.path.dirname(MATLAB_SCRIPT)
    script_name = os.path.splitext(os.path.basename(MATLAB_SCRIPT))[0]  # 'run_rcs'

    print("\n🔄 Launching MATLAB to compute RCS...")
    print(f"   Script : {MATLAB_SCRIPT}")
    print(f"   Working dir: {script_dir}\n")

    cmd = [
        "matlab",
        "-batch",                          # headless, no GUI, exits when done
        f"cd('{script_dir}'); {script_name}"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600            # 10 min timeout — increase if model is large
        )
        if result.stdout:
            print("MATLAB output:\n", result.stdout)
        if result.stderr:
            print("MATLAB warnings/errors:\n", result.stderr)
        if result.returncode == 0:
            print("✅ MATLAB RCS computation finished successfully.")
        else:
            print(f"❌ MATLAB exited with code {result.returncode}.")
    except FileNotFoundError:
        print("❌ MATLAB not found on PATH.")
        print("   Either add MATLAB to PATH or run run_rcs.m manually in MATLAB.")
    except subprocess.TimeoutExpired:
        print("❌ MATLAB timed out. Increase timeout or run manually.")