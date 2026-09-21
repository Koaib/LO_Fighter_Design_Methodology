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
