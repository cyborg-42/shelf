import sqlite3
from datetime import datetime, timedelta, timezone
import json
import numpy as np
from typing import List, Dict, Any, Optional

DATABASE_NAME = "grocery.db"

# ---- SHELF percent-of-peak status (patch_pct_status.py) ----
import os as _os, time as _time
PCT_CRITICAL = float(_os.environ.get("PCT_CRITICAL", "25"))   # below this % of peak -> Critical
PCT_LOW = float(_os.environ.get("PCT_LOW", "60"))             # below this % of peak -> Low Stock
_PCT_CONFIRM_S = float(_os.environ.get("DEPLETION_CONFIRM_S", "600"))
_EMPTY_SINCE = {}
_PEAK_COL_OK = False


def _pct_status(cursor, quadrant, weight_g):
    """Status from % of the quadrant's peak weight. Keeps peak_weight in the inventory table."""
    global _PEAK_COL_OK
    if not _PEAK_COL_OK:
        cols = [r[1] for r in cursor.execute("PRAGMA table_info(inventory)").fetchall()]
        if "peak_weight" not in cols:
            cursor.execute("ALTER TABLE inventory ADD COLUMN peak_weight REAL DEFAULT 0")
        _PEAK_COL_OK = True
    now = _time.time()
    if weight_g <= 0:
        _EMPTY_SINCE.setdefault(quadrant, now)
        return "Depleted"
    cursor.execute("SELECT peak_weight FROM inventory WHERE quadrant = ?", (quadrant,))
    row = cursor.fetchone()
    peak = float(row[0] or 0) if row else 0.0
    since = _EMPTY_SINCE.pop(quadrant, None)
    if since is not None and now - since >= _PCT_CONFIRM_S:
        peak = 0.0                      # it really was empty -> a fresh load starts a new peak
    if weight_g > peak:
        peak = float(weight_g)
    cursor.execute("UPDATE inventory SET peak_weight = ? WHERE quadrant = ?", (peak, quadrant))
    pct = 100.0 * weight_g / peak
    if pct < PCT_CRITICAL:
        return "Critical"
    if pct < PCT_LOW:
        return "Low Stock"
    return "Available"


def get_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    # Drop old incompatible schema if quadrant column is missing
    cursor.execute("PRAGMA table_info(inventory)")
    columns = [row[1] for row in cursor.fetchall()]
    if columns and "quadrant" not in columns:
        cursor.execute("DROP TABLE inventory")

    # Inventory state per 4-Quadrant tray
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quadrant INTEGER UNIQUE NOT NULL,
        item_name TEXT NOT NULL,
        weight_g REAL NOT NULL,
        max_capacity_g REAL DEFAULT 5000.0,
        status TEXT DEFAULT 'Available',
        last_updated TEXT
    )
    """)

    # Telemetry weight logs from HX711 38-Pin ESP32
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weight_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quadrant INTEGER NOT NULL,
        weight_g REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Camera scan logs from ESP32-CAM
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scan_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        confidence REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    _ensure_shelf_table(cursor)

    # Seed initial 4 Quadrants if empty
    cursor.execute("SELECT COUNT(*) FROM inventory")
    if cursor.fetchone()[0] == 0:
        seed_data = [
        (1, "Apple",       450.0, 5000.0, "Available", "Just now"),
        (2, "Orange",      620.0, 5000.0, "Available", "Just now"),
        (3, "Guava",       300.0, 5000.0, "Available", "Just now"),
        (4, "Pomegranate", 350.0, 5000.0, "Available", "Just now"),
    ]
        cursor.executemany(
            "INSERT INTO inventory (quadrant, item_name, weight_g, max_capacity_g, status, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
            seed_data
        )

    _seed_open_stays(cursor)
    conn.commit()
    conn.close()

def get_all_inventory():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory ORDER BY quadrant ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_quadrant_weight(quadrant: int, weight_g: float) -> dict:
    """
    Update the weight for a quadrant and return a dict with the computed
    status and item_name so the caller can broadcast meaningful alerts.

    Status thresholds:
        weight_g == 0          -> "Depleted"   (triggers push notification)
        0 < weight_g < 100     -> "Critical"
        100 <= weight_g < 250  -> "Low Stock"
        weight_g >= 250        -> "Available"
    """
    conn = get_connection()
    cursor = conn.cursor()

    status = _pct_status(cursor, quadrant, weight_g)

    now_str = datetime.now().strftime("%I:%M %p")
    cursor.execute(
        "UPDATE inventory SET weight_g = ?, status = ?, last_updated = ? WHERE quadrant = ?",
        (weight_g, status, now_str, quadrant)
    )
    cursor.execute(
        "INSERT INTO weight_logs (quadrant, weight_g) VALUES (?, ?)",
        (quadrant, weight_g)
    )

    # Fetch item_name so the broadcast can name the depleted item
    cursor.execute("SELECT item_name FROM inventory WHERE quadrant = ?", (quadrant,))
    row = cursor.fetchone()
    item_name = row["item_name"] if row else f"Quadrant {quadrant}"
    _record_transitions(cursor, quadrant, weight_g, item_name)

    conn.commit()
    conn.close()

    return {"status": status, "item_name": item_name}

def get_quadrant(quadrant: int) -> dict:
    """Return the current inventory row for a single quadrant."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory WHERE quadrant = ?", (quadrant,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def update_quadrant_item(quadrant: int, item_name: str, weight_g: float) -> dict:
    """
    Delta-binding: assign a newly scanned item to a specific quadrant and
    record its weight in one atomic operation.

    Called by the update-weight endpoint when a positive weight delta is
    detected immediately after a camera scan (pending_scan is set).

    Returns the same {status, item_name} dict as update_quadrant_weight so
    the caller can broadcast a consistent payload.
    """
    conn = get_connection()
    cursor = conn.cursor()

    status = _pct_status(cursor, quadrant, weight_g)

    now_str = datetime.now().strftime("%I:%M %p")

    # Update both the item name AND the weight in one shot
    cursor.execute(
        """UPDATE inventory
              SET item_name = ?, weight_g = ?, status = ?, last_updated = ?
            WHERE quadrant = ?""",
        (item_name, weight_g, status, now_str, quadrant),
    )
    cursor.execute(
        "INSERT INTO weight_logs (quadrant, weight_g) VALUES (?, ?)",
        (quadrant, weight_g),
    )

    _record_transitions(cursor, quadrant, weight_g, item_name, rename=True)

    conn.commit()
    conn.close()

    print(f"[BIND] Quadrant {quadrant} → {item_name} ({weight_g}g, {status})")
    return {"status": status, "item_name": item_name}


def log_scan_result(label: str, confidence: float):
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%I:%M %p")
    cursor.execute(
        "INSERT INTO scan_logs (label, confidence, timestamp) VALUES (?, ?, ?)",
        (label, confidence, now_str)
    )
    conn.commit()
    conn.close()

def get_recent_scans(limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scan_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_inventory_summary():
    """Returns a quick summary: total items, critical count, low stock count."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM inventory")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM inventory WHERE status = 'Critical'")
    critical = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM inventory WHERE status = 'Low Stock'")
    low_stock = cursor.fetchone()[0]
    conn.close()
    return {"total_items": total, "critical": critical, "low_stock": low_stock}

def get_depletion_analytics():
    inventory = get_all_inventory()
    metrics = []

    for item in inventory:
        name = item['item_name']
        current_w = item['weight_g']
        quadrant = item['quadrant']

        # Get recent weight logs for this quadrant to compute depletion rate via linear regression
        conn = get_connection()
        cursor = conn.cursor()
        # Get last 20 weight logs for this quadrant, ordered by timestamp (newest 20, re-ordered oldest first for regression)
        cursor.execute("""
            SELECT weight_g, timestamp FROM weight_logs
            WHERE quadrant = ?
            ORDER BY timestamp DESC
            LIMIT 20
        """, (quadrant,))
        logs = list(reversed(cursor.fetchall()))  # newest 20, back in oldest->newest order
        conn.close()

        # If we have sufficient data points, compute linear regression
        if len(logs) >= 3:
            try:
                # Convert timestamps to seconds since epoch for linear regression
                times = []
                weights = []
                for log in logs:
                    weight_g = log[0]
                    timestamp_str = log[1]
                    # Parse SQLite timestamp format: "YYYY-MM-DD HH:MM:SS"
                    dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    # Convert to seconds since epoch
                    timestamp_seconds = dt.timestamp()
                    times.append(timestamp_seconds)
                    weights.append(weight_g)

                # Perform linear regression: weight = slope * time + intercept
                # Slope is the rate of weight change per second
                n = len(times)
                sum_x = sum(times)
                sum_y = sum(weights)
                sum_xy = sum(t * w for t, w in zip(times, weights))
                sum_x2 = sum(t * t for t in times)

                # Calculate slope (rate of change per second)
                slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)

                # Convert slope to grams per day (negative slope means depletion)
                # slope is in grams/second, convert to grams/day: * 60 * 60 * 24
                daily_rate_g = -slope * 86400  # Negative because we want depletion rate as positive

                # Ensure rate is reasonable (between 0 and 500g/day)
                if daily_rate_g < 0:
                    daily_rate_g = 0  # Weight increasing (shouldn't happen in depletion)
                elif daily_rate_g > 500:
                    daily_rate_g = 500  # Cap at reasonable maximum

            except Exception as e:
                # Fallback to fixed rates if regression fails
                print(f"Linear regression failed for {name}: {e}")
                daily_rate_g = get_fallback_rate(name)
        else:
            # Not enough data points, use fallback rate
            daily_rate_g = get_fallback_rate(name)

        # --- multiple regression (backend/depletion_mr.py). Any problem -> keep the linear/fallback rate above ---
        try:
            from depletion_mr import forecast_days_left as _mr_forecast
            _c = get_connection()
            _cur = _c.cursor()
            _cur.execute("""
                SELECT MAX(timestamp), AVG(weight_g) FROM weight_logs
                WHERE quadrant = ?
                GROUP BY CAST(strftime('%s', timestamp) AS INTEGER) / 600
                ORDER BY MAX(timestamp) DESC
                LIMIT 1000
            """, (quadrant,))
            _rows = list(reversed(_cur.fetchall()))
            _c.close()
            _mr = _mr_forecast(_rows)
            if _mr.get("method") == "multiple_regression" and _mr.get("days_left") and current_w and current_w > 0:
                daily_rate_g = max(0.0, min(500.0, current_w / max(_mr["days_left"], 0.1)))
                print(f"[FORECAST] {name}: multiple regression -> {_mr['days_left']} d (r2={_mr['r2']}, n={_mr['n']})")
        except Exception as _e:
            print(f"[FORECAST] multiple regression skipped for {name}: {_e}")

        # Calculate estimated days remaining
        if daily_rate_g > 0:
            days_left = round(current_w / daily_rate_g, 1)
        else:
            days_left = 99.0  # Essentially infinite if no depletion

        metrics.append({
            "item_name": name,
            "quadrant": item['quadrant'],
            "current_weight_g": current_w,
            "daily_rate_g": round(daily_rate_g, 2),
            "estimated_days_remaining": days_left,
            "stock_status": item['status'],
        })

    return metrics


def get_fallback_rate(item_name: str) -> float:
    """Fallback depletion rate (g/day) when insufficient data for linear regression."""
    fallback_rates = {
        "Apple":       120.0,
        "Orange":      140.0,
        "Guava":       130.0,
        "Pomegranate": 120.0,
        "Carrot": 100.0,
        "Tomato": 120.0,
        "Ginger": 25.0,
        "Cucumber": 150.0,
        "Lemon": 50.0,
    }
    return fallback_rates.get(item_name, 120.0)


# =====================================================================================
#  SHELF-LIFE TRACKING  (placed / removed timestamps + "days until it goes bad")
#  Added by apply_shelf_life.py.  The numbers below are ASSUMPTIONS - change them here.
# =====================================================================================
EMPTY_G = 10.0              # below this the tray counts as empty -> item REMOVED
PLACE_G = 30.0              # at or above this (tray was empty) -> item PLACED
RETURN_GRACE_MIN = 10       # put back within 10 min = same stay (you only picked it up to look)
BAD_LOSS_PCT = 10.0         # a fruit that lost this much weight (moisture) counts as "gone bad"
TREND_MIN_SPAN_DAYS = 2.0   # weight trend is only trusted after this many days of data
TREND_MIN_POINTS = 8
STEP_DISTURB_G = 10.0       # a jump this big between two readings = someone touched it, restart the trend
DEFAULT_SHELF_LIFE_DAYS = 14.0
FRUIT_SHELF_LIFE_DAYS = {   # whole fruit in a fridge, rough rule-of-thumb values (not measured)
    "Apple": 28.0,
    "Orange": 21.0,
    "Guava": 7.0,
    "Pomegranate": 28.0,
    "Carrot": 21.0,
    "Tomato": 7.0,
    "Ginger": 21.0,
    "Cucumber": 7.0,
    "Lemon": 28.0,
}


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_utc(s: str):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _local_text(s: Optional[str]) -> str:
    """UTC database timestamp -> '03 Oct, 04:12 PM' in the PC's local time."""
    if not s:
        return ""
    return _parse_utc(s).astimezone().strftime("%d %b, %I:%M %p")


def _ensure_shelf_table(cursor):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shelf_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quadrant INTEGER NOT NULL,
        item_name TEXT NOT NULL,
        event TEXT NOT NULL,
        weight_g REAL,
        timestamp TEXT NOT NULL,
        source TEXT DEFAULT 'sensor'
    )
    """)


def _last_event(cursor, quadrant):
    cursor.execute("SELECT * FROM shelf_events WHERE quadrant = ? ORDER BY id DESC LIMIT 1", (quadrant,))
    return cursor.fetchone()


def _seed_open_stays(cursor):
    """Fruit already on the shelf when the server starts: its start time is unknown, so
    record 'first seen' now (marked source='startup' and shown as 'first seen' in the app)."""
    cursor.execute("SELECT quadrant, item_name, weight_g FROM inventory")
    for r in cursor.fetchall():
        if r["weight_g"] >= PLACE_G and _last_event(cursor, r["quadrant"]) is None:
            cursor.execute(
                "INSERT INTO shelf_events (quadrant, item_name, event, weight_g, timestamp, source) "
                "VALUES (?, ?, 'PLACED', ?, ?, 'startup')",
                (r["quadrant"], r["item_name"], r["weight_g"], _utc_now_str()),
            )


def _record_transitions(cursor, quadrant, new_w, item_name, rename=False):
    """Called inside the same transaction as every weight update.
       tray empty  + weight >= 30 g  -> PLACED
       tray holding + weight  < 10 g -> REMOVED
       put back within 10 min        -> the old stay simply continues."""
    try:
        last = _last_event(cursor, quadrant)
        is_open = last is not None and last["event"] == "PLACED"
        if not is_open and new_w >= PLACE_G:
            if last is not None and last["event"] == "REMOVED" and last["item_name"] == item_name:
                gap_min = (datetime.now(timezone.utc) - _parse_utc(last["timestamp"])).total_seconds() / 60.0
                if gap_min <= RETURN_GRACE_MIN:
                    cursor.execute("DELETE FROM shelf_events WHERE id = ?", (last["id"],))
                    print(f"[SHELF] Q{quadrant} {item_name} put back after {gap_min:.1f} min - same stay continues")
                    return
            cursor.execute(
                "INSERT INTO shelf_events (quadrant, item_name, event, weight_g, timestamp, source) "
                "VALUES (?, ?, 'PLACED', ?, ?, 'sensor')",
                (quadrant, item_name, new_w, _utc_now_str()),
            )
            print(f"[SHELF] Q{quadrant} {item_name} PLACED ({new_w:.0f} g)")
        elif is_open and new_w < EMPTY_G:
            cursor.execute(
                "INSERT INTO shelf_events (quadrant, item_name, event, weight_g, timestamp, source) "
                "VALUES (?, ?, 'REMOVED', ?, ?, 'sensor')",
                (quadrant, last["item_name"], new_w, _utc_now_str()),
            )
            print(f"[SHELF] Q{quadrant} {last['item_name']} REMOVED")
        elif is_open and rename and last["item_name"] != item_name:
            cursor.execute("UPDATE shelf_events SET item_name = ? WHERE id = ?", (item_name, last["id"]))
    except Exception as e:                      # never let tracking break a weight update
        print("[SHELF] transition skipped:", e)


def shelf_rename(quadrant: int, item_name: str):
    """The Add button names the item AFTER it was placed: put the right name on the open stay."""
    conn = get_connection()
    cursor = conn.cursor()
    last = _last_event(cursor, quadrant)
    if last is not None and last["event"] == "PLACED" and last["item_name"] != item_name:
        cursor.execute("UPDATE shelf_events SET item_name = ? WHERE id = ?", (item_name, last["id"]))
        conn.commit()
    conn.close()


def get_shelf_events(quadrant: int = 0, limit: int = 50):
    conn = get_connection()
    cursor = conn.cursor()
    if quadrant:
        cursor.execute("SELECT * FROM shelf_events WHERE quadrant = ? ORDER BY id DESC LIMIT ?", (quadrant, limit))
    else:
        cursor.execute("SELECT * FROM shelf_events ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "quadrant": r["quadrant"], "item_name": r["item_name"], "event": r["event"],
        "weight_g": r["weight_g"], "time": _local_text(r["timestamp"]),
        "first_seen": r["source"] == "startup",
    } for r in rows]


# ---- freshness reminders (patch_freshness_alerts.py) ----------------------------------
import os as _os_f
UNTOUCHED_HOURS = float(_os_f.environ.get("UNTOUCHED_HOURS", "24"))   # no weight change for this long
SPOIL_SOON_DAYS = float(_os_f.environ.get("SPOIL_SOON_DAYS", "3"))    # warn when this few days are left
DAY_START_H = float(_os_f.environ.get("DAY_START_H", "9"))            # only notify between these hours
DAY_END_H = float(_os_f.environ.get("DAY_END_H", "19"))               # (PC local time)


def get_freshness_alerts(force: bool = False, now_local=None):
    """What to remind the user about right now. The app polls this and shows each alert once per day."""
    shelf = get_shelf_life()
    now_utc = datetime.now(timezone.utc)
    nl = now_local or datetime.now()
    hour = nl.hour + nl.minute / 60.0
    daytime = DAY_START_H <= hour < DAY_END_H
    conn = get_connection()
    cursor = conn.cursor()
    items, alerts = [], []
    for s in shelf:
        if s.get("state") != "on_shelf":
            continue
        q = s["quadrant"]
        cursor.execute("SELECT timestamp FROM shelf_events WHERE quadrant = ? AND event = 'PLACED' "
                       "ORDER BY id DESC LIMIT 1", (q,))
        p = cursor.fetchone()
        if p is None:
            continue
        last_touch = _parse_utc(p["timestamp"])
        cursor.execute("SELECT weight_g, timestamp FROM weight_logs WHERE quadrant = ? AND timestamp >= ? "
                       "ORDER BY timestamp ASC, id ASC", (q, p["timestamp"]))
        prev = None
        for r in cursor.fetchall():
            if prev is not None and abs(r["weight_g"] - prev) >= 10.0:     # someone touched it
                last_touch = _parse_utc(r["timestamp"])
            prev = r["weight_g"]
        untouched_h = max(0.0, (now_utc - last_touch).total_seconds() / 3600.0)
        left = s.get("predicted_days_until_bad")
        name = s["item_name"]
        items.append({"quadrant": q, "item_name": name, "untouched_hours": round(untouched_h, 1),
                      "days_left": left, "freshness": s.get("freshness")})
        if s.get("current_weight_g", 0) < 10.0:
            continue
        kind = None
        if left is not None and (left <= SPOIL_SOON_DAYS or s.get("freshness") == "Past best"):
            kind = "past_best" if left <= 0 else "spoil_soon"
            if left <= 0:
                title = "%s may already be going bad" % name
                body = "%s in Quadrant %d has passed its expected shelf life. Check it before using it." % (name, q)
            else:
                d = max(1, int(round(left)))
                title = "Use your %s soon" % name.lower()
                body = "%s in Quadrant %d may go bad in about %d day%s. Use it soon." % (name, q, d, "" if d == 1 else "s")
        elif untouched_h >= UNTOUCHED_HOURS:
            kind = "untouched"
            days = untouched_h / 24.0
            ago = ("%d day%s" % (int(days), "" if int(days) == 1 else "s")) if days >= 1 else "%d hours" % int(untouched_h)
            title = "%s has not been touched" % name
            body = "%s in Quadrant %d has not been used for %s." % (name, q, ago)
            if left is not None:
                body += " Use it - it may go bad in about %d day%s." % (max(1, int(round(left))), "" if round(left) <= 1 else "s")
        if kind:
            alerts.append({"quadrant": q, "item_name": name, "kind": kind, "title": title, "body": body,
                           "days_left": left, "untouched_hours": round(untouched_h, 1)})
    conn.close()
    return {"daytime": daytime, "checked_at": nl.strftime("%Y-%m-%d %H:%M"),
            "alerts": alerts if (daytime or force) else [], "items": items}


def get_shelf_life():
    """One entry per quadrant that has (or had) fruit: when placed, whether removed,
    days on shelf, weight change and the predicted days until it goes bad."""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc)
    cursor.execute("SELECT quadrant, item_name, weight_g FROM inventory ORDER BY quadrant ASC")
    inv = cursor.fetchall()
    out = []
    for row in inv:
        q = row["quadrant"]
        cursor.execute("SELECT * FROM shelf_events WHERE quadrant = ? AND event = 'PLACED' "
                       "ORDER BY id DESC LIMIT 1", (q,))
        p = cursor.fetchone()
        if p is None:
            continue
        cursor.execute("SELECT * FROM shelf_events WHERE quadrant = ? AND event = 'REMOVED' AND id > ? "
                       "ORDER BY id ASC LIMIT 1", (q, p["id"]))
        r = cursor.fetchone()
        removed = r is not None
        name = p["item_name"] if removed else row["item_name"]
        end_dt = _parse_utc(r["timestamp"]) if removed else now
        age_days = max(0.0, (end_dt - _parse_utc(p["timestamp"])).total_seconds() / 86400.0)

        cursor.execute(
            "SELECT weight_g, timestamp FROM weight_logs WHERE quadrant = ? AND timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp ASC, id ASC",
            (q, p["timestamp"], end_dt.strftime("%Y-%m-%d %H:%M:%S")),
        )
        pts = [(_parse_utc(x["timestamp"]).timestamp(), x["weight_g"]) for x in cursor.fetchall()
               if x["weight_g"] >= EMPTY_G]

        # restart the trend after the last time somebody touched the fruit (jump >= 10 g)
        first = 0
        for i in range(1, len(pts)):
            if abs(pts[i][1] - pts[i - 1][1]) >= STEP_DISTURB_G:
                first = i
        win = pts[first:]
        cur_w = win[-1][1] if win else float(row["weight_g"])
        start_w = float(np.median([w for _, w in win[:3]])) if win else cur_w
        loss_pct = max(0.0, (start_w - cur_w) / start_w * 100.0) if start_w > 0 else 0.0

        life = FRUIT_SHELF_LIFE_DAYS.get(name, DEFAULT_SHELF_LIFE_DAYS)
        pred, basis, loss_rate = None, "", None
        if not removed:
            pred = max(0.0, life - age_days)
            basis = f"age ({life:.0f}-day fridge life assumed)"
            span = (win[-1][0] - win[0][0]) / 86400.0 if len(win) >= 2 else 0.0
            if len(win) >= TREND_MIN_POINTS and span >= TREND_MIN_SPAN_DAYS:
                step = max(1, len(win) // 2000)
                xs = [(t - win[0][0]) / 86400.0 for t, _ in win[::step]]
                ys = [w for _, w in win[::step]]
                slope = float(np.polyfit(xs, ys, 1)[0])
                if -slope > 0.05:
                    loss_rate = -slope
                    limit_w = start_w * (1.0 - BAD_LOSS_PCT / 100.0)
                    trend_left = max(0.0, (cur_w - limit_w) / loss_rate)
                    if trend_left < pred:
                        pred, basis = trend_left, f"weight loss {loss_rate:.2f} g/day"
            elif span < TREND_MIN_SPAN_DAYS:
                basis += "; weight trend needs 2 days of data"

        if removed:
            freshness = "Removed"
        else:
            frac = pred / life if life > 0 else 0.0
            freshness = "Fresh" if frac >= 0.40 else ("Use soon" if frac >= 0.15 else "Past best")

        out.append({
            "quadrant": q,
            "item_name": name,
            "state": "removed" if removed else "on_shelf",
            "placed_text": _local_text(p["timestamp"]),
            "removed_text": _local_text(r["timestamp"]) if removed else "",
            "first_seen": p["source"] == "startup",
            "days_on_shelf": round(age_days, 1),
            "start_weight_g": round(start_w, 1),
            "current_weight_g": round(cur_w, 1),
            "weight_loss_pct": round(loss_pct, 1),
            "loss_rate_g_per_day": round(loss_rate, 2) if loss_rate else None,
            "shelf_life_days": life,
            "predicted_days_until_bad": round(pred, 1) if pred is not None else None,
            "basis": basis,
            "freshness": freshness,
        })
    conn.close()
    return out
