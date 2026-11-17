# weight_loss_alert.py  -  "slow weight loss" (drying / spoilage warning) for Shelf
#
# Idea: remember the weight an item had when it was placed (the BASELINE).
# Every time the shelf posts a new weight, compare it with the baseline.
# If the item has lost LOSS_G grams or more within WINDOW_DAYS days -> one alert.
#
# What does NOT count as slow loss:
#   * a single drop of CONSUME_STEP_G or more      -> someone ate / took some (already "consumption")
#   * a single rise of NEW_ITEM_STEP_G or more     -> a new item was placed
#   * the item name changed                        -> a different item
#   * weight is 0                                  -> shelf is empty, baseline cleared
# After WINDOW_DAYS the baseline restarts (a new week starts from the current weight).
import os
import sqlite3
import time

from fastapi import APIRouter

# ---------------- EDIT THESE ----------------
LOSS_G = 10.0            # alert when this many grams are lost ...
WINDOW_DAYS = 7.0        # ... within this many days
CONSUME_STEP_G = 10.0    # one drop this big (or bigger) = consumption, not drying
NEW_ITEM_STEP_G = 30.0   # one rise this big (or bigger) = new item placed
# --------------------------------------------

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grocery.db")
router = APIRouter()


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute(
        "CREATE TABLE IF NOT EXISTS weight_baseline ("
        " quadrant INTEGER PRIMARY KEY, item_name TEXT, start_g REAL,"
        " start_ts REAL, last_g REAL, alerted INTEGER DEFAULT 0)"
    )
    return c


def _reset(c, quadrant, item_name, w, now):
    c.execute(
        "INSERT OR REPLACE INTO weight_baseline (quadrant, item_name, start_g, start_ts, last_g, alerted)"
        " VALUES (?, ?, ?, ?, ?, 0)",
        (quadrant, item_name, w, now, w),
    )


def check(quadrant, item_name, weight_g, now=None):
    # Call this after every weight post.  Returns a dict when an alert should be sent, else None.
    now = time.time() if now is None else now
    w = float(weight_g)
    q = int(quadrant)
    name = item_name or ""
    c = _conn()
    try:
        if w <= 0:                                  # empty shelf: forget the baseline
            c.execute("DELETE FROM weight_baseline WHERE quadrant = ?", (q,))
            c.commit()
            return None
        row = c.execute(
            "SELECT item_name, start_g, start_ts, last_g, alerted FROM weight_baseline WHERE quadrant = ?", (q,)
        ).fetchone()
        if row is None:
            _reset(c, q, name, w, now)
            c.commit()
            return None
        name0, start_g, start_ts, last_g, alerted = row
        changed_item = bool(name and name0 and name != name0)
        if changed_item or (w - last_g) >= NEW_ITEM_STEP_G or (last_g - w) >= CONSUME_STEP_G:
            _reset(c, q, name, w, now)              # new item, or eaten/removed some: start over
            c.commit()
            return None
        days = (now - start_ts) / 86400.0
        if days > WINDOW_DAYS:                      # the window is over: new week from here
            _reset(c, q, name, w, now)
            c.commit()
            return None
        c.execute("UPDATE weight_baseline SET last_g = ? WHERE quadrant = ?", (w, q))
        loss = start_g - w
        if loss >= LOSS_G and not alerted:
            c.execute("UPDATE weight_baseline SET alerted = 1 WHERE quadrant = ?", (q,))
            c.commit()
            pct = (loss / start_g * 100.0) if start_g > 0 else 0.0
            label = name or "Item"
            return {
                "loss_g": round(loss, 1),
                "loss_pct": round(pct, 1),
                "days": round(days, 1),
                "start_weight_g": round(start_g, 1),
                "weight_g": round(w, 1),
                "message": (
                    f"{label} in Quadrant {q} lost {loss:.0f} g ({pct:.1f}%) in {days:.1f} days "
                    f"({start_g:.0f} g -> {w:.0f} g). It may be drying out - use it soon."
                ),
            }
        c.commit()
        return None
    finally:
        c.close()


@router.get("/api/v1/weight-baseline")
def weight_baseline():
    # Look at what the alert logic is remembering (for testing).
    c = _conn()
    try:
        rows = c.execute("SELECT quadrant, item_name, start_g, start_ts, last_g, alerted FROM weight_baseline").fetchall()
    finally:
        c.close()
    now = time.time()
    return [
        {"quadrant": r[0], "item_name": r[1], "start_g": r[2], "days_since_start": round((now - r[3]) / 86400.0, 2),
         "last_g": r[4], "alerted": bool(r[5])}
        for r in rows
    ]


@router.post("/api/v1/debug/backdate-baseline")
def backdate_baseline(quadrant: int, days: float = 6.0):
    # DEMO ONLY (simulated time): pretend the item was placed `days` days ago, so you can show a
    # 7-day alert without waiting a week.  Say "simulated time" if you show this.
    c = _conn()
    try:
        c.execute("UPDATE weight_baseline SET start_ts = ? WHERE quadrant = ?", (time.time() - days * 86400.0, quadrant))
        c.commit()
        n = c.total_changes
    finally:
        c.close()
    return {"quadrant": quadrant, "backdated_days": days, "rows_changed": n, "note": "simulated time - demo only"}
