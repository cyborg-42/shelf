=====================================================================
 SHELF - AI-IoT Hybrid Framework for Grocery Inventory Management
          and Consumption Forecasting
=====================================================================

College     : Canara Engineering College, Benjanapadavu, Mangaluru - 574219
University  : Visvesvaraya Technological University (VTU), Belagavi
Department  : Artificial Intelligence and Machine Learning
Degree      : Bachelor of Engineering (B.E.)
Academic Yr : 2026-27

---------------------------------------------------------------------
 TEAM MEMBERS
---------------------------------------------------------------------
 Name               USN
 -----------------  ------------
 Srujan             4CB23AI110
 Srujan Bhandary    4CB23AI111
 Sujan              4CB23AI115

 Project Guide      : Dr. Praahas Amin (Associate Professor, AIML)
 Project Co-Guide   : Dr. Siju V Soman
 Head of Department : Dr. Basappa B Kodada

---------------------------------------------------------------------
 ABOUT THE PROJECT
---------------------------------------------------------------------
Shelf is a low-cost smart shelf for loose fruits and vegetables. It
tells you WHAT an item is, WHERE it is on the shelf, HOW MUCH is left,
and WHEN it will run out.

 - A phone camera + YOLOv8n detector identifies the produce item.
 - A 4-quadrant shelf (4 load cells + 4 HX711 + 1 ESP32) weighs each
   quadrant.
 - Delta-binding: a confirmed scan opens a 30 s window; the next weight
   rise of 30 g or more binds the item to that quadrant. A fall of
   10 g or more is logged as consumption.
 - A least-squares fit on the latest 20 weight readings forecasts the
   days remaining.
 - A Flutter app shows live stock, forecast and status, and sends
   Low Stock / Restock notifications.
 - Everything runs on a local network. No cloud service is needed.

---------------------------------------------------------------------
 TECH STACK
---------------------------------------------------------------------
 Backend   : Python, FastAPI, Uvicorn, SQLite, WebSocket
 Vision    : Ultralytics YOLOv8n (fine-tuned), CLIP classifier
 Mobile    : Flutter (Dart), Android
 Hardware  : ESP32, HX711 x4, 5 kg load cells x4
 Firmware  : Arduino core for ESP32 (C++)

---------------------------------------------------------------------
 FOLDER STRUCTURE
---------------------------------------------------------------------
 backend/              FastAPI server, detector, delta-binding, tests
 shelf_app/            Flutter mobile app
 esp32_weight_scale/   ESP32 firmware and calibration sketches
 README.md             Detailed project README
 GOAL.md               Project goal and success criteria

 Note: model weights (*.pt), the dataset and the local database are
 NOT stored in the repository. Keep them on the local machine.

---------------------------------------------------------------------
 HOW TO RUN
---------------------------------------------------------------------
 1) Backend
      cd backend
      pip install fastapi uvicorn python-multipart ultralytics
      uvicorn main:app --host 0.0.0.0 --port 8000
    API docs: http://127.0.0.1:8000/docs

 2) Mobile app
      cd shelf_app
      flutter pub get
      flutter run
    For a real phone, set serverIp in lib/services/api_service.dart
    to the PC's IP address (phone and PC on the same Wi-Fi).

 3) ESP32 firmware
    Open esp32_weight_scale/WeightScale_4Quad.ino, set WIFI_SSID,
    WIFI_PASSWORD and SERVER_IP, calibrate each quadrant, then flash.
    Use a 2.4 GHz Wi-Fi network.

 4) Tests (server must be running)
      python smoke_test.py
      python test_binding.py

---------------------------------------------------------------------
 SDG MAPPING
---------------------------------------------------------------------
 SDG 2 - Zero Hunger
 SDG 3 - Good Health and Well-being

---------------------------------------------------------------------
 REPOSITORY
---------------------------------------------------------------------
 https://github.com/cyborg-42/shelf
=====================================================================
