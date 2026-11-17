"""
depletion_mr.py  -  multiple-regression depletion forecast for Shelf.

Drop this file next to database.py (E:\\SHELF\\backend\\depletion_mr.py). Needs only numpy (already installed with ultralytics).

    from depletion_mr import forecast_days_left
    res = forecast_days_left(rows)          # rows = [(timestamp, weight_g), ...]  oldest -> newest
    res -> {"days_left": 3.4, "method": "multiple_regression", "r2": 0.97, "slope_g_per_day": -62.1, "n": 24}

Model (multiple linear regression, fitted with ridge-stabilised least squares):

    weight(t) = b0 + b1*t_days + b2*sin(2*pi*hour/24) + b3*cos(2*pi*hour/24) + b4*is_weekend

  - t_days        : time since the first log in this "run"           -> the overall consumption trend
  - sin/cos(hour) : time of day (people eat at certain hours)        -> captures the daily rhythm
  - is_weekend    : weekend vs weekday                               -> captures weekly habit

The forecast walks forward hour by hour with the fitted model until the predicted weight reaches 0 g,
so the daily rhythm is respected (a straight line cannot do that).

Safety rules (the old linear method stays as the fallback):
  * only data since the last restock (a rise of >= RESTOCK_G) is used
  * fewer than MIN_POINTS_MR logs, or < MIN_SPAN_H hours of data  -> plain linear regression
  * model that is not clearly downward, or fits worse than the line  -> plain linear regression
  * nothing downward at all -> days_left = None
"""
from datetime import datetime, timedelta, timezone
import math
import numpy as np

RESTOCK_G = 30.0        # a rise of this much = item was restocked / replaced -> start a new run
MIN_POINTS_MR = 10      # below this, multiple regression would just overfit
MIN_SPAN_H = 24.0       # need at least a day of history to learn a daily pattern
RIDGE = 1e-3            # tiny penalty on the non-trend terms so few points cannot blow them up
MAX_DAYS = 99.0         # same cap the app already uses ("99-day forecasts")
MIN_GAP_MIN = 10.0      # the ESP32 posts a heartbeat every 30 s: keep one log per 10 min so n and span mean something


def _to_dt(ts):
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    if isinstance(ts, datetime):
        return ts
    s = str(ts).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def _last_run(rows):
    """keep only the data after the most recent restock"""
    cut = 0
    for i in range(1, len(rows)):
        if rows[i][1] - rows[i - 1][1] >= RESTOCK_G:
            cut = i
    return rows[cut:]


def _thin(rows):
    """keep a log only if it is >= MIN_GAP_MIN after the previous kept one (always keep the newest)"""
    if len(rows) < 3:
        return rows
    kept = [rows[0]]
    last_dt = _to_dt(rows[0][0])
    for r in rows[1:-1]:
        d = _to_dt(r[0])
        if (d - last_dt).total_seconds() >= MIN_GAP_MIN * 60:
            kept.append(r); last_dt = d
    kept.append(rows[-1])
    return kept


def _features(dts, t0):
    t_days = np.array([(d - t0).total_seconds() / 86400.0 for d in dts])
    hours = np.array([d.hour + d.minute / 60.0 for d in dts])
    wk = np.array([1.0 if d.weekday() >= 5 else 0.0 for d in dts])
    X = np.column_stack([
        np.ones_like(t_days), t_days,
        np.sin(2 * math.pi * hours / 24.0), np.cos(2 * math.pi * hours / 24.0), wk,
    ])
    return X, t_days


def _fit(X, y, ridge_cols):
    P = np.zeros(X.shape[1])
    P[ridge_cols] = RIDGE
    A = X.T @ X + np.diag(P)
    return np.linalg.solve(A, X.T @ y)


def _r2(y, yhat):
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0


def _linear(t_days, y):
    """the old method: weight = a + b*t.  returns (a, b, r2)"""
    X = np.column_stack([np.ones_like(t_days), t_days])
    coef = np.linalg.lstsq(X, y, rcond=None)[0]
    return coef[0], coef[1], _r2(y, X @ coef)


def forecast_days_left(rows, now=None):
    """rows: [(timestamp, weight_g), ...] oldest -> newest. Returns a dict (see module doc)."""
    out = {"days_left": None, "method": "none", "r2": None, "slope_g_per_day": None, "n": 0}
    rows = [(r[0], float(r[1])) for r in rows if r[1] is not None]
    rows = _last_run(rows)
    rows = _thin(rows)
    out["n"] = len(rows)
    if len(rows) < 2:
        return out

    dts = [_to_dt(r[0]) for r in rows]
    y = np.array([r[1] for r in rows])
    t0 = dts[0]
    X, t_days = _features(dts, t0)
    span_h = float(t_days[-1] - t_days[0]) * 24.0
    cur = float(y[-1])
    if cur <= 0:
        return {**out, "days_left": 0.0, "method": "empty"}

    a, b, r2_lin = _linear(t_days, y)
    out["slope_g_per_day"] = float(round(float(b), 2))

    def linear_answer(method="linear_fallback"):
        if b >= -1e-6:
            return {**out, "method": method, "r2": float(round(r2_lin, 3)), "days_left": None}
        return {**out, "method": method, "r2": float(round(r2_lin, 3)),
                "days_left": float(round(min(cur / -b, MAX_DAYS), 1))}

    if len(rows) < MIN_POINTS_MR or span_h < MIN_SPAN_H:
        return linear_answer()

    coef = _fit(X, y, ridge_cols=[2, 3, 4])
    r2_mr = _r2(y, X @ coef)
    slope = float(coef[1])
    out["slope_g_per_day"] = float(round(slope, 2))
    if slope >= -1e-6 or r2_mr + 0.02 < r2_lin:
        return linear_answer()

    # walk forward hour by hour from the last log until the model reaches 0 g
    base = dts[-1]
    last_t = float(t_days[-1])
    anchor = cur - float(np.array([1, last_t,
                                   math.sin(2 * math.pi * (base.hour + base.minute / 60) / 24),
                                   math.cos(2 * math.pi * (base.hour + base.minute / 60) / 24),
                                   1.0 if base.weekday() >= 5 else 0.0]) @ coef)   # align model to the real last weight
    for h in range(1, int(MAX_DAYS * 24) + 1):
        d = base + timedelta(hours=h)
        t = last_t + h / 24.0
        hr = d.hour + d.minute / 60.0
        xv = np.array([1, t, math.sin(2 * math.pi * hr / 24), math.cos(2 * math.pi * hr / 24),
                       1.0 if d.weekday() >= 5 else 0.0])
        if float(xv @ coef) + anchor <= 0:
            return {**out, "method": "multiple_regression", "r2": float(round(r2_mr, 3)),
                    "days_left": float(round(h / 24.0, 1))}
    return {**out, "method": "multiple_regression", "r2": float(round(r2_mr, 3)), "days_left": MAX_DAYS}
