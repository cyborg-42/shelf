"""
main.py
Shelf AI-IoT Smart Shelf — FastAPI Backend
============================================
Vision pipeline: YOLOv8 Nano (pretrained COCO weights)
Weight telemetry: 4-quadrant HX711 load cells via ESP32
Analytics: SQLite + linear regression depletion forecasting
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import io
import asyncio
import numpy as np
from PIL import Image
import database

# ─── YOLOv8 setup ─────────────────────────────────────────────────────────────

try:
    from ultralytics import YOLO
    _yolo_available = True
except ImportError:
    _yolo_available = False
    print("[WARNING] ultralytics not installed. Run: pip install ultralytics")
    print("          Scan endpoint will return fallback response until installed.")

# COCO class names → our shelf produce labels
# Only these 5 classes trigger a positive detection; everything else is ignored.
COCO_TO_PRODUCE = {          # COCO only knows apple + orange; guava/pomegranate need the fruit-world model
    "apple":  "Apple",
    "orange": "Orange",
}

# Minimum YOLO confidence to accept a detection
CONF_THRESHOLD = 0.35
WORLD_IDENT_CONF = 0.10   # custom fruit model scores run lower than COCO

# Lazy-loaded at first request (avoids slow startup on the server)
yolo_model = None

def get_yolo():
    """Load yolov8n.pt on first call, then cache it."""
    global yolo_model
    if yolo_model is None and _yolo_available:
        print("[INFO] Loading YOLOv8n model (downloads ~6 MB on first run)...")
        yolo_model = YOLO("yolov8n.pt")
        print("[SUCCESS] YOLOv8n loaded.")
    return yolo_model


LAST_SCAN = {"count": 0}   # how many boxes of the winning item the newest scan found (read by scan_item)


def _run_yolo_sync(image: Image.Image):
    """
    Synchronous YOLO inference — runs in a thread pool via asyncio.
    Converts PIL Image to numpy array (what ultralytics actually expects).
    Returns (label, confidence_percent).
    """
    LAST_SCAN["count"] = 0          # filled in below when something is found
    world = _get_world()
    model = world or get_yolo()
    if model is None:
        return "No Produce Detected", 0.0
    label_of = {n.lower(): n.title() for n in world.names.values()} if world is not None else COCO_TO_PRODUCE
    seen = []

    # Convert PIL → numpy RGB array (HxWx3 uint8) — ultralytics native format
    img_array = np.array(image)

    results = model(img_array, conf=(WORLD_IDENT_CONF if world is not None else CONF_THRESHOLD), verbose=False)

    best_label = "No Produce Detected"
    best_conf  = 0.0

    for result in results:
        for box in result.boxes:
            coco_name = result.names[int(box.cls)].lower()
            seen.append((coco_name, round(float(box.conf), 2)))
            if coco_name in label_of:
                conf = float(box.conf)
                if conf > best_conf:
                    best_conf  = conf
                    best_label = label_of[coco_name]

    if best_label != "No Produce Detected":
        LAST_SCAN["count"] = sum(1 for _n, _c in seen if label_of.get(_n) == best_label)
    print("[YOLO] ident:", sorted(seen, key=lambda t: -t[1])[:5], "->", best_label)
    return best_label, round(best_conf * 100, 2)


async def run_yolo(image: Image.Image):
    """
    Async wrapper: offloads CPU-bound YOLO inference to a thread pool
    so the FastAPI event loop is never blocked.
    Other requests (weight updates, WebSocket pings) remain responsive
    during a scan even on slow CPU hardware.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_yolo_sync, image)


# ─── Delta-binding: pending scan buffer ───────────────────────────────────────
# Lifecycle:
#   Step 1 — User scans produce at the camera station → pending_scan is set
#   Step 2 — User places produce on a tray → ESP32 posts a weight increase
#   Step 3 — update-weight detects ΔW > 30g and pending_scan is set
#            → auto-binds the scanned item to that quadrant
#
# The buffer expires after PENDING_SCAN_TTL_SECONDS to prevent a stale scan
# from incorrectly binding to a weight change that happens much later.

import time as _time

PENDING_SCAN_TTL_SECONDS = 30   # scan must be placed within 30 s

pending_scan: dict = {
    "item":       None,    # e.g. "Banana"
    "confidence": 0.0,
    "timestamp":  None,    # _time.time() float
}

def _clear_pending():
    pending_scan["item"]       = None
    pending_scan["confidence"] = 0.0
    pending_scan["timestamp"]  = None

def _pending_is_valid() -> bool:
    """True if a scan is waiting and hasn't expired yet."""
    if pending_scan["item"] is None:
        return False
    age = _time.time() - (pending_scan["timestamp"] or 0)
    return age <= PENDING_SCAN_TTL_SECONDS


# ─── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Shelf AI-IoT Backend API",
    version="2.0.0",
    description="Smart shelf backend — YOLOv8 produce detection + HX711 weight telemetry",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── WebSocket connection manager ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ─── Pydantic request models ───────────────────────────────────────────────────

class WeightUpdatePayload(BaseModel):
    quadrant: int
    weight_grams: float

class SimulateScanPayload(BaseModel):
    label: str
    confidence: float


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup_event():
    database.create_tables()
    print("[SUCCESS] Shelf database initialised.")
    # Pre-warm YOLO so the first scan isn't slow
    if _yolo_available:
        get_yolo()


# ─── Core endpoints ───────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status":  "Online",
        "system":  "Shelf AI-IoT Smart Shelf Backend",
        "version": "2.0.0",
        "vision":  "YOLOv8n (COCO pretrained)",
        "endpoints": [
            "/api/v1/scan-item",
            "/api/v1/pending-scan",
            "/api/v1/inventory",
            "/api/v1/scans",
            "/api/v1/depletion-analytics",
            "/api/v1/update-weight",
            "/api/v1/simulate-scan",
        ],
    }

@app.get("/health")
def health_check():
    return {
        "status":       "healthy",
        "yolo_ready":   yolo_model is not None,
        "yolo_available": _yolo_available,
    }


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()   # keep-alive; we only push from server
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ─── Inventory & analytics ────────────────────────────────────────────────────

@app.get("/api/v1/inventory")
def get_inventory():
    return database.get_all_inventory()

@app.get("/api/v1/inventory/summary")
def get_inventory_summary():
    return database.get_inventory_summary()

@app.get("/api/v1/scans")
def get_recent_scans():
    return database.get_recent_scans()

import weight_loss_alert
app.include_router(weight_loss_alert.router)

@app.get("/api/v1/depletion-analytics")
def get_depletion_analytics():
    return database.get_depletion_analytics()


@app.get("/api/v1/freshness-alerts")
def get_freshness_alerts(force: bool = False):
    """Spoilage / untouched reminders (daytime only; force=true ignores the clock for testing)."""
    return database.get_freshness_alerts(force=force)


@app.get("/api/v1/shelf-life")
def get_shelf_life():
    """Per fruit: placed time, removed time (if any), days on shelf, predicted days until it goes bad."""
    return database.get_shelf_life()


@app.get("/api/v1/shelf-events")
def get_shelf_events(quadrant: int = 0, limit: int = 50):
    """Raw PLACED / REMOVED log (newest first). quadrant=0 means all."""
    return database.get_shelf_events(quadrant, limit)


# ─── Weight telemetry (ESP32 HX711) + delta-binding ──────────────────────────

# Minimum positive weight delta (grams) to treat as a new item placement.
# Filters out sensor noise and vibration.
DELTA_THRESHOLD_ADD    =  30.0   # +30 g → item placed
DELTA_THRESHOLD_REMOVE = -10.0   # -10 g → consumption / removal

# --- Shelf: depletion confirmation. An empty tray only becomes a STOCK_DEPLETED alert after it stays empty. ---
import os as _os, time as _time
DEPLETION_CONFIRM_S = float(_os.environ.get("DEPLETION_CONFIRM_S", "600"))   # 600 s = 10 min. For a demo: 20
_empty_since = {}


def _depletion_confirmed(q):
    """True once quadrant q has been continuously Depleted for DEPLETION_CONFIRM_S seconds."""
    now = _time.time()
    t0 = _empty_since.setdefault(str(q), now)
    return (now - t0) >= DEPLETION_CONFIRM_S


def _depletion_clear(q):
    _empty_since.pop(str(q), None)



@app.post("/api/v1/update-weight")
async def update_weight(payload: WeightUpdatePayload):
    """
    Receives weight telemetry from the ESP32 HX711 sensors.

    Delta-binding algorithm:
      Case 1 — ΔW > +30g AND pending scan exists (TTL valid)
               → auto-bind scanned item to this quadrant
      Case 2 — ΔW > +30g but NO pending scan
               → weight increased without a scan (manual placement or error)
                 just update the weight, keep existing item_name
      Case 3 — ΔW < -10g
               → consumption detected, update weight only

    All cases broadcast WEIGHT_UPDATE. Case 1 also broadcasts ITEM_BOUND.
    Zero weight broadcasts STOCK_DEPLETED.
    """
    if payload.quadrant not in [1, 2, 3, 4]:
        raise HTTPException(status_code=400, detail="Quadrant must be 1–4")

    # Read current state before updating
    current = database.get_quadrant(payload.quadrant)
    current_weight = current.get("weight_g", 0.0)
    delta = payload.weight_grams - current_weight

    bound_item = None  # set if delta-binding fires

    # ── Case 1: item placed after a scan ──────────────────────────────────────
    if delta >= DELTA_THRESHOLD_ADD and _pending_is_valid():
        bound_item = pending_scan["item"]
        scan_conf  = pending_scan["confidence"]
        result     = database.update_quadrant_item(
            payload.quadrant, bound_item, payload.weight_grams
        )
        _clear_pending()

        print(f"[BIND] 🎯 Auto-bound '{bound_item}' → Quadrant {payload.quadrant} "
              f"(ΔW={delta:+.0f}g, scan conf={scan_conf:.1f}%)")

        # Notify Flutter: item identity changed
        await manager.broadcast({
            "type":       "ITEM_BOUND",
            "quadrant":   payload.quadrant,
            "item_name":  bound_item,
            "weight_g":   payload.weight_grams,
            "confidence": scan_conf,
            "message":    f"{bound_item} placed on Quadrant {payload.quadrant}",
        })

    # ── Case 2 & 3: weight-only update ────────────────────────────────────────
    else:
        result = database.update_quadrant_weight(payload.quadrant, payload.weight_grams)
        if delta >= DELTA_THRESHOLD_ADD:
            print(f"[WEIGHT] Q{payload.quadrant} +{delta:.0f}g (no pending scan — "
                  f"keeping item '{result['item_name']}')")
        elif delta <= DELTA_THRESHOLD_REMOVE:
            print(f"[WEIGHT] Q{payload.quadrant} {delta:.0f}g consumption detected")

    status    = result["status"]
    item_name = result["item_name"]

    # Always broadcast the weight update so inventory UI refreshes
    await manager.broadcast({
        "type":      "WEIGHT_UPDATE",
        "quadrant":  payload.quadrant,
        "weight_g":  payload.weight_grams,
        "status":    status,
        "item_name": item_name,
    })

    # --- slow weight-loss alert (drying / spoilage warning) ---
    try:
        _loss = weight_loss_alert.check(payload.quadrant, item_name, payload.weight_grams)
        if _loss:
            print(f"[LOSS] {_loss['message']}")
            await manager.broadcast({
                "type":      "WEIGHT_LOSS_ALERT",
                "quadrant":  payload.quadrant,
                "item_name": item_name,
                **_loss,
            })
    except Exception as _e:
        print("[LOSS] check skipped:", _e)

    # Depletion alert when weight hits exactly zero
    if status != "Depleted":
        _depletion_clear(payload.quadrant)   # weight is back (or never hit 0): restart the wait next time
    if status == "Depleted" and _depletion_confirmed(payload.quadrant):
        await manager.broadcast({
            "type":      "STOCK_DEPLETED",
            "quadrant":  payload.quadrant,
            "item_name": item_name,
            "message":   f"{item_name} in Quadrant {payload.quadrant} is fully depleted. Please restock.",
        })

    response = {
        "status":           "success",
        "quadrant":         payload.quadrant,
        "updated_weight_g": payload.weight_grams,
        "delta_g":          round(delta, 1),
        "stock_status":     status,
        "item_name":        item_name,
    }
    if bound_item:
        response["bound_item"] = bound_item
        response["binding"]    = "auto"

    return response


# ─── Pending scan status (for Flutter UI) ─────────────────────────────────────

@app.get("/api/v1/pending-scan")
def get_pending_scan():
    """
    Returns the current pending scan buffer state.
    Flutter can poll this to show a 'Place on shelf now' prompt.
    """
    if _pending_is_valid():
        age = round(_time.time() - pending_scan["timestamp"], 1)
        return {
            "pending":    True,
            "item":       pending_scan["item"],
            "confidence": pending_scan["confidence"],
            "age_seconds": age,
            "ttl_seconds": PENDING_SCAN_TTL_SECONDS,
            "expires_in":  round(PENDING_SCAN_TTL_SECONDS - age, 1),
        }
    return {"pending": False, "item": None}


# ─── Simulate scan (testing / demo) ───────────────────────────────────────────

@app.post("/api/v1/simulate-scan")
async def simulate_scan(payload: SimulateScanPayload):
    # Same units as the real scan endpoint: confidence as a percentage.
    conf_pct = payload.confidence * 100 if payload.confidence <= 1 else payload.confidence

    database.log_scan_result(payload.label, conf_pct)

    # Open the 30 s pending buffer exactly like a real YOLO scan, so a demo
    # scan can bind to the next weight increase.
    pending_scan["item"]       = payload.label
    pending_scan["confidence"] = conf_pct
    pending_scan["timestamp"]  = _time.time()

    await manager.broadcast({
        "type":       "SCAN_UPDATE",
        "label":      payload.label,
        "confidence": conf_pct,
    })

    return {
        "status":        "success",
        "detected_item": payload.label,
        "confidence":    conf_pct,
    }

# ─── YOLOv8 scan endpoint ──────────────────────────────────────────────────────

# ─── Auto-scan with object count (probe / commit) ────────────────────────────

# Counting is more sensitive than identification, so touching / partly hidden pieces still count.
ID_CONF     = 0.25   # lowest confidence to NAME the fruit in a scan (was 0.35 - too strict for oranges)
COUNT_CONF  = 0.05   # lowest confidence a box needs to be COUNTED (identification still uses CONF_THRESHOLD)
COUNT_IOU   = 0.80   # NMS overlap limit: higher keeps touching/overlapping fruit as separate boxes
COUNT_IMGSZ = 800    # inference size (default 640); bigger = better on small/far fruit, a bit slower


# --- custom fruit model (YOLO-World, built by make_fruit_model.py) -------------------
_WORLD = None
_WORLD_TRIED = False


def _upright(buf):
    """Open an uploaded photo and obey its EXIF rotation flag (phone photos are often stored sideways)."""
    from PIL import Image as _I, ImageOps as _O
    return _O.exif_transpose(_I.open(buf)).convert("RGB")


def _get_world():
    """Loads backend/shelf_fruit_world.pt once. Returns None if it is missing (-> normal COCO model)."""
    global _WORLD, _WORLD_TRIED
    if _WORLD is not None or _WORLD_TRIED:
        return _WORLD
    _WORLD_TRIED = True
    try:
        from pathlib import Path as _P
        p = _P(__file__).parent / "shelf_fruit_world.pt"
        if p.exists():
            _det = p.with_name("shelf_detector.pt")
            if _det.exists():
                from ultralytics import YOLO
                _WORLD = YOLO(str(_det))
                globals()["_FT"] = True   # fine-tuned detector: it names the fruit itself
            else:
                from ultralytics import YOLOWorld
                _WORLD = YOLOWorld(str(p))
            print("[MODEL] fruit model loaded:", ", ".join(_WORLD.names.values()))
        else:
            print("[MODEL] shelf_fruit_world.pt not found - using the standard COCO model")
    except Exception as e:
        print("[MODEL] could not load fruit model, using COCO:", e)
        _WORLD = None
    return _WORLD


# --- Shelf: photo collection + fruit classifier ----------------------------------
import time as _t2
from pathlib import Path as _Path2

_DATASET = _Path2(__file__).parent / "dataset"
_collect = {"label": None, "last": 0.0}
_CLF = {"tried": False, "clip": None, "pre": None, "cent": None, "labels": None}


@app.get("/api/v1/collect")
def collect_mode(label: str = "off"):
    """Open in a browser: /api/v1/collect?label=guava  -> frames from the app are saved as guava photos."""
    label = "".join(ch for ch in label.lower() if ch.isalnum())
    if label in ("", "off", "stop"):
        _collect["label"] = None
        msg = "collect mode OFF"
    else:
        (_DATASET / label).mkdir(parents=True, exist_ok=True)
        _collect["label"] = label
        msg = "collecting frames as '" + label + "' (scan with the app now)"
    counts = {d.name: len(list(d.glob("*.jpg"))) for d in _DATASET.glob("*") if d.is_dir()} if _DATASET.exists() else {}
    return {"status": msg, "photos": counts}


def _collect_frame(image):
    lab = _collect["label"]
    if not lab:
        return
    now = _t2.time()
    if now - _collect["last"] < 0.6:      # at most ~1 photo per 0.6 s, so you get varied angles
        return
    _collect["last"] = now
    d = _DATASET / lab
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("*.jpg")))
    image.save(d / (str(int(now * 1000)) + ".jpg"), quality=90)
    print("[COLLECT]", lab + ":", n + 1, "photos")


def _load_clf():
    if _CLF["tried"]:
        return _CLF["cent"] is not None
    _CLF["tried"] = True
    try:
        import numpy as _np
        import clip as _clip
        f = _Path2(__file__).parent / "fruit_clf.npz"
        if not f.exists():
            print("[CLF] fruit_clf.npz not found - using the YOLO label")
            return False
        z = _np.load(f, allow_pickle=True)
        _CLF["cent"] = z["centroids"]
        _CLF["labels"] = [str(x) for x in z["labels"]]
        _CLF["clip"], _CLF["pre"] = _clip.load("ViT-B/32", device="cpu")
        _CLF["clip"].eval()
        print("[CLF] fruit classifier loaded:", ", ".join(_CLF["labels"]))
        return True
    except Exception as e:
        print("[CLF] could not load classifier:", e)
        _CLF["cent"] = None
        return False


def _refine_label(image, box, fallback):
    """Name the fruit inside a YOLO box with the classifier trained on your own photos."""
    import os as _os
    if globals().get("_FT") and not _os.environ.get("USE_CLIP"):
        return fallback   # fine-tuned detector already names the fruit
    if not _load_clf():
        return fallback
    try:
        import torch
        import numpy as _np
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
        w, h = x2 - x1, y2 - y1
        pad = 0.08
        crop = image.crop((max(0, int(x1 - pad * w)), max(0, int(y1 - pad * h)),
                           min(image.width, int(x2 + pad * w)), min(image.height, int(y2 + pad * h))))
        with torch.no_grad():
            e = _CLF["clip"].encode_image(_CLF["pre"](crop).unsqueeze(0)).float()
            e = e / e.norm(dim=-1, keepdim=True)
        sims = _CLF["cent"] @ e[0].numpy()
        return _CLF["labels"][int(_np.argmax(sims))].title()
    except Exception as ex:
        print("[CLF] error:", ex)
        return fallback


def _detect_counts(image):
    """Run YOLO once. Returns (best_label, best_conf_pct, count_of_best_label, counts_by_label, boxes)."""
    world = _get_world()
    model = world or get_yolo() or globals().get("yolo_model")
    label_of = {n.lower(): n.title() for n in world.names.values()} if world is not None else COCO_TO_PRODUCE
    if model is None:
        return "No Produce Detected", 0.0, 0, {}, []
    import numpy as np
    _collect_frame(image)
    results = model(np.array(image), conf=COUNT_CONF, iou=COUNT_IOU, imgsz=COUNT_IMGSZ, verbose=False)
    boxes = []
    seen = []
    for result in results:
        for box in result.boxes:
            coco_name = result.names[int(box.cls)].lower()
            seen.append(f"{coco_name} {float(box.conf) * 100:.0f}%")
            if coco_name not in label_of:
                continue
            boxes.append({"label": _refine_label(image, box, label_of[coco_name]), "conf": round(float(box.conf) * 100, 1)})
    print("[YOLO] raw:", ", ".join(seen) if seen else "nothing at all")
    if boxes:
        print("[COUNT] boxes:", ", ".join(f"{b['label']} {b['conf']}%" for b in boxes))
    # identification: the best box must clear the normal threshold
    strong = [b for b in boxes if b["conf"] >= ID_CONF * 100]
    if not strong:
        return "No Produce Detected", 0.0, 0, {}, boxes
    best = max(strong, key=lambda b: b["conf"])
    counts = {}
    for b in boxes:
        counts[b["label"]] = counts.get(b["label"], 0) + 1
    return best["label"], best["conf"], counts[best["label"]], counts, boxes


@app.post("/api/v1/scan-auto")
async def scan_auto(file: UploadFile = File(...), commit: bool = False):
    """
    Detect produce AND count how many of the best-matching fruit are in the frame.
    commit=false : probe only (used every ~1 s by the app's auto-scan; changes nothing).
    commit=true  : if produce found -> open 30 s pending buffer, log, broadcast SCAN_UPDATE.
    """
    try:
        import asyncio
        contents = await file.read()
        image    = _upright(io.BytesIO(contents))

        loop = asyncio.get_running_loop()
        label, confidence, count, counts, boxes = await loop.run_in_executor(None, _detect_counts, image)
        found = label != "No Produce Detected"
        committed = False

        if commit and found:
            pending_scan["item"]       = label
            pending_scan["confidence"] = confidence
            pending_scan["count"]      = count
            pending_scan["timestamp"]  = _time.time()
            print(f"[SCAN] Detected {count} x {label} ({confidence:.1f}%) - "
                  f"waiting for shelf placement (TTL {PENDING_SCAN_TTL_SECONDS}s)")
            database.log_scan_result(label, confidence)
            await manager.broadcast({
                "type":       "SCAN_UPDATE",
                "label":      label,
                "confidence": confidence,
                "count":      count,
                "counts":     counts,
            })
            committed = True

        return {
            "success":       True,
            "detected_item": label,
            "confidence":    confidence,
            "count":         count,
            "counts":        counts,
            "boxes": boxes,
            "committed":     committed,
            "pending_bind":  committed,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Assign a scanned item to a quadrant (the app's "Add" button) ------------------
from pydantic import BaseModel as _AssignBase


class AssignItemPayload(_AssignBase):
    quadrant: int
    item_name: str
    confidence: float = 0.0
    count: int = 0


@app.post("/api/v1/assign-item")
async def assign_item(payload: AssignItemPayload):
    """
    Write a scanned item's NAME onto a quadrant right now.
    The weight/status stay exactly what the load cell last reported.
    """
    from datetime import datetime

    q = int(payload.quadrant)
    name = payload.item_name.strip()
    if q not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="quadrant must be 1-4")
    if not name:
        raise HTTPException(status_code=400, detail="item_name is empty")

    conn = database.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT weight_g, status FROM inventory WHERE quadrant = ?", (q,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"quadrant {q} not found")
        weight_g, stock_status = row[0], row[1]
        cur.execute(
            "UPDATE inventory SET item_name = ?, last_updated = ? WHERE quadrant = ?",
            (name, datetime.now().strftime("%I:%M %p"), q),
        )
        conn.commit()
    finally:
        conn.close()

    # the Add button names the fruit after it was placed: fix the name on the open shelf stay
    try:
        database.shelf_rename(q, name)
    except Exception as e:
        print("[SHELF] rename failed:", e)

    # the manual Add replaces the 30 s auto-bind window
    try:
        _clear_pending()
    except Exception:
        pass
    try:
        database.log_scan_result(name, payload.confidence)
    except Exception as e:
        print("[ASSIGN] could not log scan:", e)

    print(f"[ASSIGN] {name} -> Quadrant {q} ({weight_g} g, {stock_status})")
    msg = f"{name} added to Quadrant {q}"
    await manager.broadcast({
        "type": "ITEM_BOUND", "quadrant": q, "item_name": name,
        "weight_g": weight_g, "confidence": payload.confidence, "message": msg,
    })
    await manager.broadcast({
        "type": "WEIGHT_UPDATE", "quadrant": q, "weight_g": weight_g,
        "status": stock_status, "item_name": name,
    })
    await manager.broadcast({
        "type": "SCAN_UPDATE", "label": name, "confidence": float(payload.confidence),
        "count": payload.count,
    })
    return {"success": True, "quadrant": q, "item_name": name,
            "weight_g": weight_g, "stock_status": stock_status}


@app.post("/api/v1/scan-item")
async def scan_item(file: UploadFile = File(...)):
    """
    Accepts a JPEG/PNG image from the phone camera or ESP32-CAM.

    Pipeline:
      1. Decode image → YOLOv8n (conf=0.35)
      2. If produce detected → store in pending_scan buffer (TTL 30 s)
         The next weight increase >30 g on any quadrant auto-binds it.
      3. Log + broadcast SCAN_UPDATE regardless of detection result.

    Response: {"success": true, "detected_item": "Banana", "confidence": "94.2%"}
    """
    try:
        contents = await file.read()
        image    = _upright(io.BytesIO(contents))

        label, confidence = await run_yolo(image)
        count = LAST_SCAN["count"]

        # Set pending buffer so update-weight can bind this item to a quadrant
        if label != "No Produce Detected":
            pending_scan["item"]       = label
            pending_scan["confidence"] = confidence
            pending_scan["timestamp"]  = _time.time()
            print(f"[SCAN] Detected {label} ({confidence:.1f}%) — "
                  f"waiting for shelf placement (TTL {PENDING_SCAN_TTL_SECONDS}s)")
        else:
            # No produce found — clear any stale pending entry
            _clear_pending()

        database.log_scan_result(label, confidence)

        await manager.broadcast({
            "type":       "SCAN_UPDATE",
            "label":      label,
            "count":      count,
            "confidence": confidence,
        })

        return {
            "success":        True,
            "detected_item":  label,
            "count":          count,
            "confidence":     f"{confidence:.1f}%",
            "pending_bind":   label != "No Produce Detected",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
