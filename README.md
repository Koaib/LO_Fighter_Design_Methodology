# LO Fighter Design Methodology

Automated framework for Low Observable fighter aircraft 
design — RCS reduction through aerodynamic shaping.

## Folder Structure

LO_Fighter_Design_Methodology/
├── OpenVSP/
│   └── OpenVSP-3.49.0-win64/        ← gitignored, extract here
├── OpenRCS/
│   └── open-rcs/                       ← gitignored — clone here
│       ├── stl_module.py               STL → coordinates/facetsconverter
│       ├── rcs_functions.py            Physical Optics maths (PO engine)
│       ├── rcs_monostatic.py           Monostatic RCS outer loop
│       ├── rcs_bistatic.py             Bistatic RCS outer loop
│       ├── openrcs.py                  Original OpenRCS GUI (stillworks)
│       └── ...
├── STL_Files/                        ← gitignored
├── VSP_Files/                        ← gitignored
├── STP_Files/                        ← gitignored
├── Results/                          ← gitignored
│   └── RCS/
├── scripts/
│   ├── main.py                       ← main entry point
│   ├── vsp_setup.py                  ← paths and tool launchers
│   └── run_rcs.m                     ← Octave RCS script
├── setup.py                          ← run once to set up
├── requirements.txt
└── README.md

## Downloads Required

| Tool    | Version           | Link                              |
|---------|-------------------|-----------------------------------|
| Python  | 3.11.x            | python.org/downloads              |
| OpenVSP | 3.49.0 win64      | openvsp.org                       |
| OpenRCS | latest(git clone) | github.com/comp-ime-eb-br/open-rcs|

## First Time Setup

### 1. Install Python 3.11
Download from python.org
During install: CHECK "Add Python to PATH"
Verify: open cmd and run `python --version`

### 2. Extract tools into correct folders
OpenVSP-3.49.0-win64/  →  extract into  OpenVSP/
Octave-9.2.0/           →  extract into  Octave/
Final structure must be:
LO_Fighter_Design_Methodology/
├── OpenVSP/
│   └── OpenVSP-3.49.0-win64/
├── Octave/
│   └── Octave-9.2.0/

### 3. Clone OpenRCS
```bash
cd "LO_Fighter_Design_Methodology/OpenRCS"
git clone https://github.com/comp-ime-eb-br/open-rcs
```
This produces OpenRCS/open-rcs/ which is where vsp_setup.py looks.

### 4. Run setup script (from cmd — NOT from IDE)
```bash
cd "path\to\LO_Fighter_Design_Methodology"
python setup.py
```
This creates .venv and installs all dependencies automatically.

### 5. If .venv is broken
Double-click reset_env.bat in the project folder

### 6. Configure IDE interpreter
Point your IDE to the .venv Python:
LO_Fighter_Design_Methodology.venv\Scripts\python.exe

**Spyder:**
Tools → Preferences → Python Interpreter
→ Use the following interpreter
→ browse to `.venv\Scripts\python.exe`
→ restart kernel

**VS Code:**
Ctrl+Shift+P → Python: Select Interpreter → select .venv

### 7. Run the pipeline
```bash
python scripts/main.py
```
That single command does everything:

1. Generates parametric aircraft geometry in OpenVSP
2. Exports VSP3, STEP, and STL files
3. Calls OpenRCS to run the Physical Optics RCS simulation
4. Saves all results to Results/RCS/


## Pipeline Flow

main.py
  │
  ├─ [OpenVSP]  Parametric geometry → aircraft.stl
  │
  └─ [OpenRCS]  run_openrcs.py
        │
        ├─ stl_module.stl_converter()
        │     STL → coordinates.txt + facets.txt
        │
        ├─ rcs_functions.extractCoordinatesData()
        │     Build vertex/face arrays in memory
        │
        └─ rcs_monostatic.rcs_monostatic()
              Physical Optics loop over (phi, theta) angles
                → Results/RCS/
                    ├── rcs_<name>_<timestamp>_plot.png   (RCS vs phi)
                    ├── rcs_<name>_<timestamp>_3d.jpg     (3D model figure)
                    └── rcs_<name>_<timestamp>_results.dat (numerical data)

## Branches

| Branch | Description |
|--------|-------------|
| `main` | Baseline pipeline with MATLAB RCS backend |
| `octave-POFACETS` | Octave + POFACETS backend (no MATLAB license needed) |
| `openRCS` | **Current** — OpenVSP + OpenRCS, fully MATLAB/Octave-free |

## Known Issues

- OpenVSP degen_geom/utilities circular import on Windows when using
  local folder installation. Patched automatically by setup.py.
  Basic geometry and STL export work fully. VSPAero integration
  pending resolution from OpenVSP team.
- MATLAB branch requires MATLAB license and MATLAB on system PATH.
  Octave branch has no such requirement.

  

## Understanding run_openrcs.py

`run_openrcs.py` is the Python equivalent of the old `run_rcs.m` script.
It bridges the OpenVSP STL output to the OpenRCS computation engine.

| Stage | Source File | What it does |
|-------|-------------|--------------|
| STL conversion | `stl_module.py` → `stl_converter()` | Reads STL, extracts unique vertices, writes `coordinates.txt` and `facets.txt` |
| Mesh loading | `rcs_functions.py` → `extractCoordinatesData()` | Loads the two text files into numpy arrays |
| Standard deviation | `rcs_functions.py` → `getStandardDeviation()` | Computes wave-number bk, scattering factors cfac1/cfac2 |
| Polarisation | `rcs_functions.py` → `getPolarization()` | Maps TE-z/TM-z → complex (Et, Ep) amplitudes |
| Normals & areas | `rcs_functions.py` → `productVector()` | Cross-products give face normals, alpha/beta angles, triangle areas |
| Angle loop | `rcs_monostatic.py` → `rcs_monostatic()` | Outer loop over all (phi, theta) pairs |
| Illumination test | inside `rcs_monostatic.py` | n·k ≥ 0 — skips back-facing facets |
| Phase terms | `rcs_functions.py` → `phaseVerticeTriangle()` | Dp, Dq, Do = 2bk·(vertex - ref)·direction |
| Area integral | `rcs_functions.py` → `calculate_Ic()` | Taylor-series Ic with 4 special cases for near-zero arguments |
| Field summation | `rcs_functions.py` → `calculaCampos()` | Accumulates scattered Ets, Eps over all lit facets |
| RCS in dBsm | `rcs_functions.py` → `calculateSth_Sph()` | 10 log10(4π\|sum\|²/λ²) |
| Result files | `rcs_functions.py` → `generateResultFiles()` | Writes `.dat` text file with all angle/RCS columns |
| Plots | `rcs_monostatic.py` → `finalPlot()` | Matplotlib RCS-vs-angle + contour plots |


  