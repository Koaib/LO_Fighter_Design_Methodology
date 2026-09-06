# -*- coding: utf-8 -*-
"""
LO Fighter Design Methodology - Linux/HPC Environment Setup
Run this once before first use: python3 setup.py
"""

import os
import sys
import subprocess
import glob
import shutil

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
OPENVSP_INSTALL_DIR = os.path.join(ROOT_DIR, "OpenVSP")

print("=" * 60)
print("  LO Fighter Design Methodology - Linux HPC Setup")
print("=" * 60)

# ─── Step 1: Check Python version ───────────────────────
print("\n[1/6] Checking Python version...")
major, minor = sys.version_info.major, sys.version_info.minor
if major != 3 or minor < 10:
    print(f"❌ Python 3.10+ required. You have {major}.{minor}")
    sys.exit(1)
print(f"✅ Python {major}.{minor} OK")

# ─── Step 2: Create venv ────────────────────────────────
print("\n[2/6] Creating virtual environment (.venv)...")
venv_path = os.path.join(ROOT_DIR, ".venv")
if os.path.exists(venv_path):
    print("⚠️  .venv already exists — skipping creation")
else:
    subprocess.run([sys.executable, "-m", "venv", ".venv"], check=True)
    print("✅ Virtual environment created")

venv_python = os.path.join(ROOT_DIR, ".venv", "bin", "python")
venv_pip = os.path.join(ROOT_DIR, ".venv", "bin", "pip")

# ─── Step 3: Install requirements ───────────────────────
print("\n[3/6] Installing standard requirements...")
subprocess.run([venv_pip, "install", "--upgrade", "pip"], check=True)
req_file = os.path.join(ROOT_DIR, "requirements.txt")
if os.path.isfile(req_file):
    subprocess.run([venv_pip, "install", "-r", req_file], check=True)
    print("✅ Requirements installed")
else:
    print("⚠️  requirements.txt not found — skipping pip install")

# ─── Step 4: Link OpenVSP & Validate Shared Libraries ───
print(f"\n[4/6] Configuring OpenVSP from {OPENVSP_INSTALL_DIR}...")

if not os.path.isdir(OPENVSP_INSTALL_DIR):
    print(f"❌ {OPENVSP_INSTALL_DIR} not found on {os.uname().nodename}.")
    sys.exit(1)

# Search recursively for _vsp.so across the entire /opt/OpenVSP directory tree
found_sos = glob.glob(os.path.join(OPENVSP_INSTALL_DIR, "**", "_vsp*.so"), recursive=True)

if not found_sos:
    print(f"❌ Could not find _vsp*.so anywhere inside {OPENVSP_INSTALL_DIR}.")
    sys.exit(1)

target_so = found_sos[0]
print(f"   Located binary: {target_so}")

# Check for missing dynamic shared libraries (.so)
ldd_run = subprocess.run(["ldd", target_so], capture_output=True, text=True)
missing_libs = [line.strip() for line in ldd_run.stdout.splitlines() if "not found" in line]

if missing_libs:
    print("❌ Missing system dynamic libraries required by OpenVSP:")
    for lib in missing_libs:
        print(f"   - {lib}")
    print("\nInstall missing packages: sudo apt install -y libglu1-mesa libfltk1.3 libglew2.2 libxmu6 xvfb")
    sys.exit(1)
else:
    print("✅ All required shared libraries (.so) are satisfied")

# Define base paths
vsp_base = os.path.join(OPENVSP_INSTALL_DIR, "python")
openvsp_py_dir = os.path.join(vsp_base, "openvsp")

# Get .venv site-packages path
site_pkgs_output = subprocess.check_output(
    [venv_python, "-c", "import site; print(site.getsitepackages()[0])"],
    text=True
).strip()

# 1. Write comprehensive .pth including submodules
pth_path = os.path.join(site_pkgs_output, "openvsp.pth")
pth_lines = [
    vsp_base,
    openvsp_py_dir,
    os.path.join(vsp_base, "degen_geom"),
    os.path.join(vsp_base, "utilities"),
    os.path.join(vsp_base, "vsp_airfoils"),
]
with open(pth_path, "w") as f:
    f.write("\n".join(pth_lines) + "\n")
print(f"✅ Linked OpenVSP paths into .venv via {pth_path}")

# 2. Write required openvsp_config.py into .venv to prevent import crashes
cfg_path = os.path.join(site_pkgs_output, "openvsp_config.py")
cfg_content = (
    "LOAD_GRAPHICS = False\n"
    "LOAD_FACADE = False\n"
    "LOAD_MULTI_FACADE = False\n"
    "_IGNORE_IMPORTS = True\n"
    "FACADE_PORT = -1\n"
)
with open(cfg_path, "w") as f:
    f.write(cfg_content)
print(f"✅ Created headless config at {cfg_path}")

# ─── Step 5: Patch OpenVSP __init__.py ──────────────────
print("\n[5/6] Patching OpenVSP imports...")

init_candidates = [
    os.path.join(openvsp_py_dir, "openvsp", "__init__.py"),
    os.path.join(openvsp_py_dir, "__init__.py"),
]

target_init = next((f for f in init_candidates if os.path.isfile(f)), None)

if not target_init:
    print("⚠️  openvsp/__init__.py not found — skipping patch")
else:
    try:
        with open(target_init, "r") as f:
            content = f.read()

        old = (
            "\tfrom .degen_geom_parse import *\n"
            "\tfrom .parasite_drag import *\n"
            "\tfrom .surface_patches import *\n"
            "\tfrom .utilities import *"
        )
        new = (
            "\ttry:\n"
            "\t\tfrom .degen_geom_parse import *\n"
            "\t\tfrom .parasite_drag import *\n"
            "\t\tfrom .surface_patches import *\n"
            "\t\tfrom .utilities import *\n"
            "\texcept (ImportError, Exception):\n"
            "\t\tpass"
        )

        if "try:" not in content and old in content:
            with open(target_init, "w") as f:
                f.write(content.replace(old, new))
            print("✅ OpenVSP __init__.py patched successfully")
        else:
            print("⚠️  __init__.py already patched or structure differs — skipping")
    except PermissionError:
        print(f"⚠️  Cannot write to {target_init} (read-only system directory).")
        print("   If imports fail later, apply the patch using sudo.")

# Verify Python import
verify_import = subprocess.run(
    [venv_python, "-c", "import openvsp as vsp; print('Import OK')"],
    capture_output=True, text=True
)
if verify_import.returncode != 0:
    print("❌ Failed to import openvsp in .venv:")
    print(verify_import.stderr)
else:
    print("✅ Verified: 'import openvsp' works cleanly inside .venv")


# ─── Step 6: Verify OpenRCS ─────────────────────────────
print("\n[6/6] Checking OpenRCS installation...")
openrcs_dir = os.path.join(ROOT_DIR, "OpenRCS", "open-rcs")
required_files = [
    "stl_module.py",
    "rcs_functions.py",
    "rcs_monostatic.py",
    "rcs_bistatic.py",
]

if not os.path.isdir(openrcs_dir):
    print("⚠️  OpenRCS directory not found. Clone it before running:")
    print(f"   mkdir -p \"{os.path.join(ROOT_DIR, 'OpenRCS')}\"")
    print(f"   cd \"{os.path.join(ROOT_DIR, 'OpenRCS')}\" && git clone https://github.com/comp-ime-eb-br/open-rcs")
else:
    missing = [f for f in required_files if not os.path.isfile(os.path.join(openrcs_dir, f))]
    if missing:
        print(f"⚠️  OpenRCS missing required files: {missing}")
    else:
        print("✅ OpenRCS present and intact")

# ─── Done ────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  ✅ Linux Setup Complete!")
print("\n  To execute batch runs on headless compute nodes, use:")
print("  source .venv/bin/activate")
print("  xvfb-run -a python scripts/main.py")
print("=" * 60)