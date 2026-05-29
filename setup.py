# -*- coding: utf-8 -*-
"""
Created on Thu May  7 05:10:40 2026

@author: KK
"""

"""
LO Fighter Design Methodology - Environment Setup
Run this once before first use: python setup.py
"""

import os
import sys
import subprocess

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

print("=" * 55)
print("  LO Fighter Design Methodology - Setup")
print("=" * 55)

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

# ─── Step 3: Install requirements ───────────────────────
print("\n[3/6] Installing requirements...")
if os.name == "nt":
    venv_python = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
else:
    venv_python = os.path.join(ROOT_DIR, ".venv", "bin", "python")

subprocess.run([venv_python, "-m", "pip", "install", "--upgrade", "pip"], check=True)
subprocess.run([venv_python, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
print("✅ Requirements installed")

# ─── Step 4: Install OpenVSP Python packages ────────────
print("\n[4/6] Installing OpenVSP Python packages...")

python_dir = os.path.join(ROOT_DIR, "OpenVSP", "OpenVSP-3.49.0-win64", "python")
req_dev = os.path.join(python_dir, "requirements-dev.txt")

if not os.path.exists(req_dev):
    print("❌ OpenVSP not found.")
    print(f"   Expected at: {python_dir}")
    print("   Extract OpenVSP-3.49.0-win64 inside the OpenVSP/ folder")
else:
    subprocess.run(
        [venv_python, "-m", "pip", "install", "-r", req_dev],
        check=True,
        cwd=python_dir
    )
    print("✅ OpenVSP packages installed")

# ─── Step 5: Patch OpenVSP __init__.py ──────────────────
print("\n[5/6] Patching OpenVSP imports...")

init_file = os.path.join(
    ROOT_DIR, "OpenVSP", "OpenVSP-3.49.0-win64",
    "python", "openvsp", "openvsp", "__init__.py"
)

if not os.path.exists(init_file):
    print("⚠️  __init__.py not found — skipping patch")
else:
    with open(init_file, "r") as f:
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

    if "try:" not in content:
        with open(init_file, "w") as f:
            f.write(content.replace(old, new))
        print("✅ OpenVSP __init__.py patched")
    else:
        print("⚠️  Already patched — skipping")
        
# ─── Step 6: Verify OpenRCS is present ──────────────────
print("\n[6/6] Checking OpenRCS installation...")
 
openrcs_dir = os.path.join(ROOT_DIR, "OpenRCS", "open-rcs")
required_files = [
    "stl_module.py",
    "rcs_functions.py",
    "rcs_monostatic.py",
    "rcs_bistatic.py",
]
 
if not os.path.isdir(openrcs_dir):
    print("⚠️  OpenRCS not found. Clone it before running the pipeline:")
    print(f"\n   cd \"{os.path.join(ROOT_DIR, 'OpenRCS')}\"")
    print("   git clone https://github.com/comp-ime-eb-br/open-rcs\n")
else:
    missing = [f for f in required_files
               if not os.path.isfile(os.path.join(openrcs_dir, f))]
    if missing:
        print(f"⚠️  OpenRCS folder found but missing files: {missing}")
    else:
        print("✅ OpenRCS found and looks complete")
      
    
    
# ─── Done ────────────────────────────────────────────────
print("\n" + "=" * 55)
print("  ✅ Setup complete!")
print("\n  Now configure your IDE to use .venv:")
print("\n  Spyder:")
print("  Tools → Preferences → Python Interpreter")
print("  → Use the following interpreter")
print(f"  → {os.path.join(ROOT_DIR, '.venv', 'Scripts', 'python.exe')}")
print("\n  VS Code:")
print("  Ctrl+Shift+P → Python: Select Interpreter → .venv")
print("\n  Then run: python scripts/main.py")
print("=" * 55)