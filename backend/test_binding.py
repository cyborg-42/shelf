"""
test_binding.py
End-to-end delta-binding test using a real banana photo.

Steps:
  1. Check initial inventory state
  2. POST a real banana photo to scan-item → verify YOLO detects it
  3. Verify pending_scan is set
  4. POST weight increase on Q3 → verify auto-binding fires
  5. GET inventory → verify Q3.item_name == "Banana"
  6. Verify pending_scan is cleared
"""

import urllib.request
import json
import io
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8000"
BANANA_IMG = r"dataset/Banana/IMG_20260906_195349_NV.jpg"
TEST_QUADRANT = 3

PASS = "[PASS]"
FAIL = "[FAIL]"

def get(path):
    r = urllib.request.urlopen(f"{BASE}{path}", timeout=5)
    return json.loads(r.read())

def post_json(path, data):
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"{BASE}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code

def post_image(path, img_path):
    with open(img_path, "rb") as f:
        jpeg = f.read()
    boundary = b"bindtest"
    body  = b"--" + boundary + b"\r\n"
    body += b'Content-Disposition: form-data; name="file"; filename="banana.jpg"\r\n'
    body += b"Content-Type: image/jpeg\r\n\r\n"
    body += jpeg + b"\r\n"
    body += b"--" + boundary + b"--\r\n"
    req = urllib.request.Request(
        f"{BASE}{path}", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
        method="POST"
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code

failures = []

def check(label, condition, detail=""):
    tag = PASS if condition else FAIL
    print(f"  {tag} {label}")
    if detail:
        print(f"         {detail}")
    if not condition:
        failures.append(label)

print("=" * 58)
print("  Shelf Delta-Binding End-to-End Test")
print("=" * 58)

# ── Step 1: baseline inventory ────────────────────────────────
print("\n[1] Baseline inventory")
inv = get("/api/v1/inventory")
q3_before = next(i for i in inv if i["quadrant"] == TEST_QUADRANT)
print(f"  Q{TEST_QUADRANT} before: {q3_before['item_name']}  {q3_before['weight_g']}g")
weight_before = q3_before["weight_g"]

# ── Step 2: scan real banana photo ───────────────────────────
print(f"\n[2] Scanning real banana photo ({BANANA_IMG})")
r, code = post_image("/api/v1/scan-item", BANANA_IMG)
print(f"  Response: {r}")
check("scan-item returned 200", code == 200, str(r))
check("YOLO detected Banana", r.get("detected_item") == "Banana",
      f"got '{r.get('detected_item')}'")
check("pending_bind is True", r.get("pending_bind") is True, str(r))

if r.get("detected_item") != "Banana":
    print(f"\n  ⚠️  YOLO didn't detect a banana in this photo.")
    print(f"     Confidence returned: {r.get('confidence')}")
    print(f"     The binding test cannot proceed without a detection.")
    print(f"     Try a different photo from dataset/Banana/")
    sys.exit(1)

# ── Step 3: verify pending_scan buffer ───────────────────────
print("\n[3] Pending scan buffer")
pending = get("/api/v1/pending-scan")
print(f"  Pending state: {pending}")
check("pending is True", pending.get("pending") is True, str(pending))
check("pending item is Banana", pending.get("item") == "Banana", str(pending))
check("TTL is active", (pending.get("expires_in") or 0) > 0, str(pending))

# ── Step 4: weight increase on Q3 (simulate placing banana) ──
print(f"\n[4] Weight increase on Q{TEST_QUADRANT} (simulating banana placement)")
new_weight = weight_before + 180.0  # add 180g — well above 30g threshold
print(f"  Posting weight: {new_weight}g  (delta={new_weight - weight_before:+.0f}g)")
r, code = post_json("/api/v1/update-weight", {
    "quadrant":     TEST_QUADRANT,
    "weight_grams": new_weight
})
print(f"  Response: {r}")
check("update-weight returned 200", code == 200, str(r))
check("binding == 'auto' in response", r.get("binding") == "auto",
      f"binding key = '{r.get('binding')}'")
check("bound_item == Banana", r.get("bound_item") == "Banana",
      f"bound_item = '{r.get('bound_item')}'")
check("delta_g > 30", (r.get("delta_g") or 0) > 30,
      f"delta_g = {r.get('delta_g')}")

# ── Step 5: verify inventory updated ─────────────────────────
print(f"\n[5] Inventory after binding")
inv = get("/api/v1/inventory")
q3_after = next(i for i in inv if i["quadrant"] == TEST_QUADRANT)
print(f"  Q{TEST_QUADRANT} after:  {q3_after['item_name']}  {q3_after['weight_g']}g")
check("Q3 item_name is now Banana",
      q3_after["item_name"] == "Banana",
      f"got '{q3_after['item_name']}'")
check("Q3 weight updated",
      abs(q3_after["weight_g"] - new_weight) < 0.1,
      f"expected {new_weight}, got {q3_after['weight_g']}")

# ── Step 6: pending_scan cleared ─────────────────────────────
print("\n[6] Pending scan cleared after binding")
pending = get("/api/v1/pending-scan")
print(f"  Pending state: {pending}")
check("pending is False after bind", pending.get("pending") is False, str(pending))
check("item is None after bind",     pending.get("item") is None, str(pending))

# ── Summary ───────────────────────────────────────────────────
print()
print("=" * 58)
passed = 13 - len(failures)
print(f"  Results: {passed}/13 passed  |  {len(failures)} failed")
print("=" * 58)
if failures:
    print("\n  Failed:")
    for f in failures:
        print(f"    ✗ {f}")
else:
    print("\n  ✅ Delta-binding works end-to-end!")
    print("  The app CAN correctly tell which item is in which quadrant.")
