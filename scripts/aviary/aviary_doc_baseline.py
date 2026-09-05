# -*- coding: utf-8 -*-
"""
Aviary documented-workflow baseline check ("opt2", stage A/B).

WHY THIS EXISTS
----------------
run_aviary.py (this project's real mission runner) hand-assembles an
OFF_DESIGN_MIN_FUEL problem every run: it sets Settings.PROBLEM_TYPE
directly, then calls add_driver()/add_design_variables()/add_objective()/
setup()/set_initial_guesses()/run_aviary_problem() itself. That sequence
was built by reading Aviary's internals (aviary_problem.py, aviary_group.py)
and matching them by hand - it has NEVER gone through Aviary's own actual
top-level, doctested API for this exact workflow:
AviaryProblem.run_off_design_mission() (see
aviary/docs/examples/off_design_missions.ipynb). Checking that method's
real source (core/aviary_problem.py, ~line 1407) shows the 0.9x
Mission.GROSS_MASS seed this project already uses (see run_aviary.py's own
seed_gross_mass_lbm comment) is NOT the missing piece - Aviary's own
run_off_design_mission() does exactly the same 0.9x seed internally. So
that part was already right.

What's still genuinely untested is whether this project's real aircraft
data (its VSPAero-derived aero table, its Mattingly & Heiser engine deck,
its wing-loading-scaled mass basis, its climb/cruise/descent phase
schedule) can converge through SLSQP AT ALL - under ANY Aviary problem
type, not just the hand-built OFF_DESIGN_MIN_FUEL one. This project has
never actually run a plain DESIGN/SIZING mission with this aircraft's real
numbers to find out.

This script only answers the more basic, prerequisite question, using
NOTHING from this project (no VSPAero aero tables, no custom engine deck,
no wing-loading mass basis) - purely Aviary's own bundled example
aircraft and default mission, run through Aviary's own documented API
calls verbatim:

  STAGE A - av.run_aviary() sizing Aviary's bundled "Advanced Single
  Aisle" aircraft on its own default energy-state mission
  (aviary/docs/examples/simple_mission.ipynb). Confirms SLSQP/OpenMDAO/
  Dymos converge AT ALL in this Python environment on a problem Aviary's
  own test suite is built around - rules an environment/install issue in
  or out before blaming anything problem-specific.

  STAGE B - AviaryProblem.run_off_design_mission(problem_type=
  'off_design_min_fuel', ...) on that same sized aircraft
  (aviary/docs/examples/off_design_missions.ipynb). Confirms the
  OFF_DESIGN_MIN_FUEL formulation itself - via Aviary's REAL method, not
  this project's hand-built reproduction of it - is not inherently broken
  in this environment.

If both stages pass (Aviary's own docs assert they do), the next step is
Stage C: run OUR aircraft's real aero/engine/mass/phase data through this
same real API (av.run_aviary() for a DESIGN mission, then
design_prob.run_off_design_mission() for the OFF_DESIGN_MIN_FUEL mission)
instead of run_aviary.py's current hand-assembled sequence. That is a
separate, bigger piece of work - not attempted in this script.

NOTE on prob.result: aviary_problem.py sets self.result = dm.run_problem(...)
whenever run_driver=True (the case here) - and this project's own earlier
diagnostic work already directly verified, against the actual installed
dymos/openmdao source on this machine, that this is a PLAIN BOOL (True =
failed), not an object with a .success attribute - despite
off_design_missions.ipynb's own example code checking `.result.success`.
Using `.success` here would crash with AttributeError before ever printing
a real answer, so this script checks truthiness directly instead
(`if design_prob.result:` means FAILED), matching run_aviary.py's own
already-verified convention.

Run standalone (no VSPAero run, no main.py, needed first):
    python scripts/aviary/aviary_doc_baseline.py
"""
import os

# Same reason run_aviary.py sets this: Aviary's own automatic post-run
# reporting hook crashes on a non-finite mass value from a stalled
# optimizer before we get control back to print our own diagnostics.
os.environ["OPENMDAO_REPORTS"] = "0"

import aviary.api as av

print("=" * 80)
print("STAGE A: Aviary's own documented simple-mission example (unmodified)")
print("=" * 80)

design_prob = av.run_aviary(
    aircraft_data='models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv',
    phase_info=av.default_energy_state_phase_info,
    verbosity=0,
)

if design_prob.result:
    raise RuntimeError(
        "STAGE A FAILED: Aviary's own stock sizing example did not converge "
        "in this environment. That points at an environment/install issue "
        "(scipy/OpenMDAO/Dymos version, the SLSQP build) rather than "
        "anything specific to this project's aircraft or mission - stop "
        "and report this exact failure before going any further."
    )

print("\nSTAGE A PASSED - design (sizing) mission converged.")
print(f"  Design Range      = {design_prob.get_val(av.Aircraft.Design.RANGE)[0]} nmi")
print(f"  Design Gross Mass = {design_prob.get_val(av.Aircraft.Design.GROSS_MASS)[0]} lbm")
print(f"  Fuel Mass         = {design_prob.get_val(av.Mission.TOTAL_FUEL_MASS)[0]} lbm")

print("\n" + "=" * 80)
print("STAGE B: off_design_missions.ipynb's real OFF_DESIGN_MIN_FUEL call")
print("=" * 80)

off_design_min_fuel_prob = design_prob.run_off_design_mission(
    problem_type='off_design_min_fuel',
    mission_range=1250,
    name='off_design_min_fuel_mission',
)

if off_design_min_fuel_prob.result:
    raise RuntimeError(
        "STAGE B FAILED: even Aviary's OWN documented OFF_DESIGN_MIN_FUEL "
        "workflow (run through its real run_off_design_mission() method, "
        "warm-started from a converged design mission) did not converge. "
        "That would mean OFF_DESIGN_MIN_FUEL itself is fragile in this "
        "environment/version - a more fundamental finding than expected, "
        "independent of anything this project's own script does."
    )

print("\nSTAGE B PASSED - warm-started OFF_DESIGN_MIN_FUEL mission converged.")
print(f"  Mission Range      = {off_design_min_fuel_prob.get_val(av.Mission.RANGE)[0]} nmi")
print(f"  Mission Gross Mass = {off_design_min_fuel_prob.get_val(av.Mission.GROSS_MASS)[0]} lbm")
print(f"  Fuel Mass          = {off_design_min_fuel_prob.get_val(av.Mission.TOTAL_FUEL_MASS)[0]} lbm")

print("\n" + "=" * 80)
print("BOTH STAGES PASSED on Aviary's own stock aircraft/mission via its real")
print("documented API. Next step (stage C, not run here): port THIS project's")
print("real aero table / engine deck / mass basis / phase schedule through")
print("this same av.run_aviary() -> design_prob.run_off_design_mission()")
print("pattern, instead of run_aviary.py's current hand-assembled")
print("OFF_DESIGN_MIN_FUEL problem, to find out whether OUR data converges")
print("under Aviary's real API before assuming the formulation itself is at fault.")
print("=" * 80)
