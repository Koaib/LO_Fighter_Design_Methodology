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

_STYLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lo_fighter_paper.mplstyle")
plt.style.use(_STYLE_PATH)


def robust_lowess(x, y, x_eval=None, frac=0.35, iters=3):
    """Robust LOWESS (Cleveland 1979) trendline for a noisy delta-sweep
    (shaping-parameter sensitivity studies here are dominated by run-to-
    run meshing/discretization noise on top of a real underlying trend).

    Unlike a plain moving average or Savitzky-Golay filter, this
    DOWNWEIGHTS outliers instead of requiring them to be deleted from
    the raw data first: after each local weighted-linear-regression fit,
    points with large residuals get less influence on the next fit
    (bisquare reweighting), so a single severe spike (e.g. a specular
    RCS flash at one delta) pulls the trendline only slightly, while
    still being visible in the raw data plotted underneath it.

    frac: fraction of the points used in each local neighborhood -
    larger = smoother/less sensitive to individual points. iters:
    robustness (re-weighting) passes; 0 disables outlier downweighting.
    x_eval: where to evaluate the trend (default: 200-point grid across
    the data's own range, for a visually smooth curve regardless of how
    sparse the raw delta grid is).

    Returns (x_eval, y_smooth). Falls back to a flat line at the mean
    if fewer than 3 finite points are given - nothing to smooth."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    order = np.argsort(x)
    x, y = x[order], y[order]
    n = len(x)
    if x_eval is None:
        x_eval = np.linspace(x.min(), x.max(), 200) if n else np.array([])
    else:
        x_eval = np.asarray(x_eval, dtype=float)
    if n < 3:
        return x_eval, np.full_like(x_eval, y.mean() if n else np.nan)

    k = max(2, int(np.ceil(frac * n)))
    robust_w = np.ones(n)

    for _ in range(max(1, iters + 1)):
        y_smooth = np.empty(len(x_eval))
        for i, xe in enumerate(x_eval):
            dist = np.abs(x - xe)
            idx = np.argsort(dist)[:k]
            d = dist[idx]
            h = d.max() if d.max() > 0 else 1.0
            tricube = (1 - np.clip(d / h, 0, 1) ** 3) ** 3
            w = tricube * robust_w[idx]
            xw, yw = x[idx], y[idx]
            X = np.column_stack([np.ones(k), xw - xe])
            W = np.diag(w)
            try:
                beta = np.linalg.lstsq(W @ X, W @ yw, rcond=None)[0]
                y_smooth[i] = beta[0]
            except np.linalg.LinAlgError:
                y_smooth[i] = np.average(yw, weights=w)

        # Residuals at the ORIGINAL x points feed the next robustness
        # pass - interpolated from the eval grid rather than refitting
        # at each x directly, since x_eval already densely covers it.
        fit_at_x = np.interp(x, x_eval, y_smooth)
        resid = y - fit_at_x
        s = np.median(np.abs(resid)) or 1e-12
        u = np.clip(resid / (6 * s), -1, 1)
        robust_w = (1 - u ** 2) ** 2

    return x_eval, y_smooth
