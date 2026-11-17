# Shelf — AI-IoT Smart Shelf System

Shelf is an AI-IoT smart shelf that tracks grocery/produce inventory
automatically, without manual entry. A 4-quadrant shelf fuses a camera-based
object detector with per-quadrant load cells: scan an item with the phone
camera, set it down, and the backend figures out which quadrant it landed on
by watching the weight change — no manual quadrant selection.

See `GOAL.md` for the full project vision and success criteria (frozen), and
`SHELF_MASTER_DOCUMENT.md` for the detailed architecture blueprint.

## How it works — the delta-binding pipeline

1. The Flutter app's **Scan** screen sends a photo to the backend's
   `/api/v1/scan-item` endpoint.
2. The backend runs it through a **YOLOv8n** object-detection model
   (`ultralytics`), restricted to the 4 supported produce classes: Apple,
   Banana, Orange, Carrot.
3. A confident detection opens a short **pending-scan window** (30 seconds).
4. Four ESP32-driven **HX711 load cells** (one per quadrant) continuously
   report weight to `/api/v1/update-weight`. If a quadrant's weight
   *increases* while a scan is pending, the backend auto-binds that item to
   that quadrant — no manual quadrant picking.
5. A weight *decrease* on an already-bound quadrant is read as consumption,
   and the quadrant's stock status (Available / Low Stock / Critical /
   Depleted) updates accordingly.
6. All of this is broadcast live over WebSocket to the Flutter app, which
   shows the 4-quadrant inventory view, scan history, stock alerts, and a
   depletion forecast (estimated days remaining) computed from real logged
   weight history.

## Project Structure

- `backend/` — FastAPI server (SQLite-backed), YOLOv8n detection, delta-binding
  logic, WebSocket broadcast. `main.py` is the real backend; `database.py`
  holds the SQLite access layer.
- `backend/dataset/` — real produce photos used by the end-to-end binding
  tests (`test_binding.py`). Currently only `Banana/` is populated.
- `shelf_app/` — Flutter mobile app: Scan / Home / Inventory / Analytics
  screens, live WebSocket updates.
- `esp32_weight_scale/` — ESP32 firmware. `WeightScale_4Quad.ino` is the
  current 4-quadrant firmware (shared clock line, 1 HX711 per quadrant); the
  other `.ino` files in that folder are earlier single-cell calibration
  sketches, kept for reference.
- `archive/` — retired test files from an earlier color-based mock-detection
  approach (pre-YOLO), kept locally for reference and gitignored.

## Backend Setup (FastAPI)

### Prerequisites
- Python 3.8+ (the project's own `.venv` targets 3.13)
- pip

### Installation
```bash
cd backend
pip install fastapi uvicorn python-multipart ultralytics
```

`ultralytics` pulls in `torch` and `opencv-python`, which are large — if pip
seems to hang "resolving dependencies" while installing, install
`matplotlib` on its own first (`pip install "matplotlib>=3.3.0" --prefer-binary`),
then retry; this avoids a slow backtracking resolution.

### Running the Server
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

The server will be available at:
- Local: http://127.0.0.1:8000
- For Android Emulator: `10.0.2.2:8000` (handled automatically by the Flutter app)
- For a physical Android device on the same Wi-Fi network: your machine's LAN
  IP (see `ipconfig` / `ifconfig`) — update `serverIp` in
  `shelf_app/lib/services/api_service.dart` to match.

### API Documentation
Once the server is running, visit:
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

### Backend tests
- `smoke_test.py` — API-level smoke test against a *live* server (health,
  inventory, weight updates, scan simulation, delta-binding wiring). Run
  `uvicorn` in one terminal, then `python smoke_test.py` in another.
- `test_binding.py` — full end-to-end delta-binding test using a real banana
  photo from `dataset/Banana/`: scan → pending-scan buffer → simulated
  weight placement on Q3 → verifies the backend auto-binds it.
- `find_detectable_banana.py` / `find_detectable_generic.py <ClassName>` —
  utility scripts that scan a dataset folder against a live server and report
  which photos YOLO actually detects above the confidence threshold, so you
  can pick a reliable test image.

## Frontend Setup (Flutter)

### Prerequisites
- Flutter SDK (3.0.0+), Dart SDK
- Android Studio or VS Code with Flutter extensions
- An Android emulator or physical Android device for camera-based scanning

### Getting Dependencies
```bash
cd shelf_app
flutter pub get
```

### Running the App
```bash
flutter run                 # emulator or connected physical device
flutter run -d chrome       # web
flutter run -d windows      # Windows desktop
```

Camera-based scanning requires a device with a camera — the emulator's
virtual camera works for a quick check, but a physical Android phone is
recommended for a real demo.

### Backend Connection
The app picks its backend URL automatically:
- `http://10.0.2.2:8000` on the Android emulator (alias to the host's
  localhost)
- `http://127.0.0.1:8000` on Web or Desktop

For a physical Android device on Wi-Fi, update the `serverIp` constant in
`lib/services/api_service.dart` to your development machine's LAN IP, and
make sure both devices are on the same network.

## ESP32 Firmware

`esp32_weight_scale/WeightScale_4Quad.ino` drives all 4 HX711 load cells
(shared clock pin, one data pin per quadrant) and POSTs weight deltas to the
backend's `/api/v1/update-weight` endpoint. Before flashing:

1. Set `WIFI_SSID` / `WIFI_PASSWORD` to your network credentials.
2. Set `SERVER_IP` to your backend machine's current LAN IP (this drifts
   whenever you change networks — re-check with `ipconfig`/`ifconfig` before
   a demo).
3. Flash, open the Serial Monitor at 115200 baud, and tare all 4 scales with
   trays empty.
4. Calibrate each quadrant's `CALIBRATION_FACTORS` with a known weight if
   readings drift from expected.

## Demo Walkthrough

1. Start the backend: `cd backend && uvicorn main:app --reload`
2. Start the Flutter app on a physical device (recommended) or emulator:
   `cd shelf_app && flutter run`
3. Power on the ESP32 shelf hardware, confirm it's connected to the backend
   (watch the FastAPI console for `[WEIGHT]` / `[BIND]` log lines).
4. In the app: go to **Scan**, photograph a real produce item (Apple, Banana,
   Orange, or Carrot), then place it on its shelf quadrant within 30 seconds.
5. Watch the **Home** screen update live via WebSocket — no manual refresh —
   as the item binds to its quadrant.
6. Remove/consume the item and watch the weight and stock status
   (Available / Low Stock / Critical / Depleted) update.
7. Check **Analytics** for the depletion forecast (estimated days remaining),
   computed from real logged weight history.

## Known Gaps / Current State

- Only `dataset/Banana/` has real photos, so the automated end-to-end
  binding test (`test_binding.py`) currently only exercises Banana. The same
  test pattern needs to be repeated for Apple, Orange, and Carrot once photos
  of those items are captured.
- The ESP32 firmware and the full physical integration test (camera + scale
  + app running together) have not yet been verified on real hardware in
  this environment.

## Troubleshooting

- **Backend Connection Issues**: Ensure the backend is running and reachable
  from the device/emulator (same Wi-Fi network, correct `serverIp`, firewall
  allows inbound on port 8000).
- **Port Already in Use**: Change the port in the `uvicorn` command and
  update `baseUrl` in `api_service.dart` accordingly.
- **Flutter Build Issues**: `flutter clean && flutter pub get`.
- **`ultralytics` import errors**: Confirm it installed into the same Python
  environment `uvicorn` is running from (check with
  `python -c "import ultralytics"`).

---
*Shelf — AI-IoT Smart Shelf Monitor*
