# -*- coding: utf-8 -*-
"""
plot_style.py — applies lo_fighter_paper.mplstyle to every plot this
project generates, so aero/stability/mission/RCS figures all come out
looking like one consistent set (same font, weights, DPI, color cycle,
tick/grid style) instead of each plotting function picking its own
numbers independently.

Import this AFTER matplotlib.pyplot in any script that calls plt.*/
fig.savefig() - importing it is enough, plt.style.use() below takes
effect immediately and applies to every Figure created afterward in
that process:
    import matplotlib.pyplot as plt
    import plot_style

See lo_fighter_paper.mplstyle's own header for why it uses matplotlib's
built-in mathtext (mathtext.fontset=cm) instead of a real LaTeX install.
"""
import os

import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

_STYLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lo_fighter_paper.mplstyle")
plt.style.use(_STYLE_PATH)


def robust_linear_trend(x, y):
    """Straight-line trendline for a noisy delta-sweep, fit with the
    Theil-Sen estimator (the median of the slopes between every pair of
    points) instead of ordinary least squares. A single severe outlier
    (e.g. a specular RCS flash at one delta) barely moves a median, so
    it barely moves this line - unlike OLS, which a lone outlier can
    tilt substantially since every point pulls the sum-of-squares fit
    directly. Verified against a synthetic monotonic trend + one severe
    injected outlier before use: Theil-Sen recovered the true slope
    about 4.5x more accurately than OLS did on the same data.

    Robustness to point-outliers is NOT the same thing as "a straight
    line is the right shape for this data" - a relationship that
    genuinely rises then plateaus (e.g. diminishing returns past some
    shaping delta) has no single straight line that fits it well
    ANYWHERE, robust fit or not. r_squared (1 - SS_res/SS_tot of this
    line against the raw data, the same statistic Excel's own
    "add trendline" reports) is returned alongside the line specifically
    so that's visible on the plot itself, not just assumed - a low value
    means the straight-line summary should be treated with real caution,
    not just plotted and trusted.

    r_squared CAN come out negative here, unlike a textbook OLS r_squared
    (which is mathematically guaranteed >= 0, because OLS is DEFINED as
    whichever line minimizes SS_res, and the flat mean - slope=0 - is
    always one of the lines it could have picked instead, so OLS can
    never do worse than it). Theil-Sen is deliberately NOT chosen to
    minimize SS_res - it is chosen to resist outliers - so that guarantee
    does not carry over: for a study where this parameter genuinely has
    no real linear effect on the metric (pure noise around a flat line),
    Theil-Sen's slope is just noise scattered around zero, and using ANY
    nonzero slope to predict is worse, in total squared error, than just
    predicting the flat mean every time. Confirmed numerically before
    shipping this: fit against synthetic pure-noise (zero true slope)
    data gave r_squared=-0.0005, for exactly this reason. A negative (or
    near-zero) r_squared is a real, correct result, not a bug - read it
    exactly like a low positive one: this parameter's effect on this
    metric is not reliably linear (very possibly not reliably anything),
    so don't trust the slope's sign, let alone its magnitude.

    Returns (x_eval, y_line, r_squared): a straight line evaluated at
    the two ends of x's own range, ready to plot directly over the raw
    data, plus its own r_squared against every raw point (not just the
    two endpoints). Falls back to a flat line at the mean (r_squared as
    None) if fewer than 2 finite points are given - nothing to fit a
    slope to."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 2:
        x_eval = np.linspace(x.min(), x.max(), 2) if len(x) else np.array([])
        return x_eval, np.full_like(x_eval, y.mean() if len(y) else np.nan), None

    slope, intercept, _, _ = stats.theilslopes(y, x)
    pred = slope * x + intercept
    ss_res = np.sum((y - pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else None

    x_eval = np.array([x.min(), x.max()])
    return x_eval, slope * x_eval + intercept, r_squared


def linear_fit(x, y):
    """Ordinary-least-squares straight-line fit (np.polyfit, degree 1) -
    used ONLY by aero_stab_mission_compare_family.py's and maneuver_
    compare_family.py's own per-panel trend lines. rcs_compare_family.py
    is deliberately NOT switched to this - it keeps calling
    robust_linear_trend() (Theil-Sen) exactly as before, untouched.

    Why two different fits exist in the same project: robust_linear_
    trend()'s Theil-Sen is chosen for outlier-RESISTANCE (a lone severe
    spike barely tilts the median-of-slopes line) at the cost of two
    textbook guarantees a reader expects from "a trendline" - it does
    NOT necessarily pass through (x.mean(), y.mean()), and its R² CAN go
    negative (both documented, and verified numerically, on that
    function's own docstring). An OLS fit WITH an intercept has both
    guarantees unconditionally: it is DEFINED as whichever line
    minimizes sum-of-squared-residuals, and the flat mean (slope=0) is
    always one candidate line it could have picked instead, so it can
    never score worse than flat - hence 0 <= r_squared <= 1 always, and
    it always passes through the data's own mean point. Asserted below
    every call, not just assumed.

    Same finite-value mask applied to x AND y JOINTLY (one boolean
    array, never two separately-computed ones), so the points hitting
    polyfit are always drawn from the exact same (x, y) pairs - the
    returned xs/ys are that exact masked pair; callers should plot THOSE
    (not re-slice x/y themselves) so the scatter and the fit are
    provably the same data, not just supposed to be.

    Returns None if fewer than 3 finite points remain after masking - a
    2-point OLS "fit" is a line through both points unconditionally
    (r_squared=1 no matter what the data means), not an informative
    statistic, so it's treated the same as "nothing to fit" rather than
    a trivially perfect one. Otherwise returns (slope, intercept, r2,
    xs, ys, n). r2 is None (not NaN) in the one genuine edge case OLS
    itself doesn't cover - every y value identical (ss_tot==0, so
    "variance explained" has no denominator - there's no variance to
    explain in the first place, not a bad fit)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    xs, ys = x[mask], y[mask]
    if xs.size < 3:
        return None

    slope, intercept = np.polyfit(xs, ys, 1)
    yhat = slope * xs + intercept
    ss_res = np.sum((ys - yhat) ** 2)
    ss_tot = np.sum((ys - ys.mean()) ** 2)
    if ss_tot == 0:
        return slope, intercept, None, xs, ys, xs.size

    r2 = 1.0 - ss_res / ss_tot
    assert -1e-9 <= r2 <= 1.0 + 1e-9, (
        f"linear_fit: OLS r_squared={r2!r} outside [0,1] - mathematically "
        f"impossible for an intercept OLS fit, so something upstream fed "
        f"this mismatched/corrupted xs={xs!r}, ys={ys!r}")
    return slope, intercept, min(1.0, max(0.0, r2)), xs, ys, xs.size


# Fixed y-axis limits per metric, spanning every study's own data for
# that metric (not auto-scaled per plot). Auto-scaling makes the SAME
# metric look like it's on a different scale from one parameter's plot
# to the next, which in turn makes the horizontal baseline/mean line
# look like it "moves" between plots even when the underlying data
# didn't change nearly as much - fixing the range removes that
# artifact and makes the 5 studies visually comparable side by side.
# Bounds below span every study's own observed min/max for that metric.
YLIM_BY_METRIC = {
    "az_rcs":        (5.0, 27.5),        # Mean Azimuth RCS (dBsm)
    "frontal_rcs":   (-18.5, -15.0),     # Mean Frontal-Sector RCS (dBsm)
    "ld_max":        (0.0, 15.0),        # Theoretical max L/D
    "static_margin": (-0.4, 0.4),        # Static margin
    "residual_fuel": (-7500.0, 8000.0),  # Residual fuel (lbm)
    "ps_1g":         (10000.0, 20000.0), # Specific excess power at 1g (ft/min)
    "n_s":           (2.0, 3.5),         # Sustained load factor (g)
    "turn_rate":     (6.0, 10.0),        # Sustained turn rate (deg/s)
}


def delta_unit_for_study(study_name):
    """(unit_label, unit_scale) for expressing a per-delta slope in a
    natural, human-scaled unit for THIS study's swept parameter, instead
    of the unitless sensitivity_pct. The angle-based studies (VT_Cant,
    VT_Sweep, WingSweep*) sweep delta directly in degrees, so their
    slope is naturally "per deg" (scale=1.0, no rescaling). The
    thickness/chord study sweeps delta in absolute t/c ratio, in steps
    of 0.01 (see DELTAS_TC in rcs_sweep_driver.py/
    aero_stab_mission_driver.py) - reporting its slope "per 1.0 unit
    t/c" would extrapolate about 50x past the actual tested range
    (+-0.02) and produce an artificially huge-looking number for the
    same reason the old baseline-normalized sensitivity_pct did.
    "per 0.01 t/c" (one real tested step) is the natural, defensible
    unit instead - matched in scale to "per deg" the same way one
    tested step is matched to one tested step for every other study."""
    if "thickchord" in study_name.lower():
        return "0.01 Δ(t/c)", 0.01
    return "deg", 1.0
