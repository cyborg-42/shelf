#!/usr/bin/env python3
"""
shelf_sim.py  -  FAKE ESP32 shelf + FAKE scanner for Shelf.

Plays scans and weight changes at your running backend so the phone app (or the
web /docs page) shows live values with NO hardware.

    python shelf_sim.py --host 10.144.47.46 demo
    python shelf_sim.py --host 10.144.47.46 place Banana 3 180
    python shelf_sim.py --host 10.144.47.46 set 2 350
    python shelf_sim.py --host 10.144.47.46 drain 1 --minutes 3
    python shelf_sim.py --host 10.144.47.46 demo --image banana.jpg

NOTE: --host / --port / --ttl go BEFORE the command word (demo, place, set...).

EVERYTHING THIS SCRIPT PRODUCES IS SIMULATED.  Do not report it as measured
hardware data - label it "Simulated" in the report / viva.

How it knows your API: it downloads  http://HOST:PORT/openapi.json  and builds
each request from the server's own schema, so it keeps working even if field
names differ from what I assumed (quadrant vs quadrant_id, weight vs weight_g...).
Use  `python shelf_sim.py schema`  to see what it found.

Standard library only.  `pip install websockets` (optional) also prints the live
WebSocket events the app would receive.
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

BASE = ""
TTL = 30


def say(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


# ----------------------------------------------------------------- http
def http(method, path, body=None, headers=None, raw=None, timeout=15):
    url = BASE + path
    data = raw
    hdr = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode(errors="ignore")
            return r.status, txt
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")
    except Exception as e:
        return None, str(e)


def short(txt, n=160):
    txt = " ".join(txt.split())
    return txt if len(txt) <= n else txt[:n] + "..."


# ------------------------------------------------------------ openapi
SPEC = {}


def load_spec():
    global SPEC
    code, txt = http("GET", "/openapi.json")
    if code != 200:
        sys.exit(
            f"Cannot read {BASE}/openapi.json ({code}: {short(txt)}).\n"
            "Is the backend running?  (run bringup_check.py)"
        )
    SPEC = json.loads(txt)


def resolve(schema):
    """Follow $ref chains."""
    seen = 0
    while schema and "$ref" in schema and seen < 10:
        name = schema["$ref"].split("/")[-1]
        schema = SPEC.get("components", {}).get("schemas", {}).get(name, {})
        seen += 1
    return schema or {}


def find_route(*needles, method=None):
    for path, ops in SPEC.get("paths", {}).items():
        if all(n in path for n in needles):
            for m, op in ops.items():
                if method is None or m.upper() == method:
                    return path, m.upper(), op
    return None, None, None


def guess_value(name, sch, ctx):
    """Pick a value for one schema property from its name/type."""
    n = name.lower()
    t = sch.get("type")
    if t == "array":
        item = resolve(sch.get("items", {}))
        if item.get("type") in ("number", "integer") and "weights" in ctx:
            return list(ctx["weights"])
        return []
    if t in ("integer", "number"):
        if any(k in n for k in ("weight", "gram", "mass")) or n in ("w", "g", "value"):
            return ctx["weight"] if t == "number" else int(round(ctx["weight"]))
        if any(k in n for k in ("quad", "slot", "shelf", "cell")) or n in (
            "q",
            "id",
            "index",
        ):
            return ctx["quadrant"]
        if "conf" in n or "score" in n:
            return ctx.get("confidence", 0.9)
        return sch.get("default", 0)
    if t == "string":
        if any(k in n for k in ("time", "date", "_at")):
            return datetime.now(timezone.utc).isoformat()
        if any(k in n for k in ("item", "name", "label", "class", "produce")):
            return ctx.get("item", "Banana")
        if "device" in n or "source" in n:
            return "shelf_sim"
        return sch.get("default", "sim")
    if t == "boolean":
        return sch.get("default", False)
    return sch.get("default")


def build_body(op, ctx):
    """JSON body (or None) and query dict from the operation's schema."""
    body = None
    rb = op.get("requestBody", {}).get("content", {})
    if "application/json" in rb:
        sch = resolve(rb["application/json"].get("schema", {}))
        props = sch.get("properties", {})
        req = set(sch.get("required", []))
        body = {}
        for k, v in props.items():
            v = resolve(v) if "$ref" in v else v
            val = guess_value(k, v, ctx)
            body[k] = val
    query = {}
    for p in op.get("parameters", []):
        if p.get("in") == "query":
            query[p["name"]] = guess_value(p["name"], resolve(p.get("schema", {})), ctx)
    return body, query


def qs(query):
    if not query:
        return ""
    from urllib.parse import urlencode

    return "?" + urlencode(query)


# ------------------------------------------------------------ actions
STATE = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}  # what the fake shelf currently "reads"


def post_weight(q, grams, note=""):
    path, method, op = (
        find_route("update-weight")
        if find_route("update-weight")[0]
        else find_route("weight")
    )
    if not path:
        sys.exit(
            "No weight route found in /openapi.json. Run: python shelf_sim.py schema"
        )
    STATE[q] = max(0.0, float(grams))
    ctx = {
        "quadrant": q,
        "weight": STATE[q],
        "weights": [STATE[i] for i in (1, 2, 3, 4)],
    }
    body, query = build_body(op, ctx)
    code, txt = http(method, path + qs(query), body=body)
    say("SIM-ESP32", f"Q{q} = {STATE[q]:.0f} g {note}  -> HTTP {code}  {short(txt)}")
    if code == 422:
        say(
            "HINT",
            "422 = field names differ. Run  python shelf_sim.py schema  and send me the output.",
        )
    return code, txt


def open_scan(item, image=None):
    """Real photo -> scan-item endpoint; otherwise open the pending buffer directly."""
    if image:
        path, method, op = find_route("scan-item")
        if not path:
            path, method, op = find_route("scan")
        rb = op.get("requestBody", {}).get("content", {}) if op else {}
        field = "file"
        if "multipart/form-data" in rb:
            props = resolve(rb["multipart/form-data"].get("schema", {})).get(
                "properties", {}
            )
            for k, v in props.items():
                if v.get("format") == "binary" or v.get("type") == "string":
                    field = k
                    break
        boundary = uuid.uuid4().hex
        mime = mimetypes.guess_type(image)[0] or "image/jpeg"
        with open(image, "rb") as f:
            blob = f.read()
        raw = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{os.path.basename(image)}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode()
            + blob
            + f"\r\n--{boundary}--\r\n".encode()
        )
        code, txt = http(
            "POST",
            path,
            raw=raw,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=60,
        )
        say(
            "SIM-SCAN",
            f"REAL photo {os.path.basename(image)} -> HTTP {code}  {short(txt)}",
        )
        return code, txt
    path, method, op = find_route("pending-scan", method="POST")
    if not path:
        path, method, op = find_route("simulate-scan", method="POST")
    if not path:
        say(
            "SIM-SCAN",
            "No POST pending-scan / simulate-scan route; pass --image <photo.jpg> to use the real scan endpoint.",
        )
        return None, ""
    ctx = {"item": item, "confidence": 0.90, "quadrant": 0, "weight": 0}
    body, query = build_body(op, ctx)
    code, txt = http("POST", path + qs(query), body=body)
    say(
        "SIM-SCAN",
        f"fake scan '{item}' (conf 0.90) opens {TTL}s window -> HTTP {code}  {short(txt)}",
    )
    return code, txt


def show_pending():
    path, _, _ = find_route("pending-scan", method="GET")
    if path:
        code, txt = http("GET", path)
        say("CHECK", f"pending-scan buffer: {short(txt)}")


# ------------------------------------------------------- websocket tap
def ws_listen(host, port):
    try:
        import asyncio
        import websockets
    except ImportError:
        say("WS", "(pip install websockets to also print live WebSocket events)")
        return

    async def run():
        try:
            async with websockets.connect(f"ws://{host}:{port}/ws") as ws:
                say("WS", "listening on /ws (this is what the app receives)")
                async for m in ws:
                    say("WS-EVENT", short(m, 200))
        except Exception as e:
            say("WS", f"closed: {e}")

    threading.Thread(target=lambda: asyncio.run(run()), daemon=True).start()
    time.sleep(0.5)


# -------------------------------------------------------------- scenarios
def demo(args):
    say("INFO", "ALL DATA BELOW IS SIMULATED (fake scanner + fake shelf).")
    for q in (1, 2, 3, 4):
        post_weight(q, 0, "(baseline, empty shelf)")
        time.sleep(0.3)
    plan = [
        ("Apple", 1, 150),
        ("Orange", 2, 200),
        ("Banana", 3, 180),
        ("Carrot", 4, 90),
    ]
    for item, q, g in plan:
        print()
        say(
            "STEP",
            f"Scan {item}, then place {g} g on Q{q} (inside 30 s) -> EXPECT: bind to Q{q}",
        )
        open_scan(item, image=args.image if item == "Banana" else None)
        time.sleep(args.pause)
        post_weight(q, g, f"(+{g} g placed)")
        time.sleep(args.pause)
        show_pending()
    print()
    say("STEP", "Eat 25 g from Q3 -> EXPECT: consumption (delta <= -10 g), no bind")
    post_weight(3, STATE[3] - 25, "(-25 g eaten)")
    time.sleep(args.pause)
    say(
        "STEP",
        "Jitter +6 g on Q1 with no scan -> EXPECT: ignored as jitter (under +30 g)",
    )
    post_weight(1, STATE[1] + 6, "(+6 g jitter)")
    time.sleep(args.pause)
    say(
        "STEP",
        "Put 60 g on Q2 WITHOUT scanning -> EXPECT: weight updates, item name NOT changed",
    )
    post_weight(2, STATE[2] + 60, "(+60 g unscanned)")
    time.sleep(args.pause)
    if args.ttl_test:
        say(
            "STEP",
            f"Scan Apple, wait {TTL + 3} s (window expires), then place 100 g on Q4 -> EXPECT: NO bind",
        )
        open_scan("Apple")
        time.sleep(TTL + 3)
        post_weight(4, STATE[4] + 100, "(+100 g too late)")
    print()
    say(
        "DONE",
        "Check the phone: 4 quadrants filled, Q3 reduced, Q2 unchanged name. All SIMULATED.",
    )


def drain(args):
    q = args.quadrant
    say(
        "INFO",
        f"SIMULATED slow consumption of Q{q} for {args.minutes} min (one post every {args.every}s)",
    )
    steps = max(1, int(args.minutes * 60 / args.every))
    start = args.start
    post_weight(q, start, "(start)")
    for i in range(1, steps + 1):
        time.sleep(args.every)
        post_weight(q, start - args.rate * i, "(draining)")


def main():
    global BASE, TTL
    ap = argparse.ArgumentParser(
        description="Shelf fake scanner + fake ESP32 (SIMULATED data)"
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument(
        "--ttl",
        type=int,
        default=30,
        help="pending-scan TTL in seconds (for the expiry test)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--pause", type=float, default=2.0)
    d.add_argument("--image")
    d.add_argument("--ttl-test", action="store_true")
    p = sub.add_parser("place")
    p.add_argument("item")
    p.add_argument("quadrant", type=int)
    p.add_argument("grams", type=float)
    p.add_argument("--image")
    p.add_argument(
        "--current", type=float, default=0, help="what the quadrant reads now (grams)"
    )
    s = sub.add_parser("set")
    s.add_argument("quadrant", type=int)
    s.add_argument("grams", type=float)
    dr = sub.add_parser("drain")
    dr.add_argument("quadrant", type=int)
    dr.add_argument("--minutes", type=float, default=3)
    dr.add_argument("--every", type=float, default=10)
    dr.add_argument("--start", type=float, default=400)
    dr.add_argument("--rate", type=float, default=15, help="grams removed per post")
    sub.add_parser("schema")
    a = ap.parse_args()
    BASE = f"http://{a.host}:{a.port}"
    TTL = a.ttl
    load_spec()
    if a.cmd == "schema":
        for path, ops in SPEC["paths"].items():
            for m, op in ops.items():
                body, query = build_body(
                    op,
                    {
                        "quadrant": 1,
                        "weight": 100.0,
                        "weights": [0, 0, 0, 0],
                        "item": "Banana",
                    },
                )
                print(
                    f"{m.upper():6} {path}\n       body={json.dumps(body)}  query={query}"
                )
        return
    ws_listen(a.host, a.port)
    if a.cmd == "demo":
        demo(a)
    elif a.cmd == "place":
        open_scan(a.item, image=a.image)
        time.sleep(1.5)
        post_weight(a.quadrant, a.current + a.grams, f"(+{a.grams:.0f} g placed)")
        time.sleep(1)
        show_pending()
    elif a.cmd == "set":
        post_weight(a.quadrant, a.grams)
    elif a.cmd == "drain":
        drain(a)
    time.sleep(1)


if __name__ == "__main__":
    main()
