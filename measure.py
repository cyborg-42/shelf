"""
measure.py - take REAL measurements from the Shelf ESP32 over USB and save them to CSV.

It talks to the sketch's own Serial commands ("live", "post off", "post on"), so nothing in the sketch changes.
While it runs it sends "post off", so your test weights are NOT written into the app's database / forecast
history. It sends "post on" again when it finishes.

BEFORE YOU RUN IT
  * Close the Arduino Serial Monitor (only one program can use the USB port).
  * Find the port in Arduino IDE -> Tools -> Port (e.g. COM5).
  * Install once:   .venv\\Scripts\\python.exe -m pip install pyserial

MODES
  python measure.py accuracy --port COM5      known mass on a quadrant -> mean reading, error, noise
  python measure.py drift    --port COM5 --minutes 10 [--quadrant 1]
                                              leave a load (or nothing) on and watch it wander
  python measure.py bind                      tally scan-and-place trials (typed in by you; no USB needed)

Everything written is MEASURED data from your shelf. Put the CSV files in the report, not typed-in guesses.
"""
import argparse, csv, math, re, sys, time
from datetime import datetime
from pathlib import Path

LIVE = re.compile(r"Q(\d)\s+(-?\d+)\s+(-?\d+(?:\.\d+)?)g")
SETTLE_S = 3.0      # ignore the first seconds after you place the mass
RECORD_S = 10.0     # accuracy: how long to average


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stats(v):
    n = len(v)
    if n == 0:
        return None
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": m, "std": sd, "min": min(v), "max": max(v)}


def slope_per_min(ts, v):
    """Least-squares slope of reading vs time, grams per minute."""
    n = len(v)
    if n < 3:
        return 0.0
    mt = sum(ts) / n
    mv = sum(v) / n
    den = sum((t - mt) ** 2 for t in ts)
    if den == 0:
        return 0.0
    return sum((t - mt) * (x - mv) for t, x in zip(ts, v)) / den * 60.0


class Shelf:
    def __init__(self, ser):
        self.ser = ser

    def send(self, text):
        self.ser.write((text + "\n").encode())
        self.ser.flush()

    def lines(self, seconds):
        """Yield (t, {quadrant: grams}) for every live line seen in the next `seconds`."""
        t0 = time.time()
        while time.time() - t0 < seconds:
            raw = self.ser.readline().decode(errors="ignore").strip()
            if not raw:
                continue
            found = LIVE.findall(raw)
            if len(found) == 4:
                yield time.time() - t0, {int(q): float(g) for q, _r, g in found}

    def start_live(self):
        self.send("post off")
        time.sleep(0.4)
        for _attempt in range(2):                  # "live" TOGGLES, so check we really get lines
            self.send("live")
            got = list(self.lines(3.0))
            if got:
                return True
            self.send("live")                      # it was already on and we just turned it off: turn it back on
            got = list(self.lines(3.0))
            if got:
                return True
        return False

    def stop(self):
        try:
            self.send("live")                      # turn live printing off
            time.sleep(0.3)
            self.send("post on")
        except Exception:
            pass


def open_shelf(port, baud):
    import serial
    ser = serial.Serial(port, baud, timeout=1)
    time.sleep(2.0)                                # opening the port resets many ESP32 boards
    ser.reset_input_buffer()
    sh = Shelf(ser)
    if not sh.start_live():
        sys.exit("No live data. Is the Serial Monitor closed? Right port? Is any quadrant calibrated (type 'show' in the Arduino monitor)?")
    return sh


def append_csv(path, header, row):
    new = not Path(path).exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def cmd_accuracy(a):
    sh = open_shelf(a.port, a.baud)
    out = a.out or "accuracy_measured.csv"
    hdr = ["time", "quadrant", "true_g", "mean_g", "error_g", "error_pct", "std_g", "min_g", "max_g", "n"]
    print("Accuracy test. Posting is OFF. Type nothing to finish. true_g can be 0 (empty tray).")
    try:
        while True:
            q = input("\nQuadrant 1-4 (Enter to finish): ").strip()
            if not q:
                break
            if q not in "1234" or len(q) != 1:
                print("  must be 1, 2, 3 or 4"); continue
            true_g = float(input("TRUE mass in grams (from a kitchen scale; 0 = empty): "))
            input("Place it in the MIDDLE of Q%s's tray, then press Enter. " % q)
            list(sh.lines(SETTLE_S))                # let it settle, discard
            vals = [g[int(q)] for _t, g in sh.lines(RECORD_S)]
            s = stats(vals)
            if not s:
                print("  no readings, try again"); continue
            err = s["mean"] - true_g
            pct = (err / true_g * 100.0) if true_g else float("nan")
            print("  Q%s  true %.1f g   mean %.1f g   error %+.1f g (%s)   noise std %.2f g   range %.1f..%.1f   n=%d"
                  % (q, true_g, s["mean"], err, ("%+.1f%%" % pct) if true_g else "n/a", s["std"], s["min"], s["max"], s["n"]))
            append_csv(out, hdr, [now(), q, true_g, round(s["mean"], 2), round(err, 2),
                                  "" if not true_g else round(pct, 2), round(s["std"], 3),
                                  s["min"], s["max"], s["n"]])
    finally:
        sh.stop()
    print("Saved to", out)


def cmd_drift(a):
    sh = open_shelf(a.port, a.baud)
    qs = [a.quadrant] if a.quadrant else [1, 2, 3, 4]
    series = {q: ([], []) for q in qs}
    out = a.out or "drift_measured.csv"
    print("Recording %.1f min on Q%s. Do not touch the shelf." % (a.minutes, ",".join(map(str, qs))))
    try:
        next_print = 0.0
        for t, g in sh.lines(a.minutes * 60.0):
            for q in qs:
                series[q][0].append(t); series[q][1].append(g[q])
            if t >= next_print:
                print("  %3.0f s  " % t + "  ".join("Q%d %.1f g" % (q, g[q]) for q in qs))
                next_print = t + 30.0
    finally:
        sh.stop()
    hdr = ["time", "quadrant", "minutes", "mean_g", "std_g", "min_g", "max_g", "drift_g_per_min", "n"]
    for q in qs:
        ts, vs = series[q]
        s = stats(vs)
        if not s:
            continue
        d = slope_per_min(ts, vs)
        print("Q%d  mean %.2f g  noise std %.2f g  range %.1f..%.1f  drift %+.3f g/min  (n=%d)"
              % (q, s["mean"], s["std"], s["min"], s["max"], d, s["n"]))
        append_csv(out, hdr, [now(), q, a.minutes, round(s["mean"], 2), round(s["std"], 3),
                              s["min"], s["max"], round(d, 4), s["n"]])
    print("Saved to", out)


def cmd_bind(a):
    out = a.out or "binding_trials_measured.csv"
    hdr = ["time", "quadrant", "item_scanned", "bound_correctly"]
    tally = {1: [0, 0], 2: [0, 0], 3: [0, 0], 4: [0, 0]}
    if Path(out).exists():
        for r in csv.DictReader(open(out)):
            q = int(r["quadrant"]); tally[q][1] += 1; tally[q][0] += r["bound_correctly"] == "yes"
    print("Scan-and-place tally. After each trial type the result. Blank quadrant to finish.")
    while True:
        q = input("\nQuadrant 1-4 (Enter to finish): ").strip()
        if not q:
            break
        if q not in ("1", "2", "3", "4"):
            print("  must be 1-4"); continue
        item = input("Item scanned (e.g. Apple): ").strip()
        ok = input("Did the app put the RIGHT item on Q%s within 30 s? (y/n): " % q).strip().lower().startswith("y")
        append_csv(out, hdr, [now(), q, item, "yes" if ok else "no"])
        tally[int(q)][1] += 1; tally[int(q)][0] += ok
        print("  totals: " + " | ".join("Q%d %d/%d" % (k, v[0], v[1]) for k, v in tally.items()))
    tot = sum(v[0] for v in tally.values()); n = sum(v[1] for v in tally.values())
    print("Overall: %d of %d correct" % (tot, n) if n else "No trials recorded.")
    print("Saved to", out)


def main():
    ap = argparse.ArgumentParser(description="Real measurements from the Shelf ESP32")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("accuracy", "drift"):
        p = sub.add_parser(name)
        p.add_argument("--port", required=True)
        p.add_argument("--baud", type=int, default=115200)
        p.add_argument("--out")
        if name == "drift":
            p.add_argument("--minutes", type=float, default=10)
            p.add_argument("--quadrant", type=int, choices=[1, 2, 3, 4])
    b = sub.add_parser("bind"); b.add_argument("--out")
    a = ap.parse_args()
    {"accuracy": cmd_accuracy, "drift": cmd_drift, "bind": cmd_bind}[a.cmd](a)


if __name__ == "__main__":
    main()
