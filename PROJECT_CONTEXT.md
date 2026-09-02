# LO Fighter Design Methodology — Project Context

Compiled from: Claude 1 export (132 conversations, Nov 2025–Aug 2026), Claude 2 export (61 conversations, May–Sep 2026), and cross-session memory. Last compiled: 2026-09-02.

This file is meant to be dropped into the repo root and pointed at from Claude Code / a fresh Claude chat so it doesn't need to re-derive project state from scratch.

## 1. Project Identity

* Title: Design Methodology for Low Observable (Low RCS) Modern Fighter Aircraft through Aerodynamic Shaping (feasibility-report title: "...using Aerodynamic Feature Shaping")
* Type: Final-Year Project (FYP), CAE NUST Risalpur (PAF College of Aeronautical Engineering), Aerospace Engineering, 8th semester
* Student: Koaib
* Supervisor: S/L Bilal Mufti (Georgia Tech PhD)
* Client: ADIC (Aerospace Design and Integration Centre) — this is an RFP-driven, client-scoped project, not a free-form academic one. The ADIC feasibility report / PDD ("Desired Outcome") paragraph is the authoritative source for what's actually contracted.
* Core deliverable: A reusable, open-source, config-driven Python pipeline (single entry point) that ADIC engineers can run independently — the deliverable is the methodology/tool, not a fixed aircraft design.
* Repo: `Koaib/LO_Fighter_Design_Methodology` on GitHub (not `_Archive`), managed via GitHub Desktop. Local root: `D:\LO_Fighter_Design_Methodology\` — must stay on `D:\`, not OneDrive (OneDrive's filesystem filter driver locks files and prevents `vspaero.exe` from writing output).

### Scope boundaries (explicit, from the feasibility report)

* Aerodynamic shaping only — materials/coatings/RAM are out of scope.
* ADIC's actual contracted "Design Trade-off & Integration" deliverable, verbatim: "Mission profile comparison against the baseline (same weight class)." No MDAO, no coupled trajectory optimization, no gradient-based anything required. This became the key reference point in the Aviary scope debate (see §6).
* Supervisor is skeptical of DoE/ML surrogate approaches; favors direct parametric physics-based sweeps. This shapes all architectural decisions — surrogate/DNN work is explicitly deferred / future-work, not core.

### Baseline & references

* Baseline: F-16C / SSAM Gen-5 geometry (open-source data, no-strake, full-scale ~19 m)
* Methodology grounded in Hines (2001) Georgia Tech PhD thesis (DoE/RSM/PO on F/A-18C) — read in full (242 pages), adapted rather than copied
* RCS validation: Touzopoulos et al. 2017; canonical benchmarks: NASA almond (Woo et al. 1993), flat plate, sphere
* Aerodynamic validation: SSAM Gen-5 wind-tunnel test (WTT) data — Giannelis, Bykerk & Vio, Aerospace 2023. Table 1 gives Sref = 0.1091 m², cref (MAC) = 0.2265 m, load-cell/CG location; Figure 2 gives the body-axis convention with nose-up-positive Cm (quoted directly from the paper, confirmed in-session).
* PO polarization theory: Barile 1984 (duality theorem)
* Closest analog MDO paper: Taj et al. 2023 (from supervisor's institutional network) — used for novelty positioning against existing aero-stealth trade-off literature
* External consultant: Rob McDonald (OpenVSP author), consulted via the OpenVSP Google Group for geometry/meshing issues

## 2. Pipeline Architecture

Single Python entry point integrating four tools, orchestrated via `main.py`:

1. **OpenVSP 3.49.0** — parametric geometry generation
   * Active geometry: `SSAM_final_geom_to_be_used_scaled_by_19_simplified.vsp3` (no-strake, full-scale, ~19 m)
   * A separate WTT-scale (0.75 m wind-tunnel-model scale) geometry is used for aero validation against Giannelis/Bykerk/Vio
   * Strake removal is a deliberate methodology decision: VLM can't capture nonlinear leading-edge-vortex physics, so including strakes would give meaningless VLM results anyway
2. **VSPAero (VLM/panel)** — aerodynamic analysis
   * Driver files: `sweep_driver.py`, `sweep_worker.py`, `vsp_setup.py`
   * Sweep families: `WingSweep_aligned_S1`, `WingSweep_misaligned_S1`, `VTCant_S1` (`WingTwist` planned/mentioned in report outline, TE-sweep/`Sweep_Location` discussed but deferred; fuselage/chine/nose-angle params deprioritized — same VLM-can't-capture-vortex-lift reasoning as strakes)
   * Validity range: Mach ≤ ~0.65–0.7 (results near that ceiling should be treated with caution)
3. **OpenRCS (Physical Optics)** — monostatic RCS
   * github.com/comp-ime-eb-br/open-rcs, included as a git submodule
   * Fixed settings: 12 GHz, theta = 90°, phi swept 0–360° at 1° steps, TE-z polarization, PEC surface (dual-pol runs add no information — see §7)
4. **NASA Aviary** — mission analysis
   * Used purely for fixed-geometry/fixed-mass mission analysis (no sizing/optimization loop)
   * Cross-checked against a hand-rolled Breguet range script
   * Files: `build_engine_deck.py`, `build_aero_polar.py`, `external_aero_builder.py`, `run_aviary.py`, `phase_info.py`, plus supporting scripts

### Environment

* `.venv` managed via `setup.py` / `reset_env.bat` (rebuild = delete `.venv`, rerun `setup.py`)
* IDE: Spyder, run via `%runfile ... --wdir`
* Supporting libs: numpy-stl, trimesh, PyVista/VTK (system Python only, not in `.venv` — Cp-surface visualization work is deferred partly because of this), psutil

## 3. Current Implementation Status (as of late Aug 2026)

### Geometry (OpenVSP)

* SSAM-Gen5 reconstructed via STL reverse-engineering + validated against published SSAM parameters. Both a full-scale and a WTT (0.75 m) scale version exist and are used for different purposes (design sweeps vs. aero validation).
* `VSPRenew()` must be called inside loops, not once before them — otherwise MeshGeom accumulates across iterations and corrupts later results in the loop.

### Aerodynamics (VSPAero)

* Reynolds-number bug fixed in `vsp_setup.py`: hardcoded sea-level atmosphere replaced with a proper two-layer ISA function `isa_atmosphere()` (troposphere + stratosphere, Sutherland's law viscosity).
* Aero run loop restructured to a Mach × Altitude grid (3×3 = 9 runs), producing a `(3,3,11)` factorial array for Aviary's GASP tabular aero mechanism.
* Sweep-study debugging (active, as of the Aug 11–15 checkpoint — status may have moved since):
   * `WingSweep_aligned_S1` family: 4/7 points landed clean at last check (−10, −5, 0, +10); CL–α smooth/monotonic; sweep-decrease improves L/D at M0.6 as physically expected; +10° showed ~19% L/D loss, crossing a 3% threshold around +1.5–2°.
   * Persistent file-handle race condition: all sweep configs share fixed VSPAero output filenames (`aircraft.vsp3`, `.polar`, etc.); rapid subprocess succession under Windows causes intermittent "ERROR 7: Could not open History/Polar/Load file". Mitigated (not fixed) with `time.sleep(2–5)` before subprocess launch + retry-once-on-`aero_failed`, plus a Windows Defender exclusion on the project folder. Architectural fix identified but not yet implemented: give each sweep config unique output filenames instead of shared ones.
   * `+5.0` config showed genuine solver non-convergence (`aero_diverged`), reproduced 3 separate times — not the race condition. `wake_iters` raised from 3→6 with an `aero_diverged` guard added so bad runs are flagged rather than silently trusted.
   * `WingSweep_aligned_S1 +5.0` also separately flagged (per longer-running memory) as having a confirmed wing/HT near-contact geometry defect (~1 mm minimum distance) — should be excluded as a documented outlier. `-15.0`/`-10.0` flagged elsewhere for VLM divergence at large sweep angles. These two issue-lists don't perfectly agree on which exact deltas are bad — treat as "multiple failure modes have been seen across sweep angles; do a systematic proximity/convergence check across all deltas before trusting any one family end-to-end" rather than a single settled list.
   * Alpha window widened from (−2° to 10°) to (−8° to 14°) with 12 points after the narrower window pinned `alpha_at_max_LD` fits to the domain edge.
* Stability analysis (static margin) — added later, substantial thread:
   * `SM = -dCm/dCL` implemented as `compute_static_margin(aero_csv, cl_target, cref, window_pts=5)` — a windowed local-slope fit around a target CL (not a whole-range fit, since VSPAero and WTT curves diverge into nonlinearity past ~14–16° α and a global fit blends the linear and bent regions into a meaningless number). Returns `(SM, R²)` so weak fits get flagged, same pattern as `used_max_LD_fallback`.
   * Confirmed equivalent to the textbook definition: `SM = (Xnp − Xcg)/cref = −(Xcg − Xnp)/cref = −dCm/dCL`.
   * `CMytot` needs to be added to `run_vspaero_aero()`'s CSV export (parsed-column dict + CSV header/row — currently hardcoded to `["Alpha","CL","CDtot","CDi","CDo","L/D"]`).
   * `run_vspaero_aero()` needs a new optional `x_cg` parameter to explicitly set VSPAero's `Xcg` Parm before each run — currently no CG/moment-reference control exists in the function; it relies on whatever was last saved in the `.vsp3` file. This was still open as of the last detailed checkpoint.
   * Scale-mismatch trap (worth remembering): the WTT-scale CG value (`X_cg ≈ 0.4385`, derived as "paper's −0.4385 m, sign-flipped into VSPAero's +X-aft convention") is only valid for the WTT-scale geometry's coordinate system. Using the same absolute value on the full-scale sweep geometry (`..._scaled_by_19_simplified.vsp3`) silently measures CG at the wrong physical fraction of the airframe and can flip the static-margin sign from an input error, not a real finding. The scaled value used there is `8.3315` (scaled + sign-flipped), not `0.4385`. General rule adopted: re-derive CG from actual measured body length per geometry, don't propagate a scalar multiply/divide across geometries that may not be uniformly scaled (confirmed via a real case where Cref-derived and Sref-derived scale factors disagreed — 1.576× vs 1.410× — revealing the "nozzle_mod" geometry wasn't a uniform scale-up of the WTT baseline).
   * Once the CG was correctly set for the WTT-scale baseline, VSPAero reproduced the expected RSS (relaxed static stability) signature — Cm slope flips positive with α, matching WTT expectations — closing that validation checkpoint.
   * `perf_analysis.py` was slated for rename to `perf_stab_analysis.py` and refactor to read (not recompute) per-config values from manifests, once the above is wired in.
   * Important open flag: all current sweep-manifest data has `CMytot` computed about an artifact/placeholder CG (`0.54187`), not the real one — needs a rerun once `x_cg` wiring lands.

### RCS (OpenRCS / Physical Optics)

* Runs in minutes — this is the explicit justification (alongside the supervisor's stated preference) for not building a DoE/surrogate layer around it.
* PO monostatic on PEC systematically overestimates RCS vs. a real F-35 (~8 dB gap observed) — physically expected because PO single-bounce excludes RAM absorption and edge-diffraction cancellation. Accepted as reasonable at conceptual-design fidelity.
* TE-z and TM-z co-pol RCS are mathematically identical under the PO monostatic approximation for PEC targets (Barile 1984 duality theorem); cross-pol is always at solver floor. `pol="TE-z"` is the canonical default — dual-pol runs were tried and confirmed to add no information.
* Mesh density: 1.5λ panel-size rule (at 12 GHz, λ = 2.5 cm → min panel edge 3.75 cm); practical convergence range is λ/4–λ/6. A flat plate's RCS is theoretically mesh-independent under analytical PO — mesh-dependence on a flat-plate test case indicates a bug, not physics.
* OpenRCS kept as a git submodule (`OpenRCS/open-rcs/`) — never delete its inner `.git`; it's listed in the root `.gitignore`. `automatic_compare.py` inside it is the only MATLAB-dependent file and isn't used by the pipeline.

### Aviary (mission analysis)

* Scope debate happened explicitly (Aug 11 checkpoint): the ADIC contracted deliverable only requires "mission profile comparison against the baseline (same weight class)" — no MDAO, gradient optimization, or trajectory coupling. Initial read: Aviary integration is not required to satisfy the deliverable, and VSPAero polars + Breguet-style performance equations already cover it as a checkbox, not a research gap. Considered doing it anyway partly for its PhD-application value (Georgia Tech/MDO exposure) and as a stretch/plus point.
* It was subsequently implemented anyway (per later sessions/memory) — GASP aerodynamics method (`tabular_cruise` + `solve_alpha`, matching the VSPAero polar's altitude/Mach/AoA → CL/CD array structure via `reshape_to_grid()`), FLOPS mass method with F-16C published specs overridden via `set_val()`, F100-PW-229 EngineDeck from simplified static ratings, mission profile climb → cruise (M0.6/35,000 ft) → descent, `target_range = 400 nmi` as a one-way combat-radius approximation.
* Architectural rule: `external_aero_builder.py`'s `build_pre_mission()` must `return None` — GASP's `tabular_cruise` reads `Aircraft.Design.LIFT_POLAR`/`DRAG_POLAR` directly from `aviary_inputs` as fixed parameters (set via `prob.aviary_inputs.set_val()` in `run_aviary.py`). Adding an `om.Group()` component here that also promotes those names causes a shape-mismatch error (`(99,)` vs `(3,3,11)`) via a promotion conflict — this exact bug recurred because a fix wasn't actually saved/reloaded; always verify via `external_aero_builder.__file__` and a full Spyder kernel restart (not just a rerun) when a "fixed" bug reappears identically.
* Usage pattern: `run_model()` only — no `add_driver()`/`add_design_variables()`/`add_objective()`; this is analysis, not optimization.
* The F-16C/Gen-5-generation mismatch mainly affects absolute magnitude, not relative baseline-vs-sweep comparisons, which is the project's actual use case — treated as acceptable.
* Turn/maneuver performance is explicitly outside Aviary's scope in this project.

### Known dependency landmine (worth remembering for env resets)

* `requirements.txt` had both `stl==0.0.3` and `numpy-stl==3.1.2`. Both packages install into a site-packages folder literally named `stl/`, so whichever installs second silently overwrites the other — and pip's resolver doesn't guarantee requirements.txt line order, so this could pass or fail unpredictably across `reset_env.bat` runs depending on pip version/resolver state. Code only ever uses `from stl import mesh` (numpy-stl's namespace). Fix: delete the `stl==0.0.3` line before rerunning `reset_env.bat`, not after.

## 4. Planned Report Structure (as of Aug 27 checkpoint)

Full chapter-level ToC was drafted collaboratively and mapped explicitly against ADIC's numbered deliverables. Deliberately includes "honesty checkpoints" so nothing collapses under viva questioning — status is reported as-is (including gaps/deferrals), not polished over.

* **Front Matter** — title page, certificate, acknowledgments, abstract, ToC, figures/tables, nomenclature
* **Ch.1 Introduction** — background/motivation, ADIC problem statement (quoting the PDD scope paragraph), objectives (mapped to PDD "Desired Outcome"), report organization
* **Ch.2 Literature Review (Deliverable 1)** — 2.1 RCS/EM fundamentals (RRE, dBsm, PO/GO/GTD-PTD, 3–5 pp); 2.2 historical evolution of LO aircraft design (an A–G case structure covering F-117, B-2, F-22, F-35, Soviet MFI/MiG-1.44, Su-57, J-20); 2.3 threat detection (radar + EO/IR) — open gap, EO/IR half still unwritten; 2.4 shaping-technology survey; 2.5 RCS prediction/evaluation-method landscape; 2.6 aero–stealth trade-off literature (Hines, Taj et al., Liangliang et al. — novelty positioning); 2.7 optimization/surrogate/ML approaches; 2.8 research gaps/positioning
* **Ch.3 Methodology and Pipeline Architecture** — framework philosophy (self-contained, config-driven, single-entry-point — stated explicitly as an ADIC deliverability constraint), tool selection rationale (why OpenVSP→OpenRCS→VSPAero→Aviary, why not POFACETS/MATLAB), pipeline data flow diagram, baseline case-study selection
* **Ch.4 Parametric Geometric Module (Deliverable 2a)** — SSAM-Gen5 reconstruction, parametric CAD structure, scale management (0.75 m WT model vs full-scale), geometry validation
* **Ch.5 RCS Analysis Module (Deliverables 2b + 3)** — PO/OpenRCS pipeline bridge (`run_openrcs.py`), settings + justification, canonical-shape validation, full-scale extrapolation scaling law, explicit scope-boundary statement for cavity/inlet/weapon-bay (PO limitation, FEKO RL-GO flagged as future work)
* **Ch.6 Aerodynamic and Performance Module (Deliverable 3)** — VSPAero/Mach-sweep, subsonic vs. supersonic thin-surface switch at M≥1.0, stability analysis (SM, rolling-window regression, CG sign convention), performance module (Breguet, equilibrium cruise CL, `perf_assumptions.json`), 6.5 Aviary status — required to be an honest what's-done-vs-deferred statement, not a polished result, known limitations
* **Ch.7 Tools Validation Study** — its own chapter (not buried in 5/6) because it's one of the strongest, most complete pieces of work: canonical-shape RCS validation vs Woo et al./Touzopoulos et al., VSPAero vs. WTT CMcg validation, mesh/tessellation convergence, validated operating envelope summary
* **Ch.8 Design Trade-off and Sensitivity Study (Deliverable 4)** — DOE/sweep infrastructure (`sweep_driver.py`, `compare_family.py`), Stage-1 aero-only screening results (WingSweep/VTCant/WingTwist), 8.3 Stage-2 aero+RCS coupled — report actual completion status honestly, sensitivity thresholds/design guidelines, DNN surrogate stated as deferred future work (not hidden)
* **Ch.9 Discussion** — synthesis, comparison vs. Hines (2001)/Taj et al. (2023), limitations (PO scope, transonic gap, single-Mach DOE, partial coverage), deliverability assessment against ADIC's "operable by an uninvolved engineer" requirement
* **Ch.10 Conclusion and Future Work (Deliverable 5)** — objectives-vs-PDD summary, design guidelines + quantitative impact, recommendations to ADIC (FEKO RL-GO for cavities, DNN surrogate completion, full-loop Aviary integration), closing statement
* **References / Appendices** — A: config-schema + `main.py` usage guide (literal ADIC handoff doc); B: repo structure; C: supplementary plots; D: the IEEE survey paper as submitted, cross-referenced

## 5. Open Items

Carry into next session — status current as of the most detailed checkpoint; re-verify against actual code before assuming any are still unresolved.

* [ ] Confirm full-scale sweep geometry's density setup on Main_Wing/HT/VT — determines whether the earlier per-config CG table was meaningful or a zero-mass artifact.
* [ ] Implement `Xcg`-setting capability in `run_vspaero_aero()` (exact API — `vsp.GetXcgParmID()` vs. container-based `FindParm`/`FindContainer` — not fully verified against the installed OpenVSP version at last check).
* [ ] Add `CMytot` to `vsp_setup.py`'s CSV export.
* [ ] Finish `compute_static_margin()` wiring (windowed local-slope + R² flag — function itself was drafted; integration/rerun with correct per-geometry CG was still pending).
* [ ] Rename `perf_analysis.py` → `perf_stab_analysis.py`; refactor to read, not recompute, per-config values from manifests.
* [ ] Rerun sweep families once the `Xcg` fix + `CMytot` export are in place — existing sweep manifest data has `CMytot` computed about a placeholder CG, not the real one.
* [ ] Resolve `alpha_at_max_LD` boundary sensitivity — check `compare_family.py` too.
* [ ] Confirm sweep geometry's coordinate origin matches the WTT model's nose-tip convention before reusing the same CG scaling/sign-flip logic.
* [ ] Replace the TSFC placeholder (currently derived from a course-code `ct` value) with a properly cited generic afterburning-turbofan number.
* [ ] Architectural fix for the sweep file-handle race: unique per-config output filenames instead of shared `aircraft.*` names (currently only mitigated with sleep/retry).
* [ ] Get `-15.0`, `+15.0` (race) and `+5.0` (genuine divergence) sweep points to actually complete cleanly — do a systematic proximity + convergence check across all deltas, not just the ones that have already failed once.
* [ ] Write the EO/IR half of literature-review §2.3 (explicit gap, not yet started).
* [ ] Stage 2 (aero+RCS coupled sweep) — flip `run_rcs=True`, narrower delta list per family; not started as of last detailed checkpoint.
* [ ] TE-sweep (`Sweep_Location`) family — mechanics discussed, not built.
* [ ] Deferred/optional, not committed: turn-rate/Ps delta across sweep family; non-zero placeholder density on wing/tails to let CG move a small bounded amount for sensitivity.
* [ ] Validate aero results (CL-α, drag polar) against SSAM Gen-5 fully — flagged as priority before revisiting Cp-surface visualization.
* [ ] Spanload plots — queued after aero validation.
* [ ] 3D Cp-surface visualization — deferred; needs PyVista/VTK inside `.venv` (currently only in system Python).
* [ ] Systematic proximity check across all sweep-family deltas (not just the known-failing config) to catch geometry defects like the WingSweep +5.0 wing/HT near-contact case consistently.

## 6. Key Technical Learnings & Principles

* **PO polarization independence**: TE-z/TM-z co-pol RCS identical under PO monostatic approximation for PEC (Barile 1984). Cross-pol at solver floor. Use `pol="TE-z"` only.
* **Mesh density for PO**: 1.5λ panel rule; λ/4–λ/6 practical convergence. Mesh-dependence on a flat plate = bug, not physics (analytical PO is mesh-independent there).
* **OpenRCS as PO cross-check**: ~8 dB gap vs. real F-35 RCS is physically justified (no RAM, no edge-diffraction cancellation in single-bounce PO/PEC) — acceptable at conceptual-design fidelity.
* **VSPAero/Aviary boundary**: VLM can't capture nonlinear LE-vortex physics (strakes, high-α separated flow); turn/maneuver performance is entirely outside Aviary's scope here; VSPAero Mach ceiling ~0.65–0.7.
* **Aviary usage pattern**: `run_model()` only, no driver/design-vars/objective. Generation mismatch (F-16C vs Gen-5 baseline) mainly skews absolute magnitude, not relative comparisons — acceptable for this project's actual use case.
* **OpenVSP Python API quirks**: analysis inputs need single-element lists (`[value]`); `SetParmVal()` never raises on failure (silent no-op on group-string mismatch) — always verify via `GetParmVal`/`GetGeomParmIDs` name-keyed dicts instead of trusting group strings; `VSPRenew()` must be called inside loops, not once outside them.
* **OneDrive incompatibility**: stay on `D:\` — OneDrive's filter driver blocks `vspaero.exe` output-file creation.
* **Surrogate methods rejected**: OpenRCS runs in minutes; surrogate overhead only pays off for expensive solvers. Matches supervisor's explicit stated preference for direct parametric sweeps.
* **OpenRCS as submodule**: never delete its inner `.git`; keep it gitignored at the parent-repo level; `automatic_compare.py` is the one MATLAB-dependent file, unused by the pipeline.
* **CG/static-margin scale trap**: never propagate a scalar CG value across geometries at different scales/proportions without re-deriving from actual measured body length — Cref-derived and Sref-derived scale factors can disagree, revealing non-uniform scaling.
* **Dependency landmine**: don't let `stl` and `numpy-stl` coexist in `requirements.txt` — both claim the `stl/` site-packages namespace; keep only `numpy-stl`.
* **Aviary `build_pre_mission()` rule**: must `return None` — GASP's `tabular_cruise` reads the polar arrays directly from `aviary_inputs`; adding a component here that also promotes `LIFT_POLAR`/`DRAG_POLAR` causes a promotion/shape conflict. If a "fixed" version of this bug reappears identically, suspect a stale/unsaved file or duplicate module path before re-debugging the logic — verify via `module.__file__` and a full kernel restart.

## 7. Working Preferences

For whoever/whatever is reading this — Claude Code included.

* No sidebar artifacts for code. Give exact find-and-replace pairs with explicit file paths, inline in chat/output. No full-file rewrites unless the file is new/short. This is a firm, repeatedly-stated preference from the person, carried over into this document as a standing instruction for how to hand back code changes on this project.
* Debugging style is empirical/iterative: isolate variables, cross-reference GUI observations with API behavior, verify fixes against actually-running code before calling something resolved.
* Communication is informal and fast-paced; expects intent to be inferred rather than over-asking for clarification; pushes back directly on incorrect diagnoses or stale references.
* Formal deliverables (report, presentations) are expected despite the informal chat style — prefers native visual formats (flowcharts, annotated diagrams, icon grids) over bullet-heavy slides, but wants technical rigor and honest status reporting, especially anything that could be challenged in a viva.
* Feasibility-checks before committing implementation effort; defers non-critical features (e.g. Cp-surface viz, spanload plots) until validated results exist.

## 8. Notes on This Document's Provenance

* Built by reading both full conversation exports (`claude1_conversations.json`, `claude2_conversations.json` — 132 + 61 conversations) plus prior cross-session memory, and cross-referencing the two.
* Where the two sources disagreed slightly on current status (e.g. exactly which sweep-angle deltas were failing and why, at different points in Aug 2026), this document says so explicitly rather than picking one silently — re-verify current state against the actual repo/code before relying on either.
* Non-technical threads (PhD-application discussions, coursework/exam prep, unrelated personal projects like a water-chiller installation, job-application help) were deliberately excluded — they're in the raw exports if ever needed, but aren't part of the FYP technical state.
* If this file starts drifting from reality, the fix is to keep it updated directly (it's meant to be a living doc in the repo), not to regenerate it from a fresh full-export read each time.
