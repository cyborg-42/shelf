/*
  LoadCell_Live.ino  -  see the weight on your load cells, live, and see every CHANGE as it happens.
  (bring-up / test sketch: NO Wi-Fi, NO server. Use it to check wiring + calibrate. Then flash Shelf_Shelf.ino.)

  WIRING (same as the final shelf)         Q1 = DOUT -> GPIO19     Q2 -> GPIO21    Q3 -> GPIO22    Q4 -> GPIO23
    every HX711:  SCK/CLK -> GPIO18 (shared),  VCC -> 3V3,  GND -> GND
    only have ONE HX711 wired so far?  Leave ENABLED = {true,false,false,false} below. Wired two? set the 2nd to true.

  ARDUINO IDE:  Board "ESP32 Dev Module"   Serial Monitor: 115200 baud, line ending "Newline"   No libraries needed.

  FIRST TIME (do these in the Serial Monitor, one at a time):
     1. empty tray ........................ type:  tare
     2. put a KNOWN weight on that tray ... type:  cal 1 500      (cell number, weight in grams - a 500 g..2 kg weight is best)
     3. take it off / put it on ........... the line should show ~0 g and ~500 g. Done - it is saved in the ESP32.
  Calibration is saved with the same keys as Shelf_Shelf.ino, so you do not need to redo it there.

  WHAT YOU SEE
     Q1   181.2 g  still      <- every half second: current weight, and whether it is moving or still
     >>> Q1  +181.0 g  PLACED   (now 181.2 g)    <- printed ONCE each time the weight changes by 5 g or more and settles
  Type  plot  to get numbers the Arduino "Serial Plotter" can draw as a live graph.
*/
#include <Preferences.h>

// =============================== EDIT THESE ===============================
const uint8_t PIN_CLK     = 18;
const uint8_t PIN_DOUT[4] = {19, 21, 22, 23};          // Q1..Q4
bool ENABLED[4]           = {true, false, false, false}; // set true for every HX711 you have wired
const uint32_t SAMPLE_MS  = 100;       // HX711 gives 10 readings per second
const uint32_t PRINT_MS   = 500;       // how often the live line prints
const float STABLE_TOL_G  = 3.0f;      // last 8 readings agree within 3 g  -> "still"
const float EVENT_MIN_G   = 5.0f;      // report a change only if it is at least 5 g
const int   CAL_SAMPLES   = 20;        // readings averaged for tare / cal (~2 s)
// ==========================================================================

static portMUX_TYPE hxMux = portMUX_INITIALIZER_UNLOCKED;

class HX711Multi {                      // reads every ENABLED chip at once (shared clock)
public:
  void begin() {
    pinMode(PIN_CLK, OUTPUT); digitalWrite(PIN_CLK, LOW);
    for (int i = 0; i < 4; i++) pinMode(PIN_DOUT[i], INPUT);
  }
  bool readEnabled(int32_t out[4], uint32_t timeoutMs = 300) {
    uint32_t t0 = millis();
    while (!ready()) { if (millis() - t0 > timeoutMs) return false; delay(1); }
    uint32_t v[4] = {0, 0, 0, 0};
    portENTER_CRITICAL(&hxMux);
    for (int b = 0; b < 24; b++) {
      digitalWrite(PIN_CLK, HIGH); delayMicroseconds(1);
      for (int i = 0; i < 4; i++) if (ENABLED[i]) v[i] = (v[i] << 1) | (digitalRead(PIN_DOUT[i]) ? 1u : 0u);
      digitalWrite(PIN_CLK, LOW);  delayMicroseconds(1);
    }
    digitalWrite(PIN_CLK, HIGH); delayMicroseconds(1);     // 25th pulse: next reading = channel A, gain 128
    digitalWrite(PIN_CLK, LOW);
    portEXIT_CRITICAL(&hxMux);
    for (int i = 0; i < 4; i++) { if (v[i] & 0x800000u) v[i] |= 0xFF000000u; out[i] = (int32_t)v[i]; }
    return true;
  }
private:
  bool ready() {
    bool any = false;
    for (int i = 0; i < 4; i++) if (ENABLED[i]) { any = true; if (digitalRead(PIN_DOUT[i])) return false; }
    return any;
  }
};

// follows one quadrant: smooth value, still/moving, and "a change just happened"
struct Tracker {
  static const int W = 8;
  float buf[W]; int head = 0, count = 0; float baseline = 0; bool have = false;
  void reset() { head = 0; count = 0; have = false; }
  // returns true when a settled change >= EVENT_MIN_G happened; fills delta + now
  bool push(float g, bool &still, float &now, float &delta) {
    buf[head] = g; head = (head + 1) % W; if (count < W) count++;
    float lo = buf[0], hi = buf[0], s = 0;
    for (int i = 0; i < count; i++) { if (buf[i] < lo) lo = buf[i]; if (buf[i] > hi) hi = buf[i]; s += buf[i]; }
    now = s / count;
    still = (count == W) && ((hi - lo) <= STABLE_TOL_G);
    if (!still) return false;
    if (!have) { baseline = now; have = true; return false; }
    if (fabsf(now - baseline) >= EVENT_MIN_G) { delta = now - baseline; baseline = now; return true; }
    return false;
  }
};

HX711Multi hx;
Tracker    trk[4];
Preferences prefs;
float zeroRaw[4] = {0, 0, 0, 0}, scaleCpg[4] = {1, 1, 1, 1};
bool  calibrated[4] = {false, false, false, false}, tared[4] = {false, false, false, false};
bool  plotMode = false, rawMode = false;
char  cmd[64]; int cmdLen = 0;
uint32_t nextSample = 0, nextPrint = 0;
float lastNow[4] = {0, 0, 0, 0}; bool lastStill[4] = {false, false, false, false};
int32_t lastRaw[4] = {0, 0, 0, 0};
bool gotReading = false; uint32_t lastGoodMs = 0;

float toGrams(int q, int32_t raw) { return ((float)raw - zeroRaw[q]) / scaleCpg[q]; }

void saveQ(int q) {                       // same keys as Shelf_Shelf.ino
  char k[8];
  snprintf(k, sizeof k, "z%d", q);  prefs.putFloat(k, zeroRaw[q]);
  snprintf(k, sizeof k, "s%d", q);  prefs.putFloat(k, scaleCpg[q]);
  snprintf(k, sizeof k, "ok%d", q); prefs.putBool(k, calibrated[q]);
  snprintf(k, sizeof k, "t%d", q);  prefs.putBool(k, tared[q]);
}
void loadAll() {
  for (int q = 0; q < 4; q++) {
    char k[8];
    snprintf(k, sizeof k, "z%d", q);  zeroRaw[q]  = prefs.getFloat(k, 0);
    snprintf(k, sizeof k, "s%d", q);  scaleCpg[q] = prefs.getFloat(k, 1);
    snprintf(k, sizeof k, "ok%d", q); calibrated[q] = prefs.getBool(k, false);
    snprintf(k, sizeof k, "t%d", q);  tared[q] = prefs.getBool(k, false);
    if (scaleCpg[q] == 0) { scaleCpg[q] = 1; calibrated[q] = false; }
  }
}
void showCal() {
  Serial.println("---- saved calibration ----");
  for (int q = 0; q < 4; q++)
    Serial.printf("Q%d  %s  zero=%.0f  scale=%.2f counts/g  %s\n", q + 1, ENABLED[q] ? "(enabled) " : "(disabled)", zeroRaw[q], scaleCpg[q],
                  calibrated[q] ? "CALIBRATED" : (tared[q] ? "tared - now type: cal <q> <grams>" : "not set up"));
}
bool avgRaw(float out[4], int n) {
  double s[4] = {0, 0, 0, 0}; int got = 0, tries = 0;
  while (got < n && tries < n * 4) {
    int32_t r[4]; tries++;
    if (hx.readEnabled(r)) { for (int i = 0; i < 4; i++) s[i] += r[i]; got++; }
  }
  if (got < n / 2) return false;
  for (int i = 0; i < 4; i++) out[i] = (float)(s[i] / got);
  return true;
}
void help() {
  Serial.println("Commands (type, press Enter):");
  Serial.println("  tare          empty trays = 0 g (all enabled cells)      tare 2 = only Q2");
  Serial.println("  cal 1 500     put a KNOWN weight (grams) on Q1's tray, then type this");
  Serial.println("  show          saved calibration        raw  toggle raw counts (wiring check)");
  Serial.println("  plot          toggle numbers for Serial Plotter           reset  erase calibration");
}
void doTare(int only) {
  float a[4];
  if (!avgRaw(a, CAL_SAMPLES)) { Serial.println("TARE FAILED: no HX711 answered. Check VCC/GND/CLK/DOUT wiring and ENABLED[]."); return; }
  for (int q = 0; q < 4; q++) if (ENABLED[q] && (only < 0 || only == q)) { zeroRaw[q] = a[q]; tared[q] = true; saveQ(q); trk[q].reset(); Serial.printf("Q%d zero set (%.0f)%s\n", q + 1, a[q], calibrated[q] ? "" : "  -> now: cal " "<q> <grams>"); }
}
void doCal(int q, float known) {
  if (!ENABLED[q]) { Serial.printf("Q%d is disabled in ENABLED[] (top of the sketch).\n", q + 1); return; }
  if (!tared[q]) { Serial.printf("Q%d has no zero yet. Empty the tray and type: tare\n", q + 1); return; }
  if (known < 50) { Serial.println("Use a known weight of at least 50 g (500 g to 2 kg is best)."); return; }
  float a[4];
  if (!avgRaw(a, CAL_SAMPLES)) { Serial.println("CAL FAILED: HX711 not responding."); return; }
  float diff = a[q] - zeroRaw[q];
  if (fabsf(diff) < 2000) { Serial.printf("Q%d barely changed (%.0f counts). Is the weight on Q%d's tray, and did you tare first?\n", q + 1, diff, q + 1); return; }
  scaleCpg[q] = diff / known; calibrated[q] = true; saveQ(q); trk[q].reset();
  Serial.printf("Q%d calibrated: %.2f counts/g%s\n", q + 1, scaleCpg[q], diff < 0 ? "  (negative = A+/A- swapped; handled)" : "");
  float mag = fabsf(scaleCpg[q]);
  if (mag < 50 || mag > 1500) Serial.println("  WARNING: expected roughly 100-500 counts/g. Check wiring and that the weight is on the free end.");
  Serial.println("  Now take the weight off and on again: you should see ~0 g and ~the known weight.");
}
void handleCmd(char* s) {
  int q = 0; float g = 0;
  if (!strcmp(s, "help") || !strcmp(s, "?")) help();
  else if (!strcmp(s, "tare")) doTare(-1);
  else if (sscanf(s, "tare %d", &q) == 1 && q >= 1 && q <= 4) doTare(q - 1);
  else if (sscanf(s, "cal %d %f", &q, &g) == 2 && q >= 1 && q <= 4) doCal(q - 1, g);
  else if (!strcmp(s, "show")) showCal();
  else if (!strcmp(s, "plot")) { plotMode = !plotMode; Serial.println(plotMode ? "plot ON (open Tools > Serial Plotter)" : "plot OFF"); }
  else if (!strcmp(s, "raw")) { rawMode = !rawMode; Serial.println(rawMode ? "raw ON" : "raw OFF"); }
  else if (!strcmp(s, "reset")) { prefs.clear(); for (int i = 0; i < 4; i++) { zeroRaw[i] = 0; scaleCpg[i] = 1; calibrated[i] = false; tared[i] = false; trk[i].reset(); } Serial.println("Calibration erased."); }
  else if (s[0]) Serial.println("Unknown command. Type: help");
}
void pollSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') { cmd[cmdLen] = 0; handleCmd(cmd); cmdLen = 0; }
    else if (cmdLen < (int)sizeof(cmd) - 1) cmd[cmdLen++] = (char)tolower(c);
  }
}

void setup() {
  Serial.begin(115200); delay(300);
  Serial.println("\n=== LoadCell_Live ===");
  hx.begin();
  prefs.begin("shelf", false);
  loadAll();
  showCal();
  help();
  bool anyCal = false; for (int q = 0; q < 4; q++) if (ENABLED[q] && calibrated[q]) anyCal = true;
  if (!anyCal) Serial.println("\nNot calibrated yet: empty the tray, type  tare , then put a known weight on and type  cal 1 500");
}

void loop() {
  pollSerial();
  uint32_t now = millis();
  if (now >= nextSample) {
    nextSample = now + SAMPLE_MS;
    int32_t r[4];
    if (hx.readEnabled(r)) {
      gotReading = true; lastGoodMs = now;
      for (int q = 0; q < 4; q++) {
        if (!ENABLED[q]) continue;
        lastRaw[q] = r[q];
        if (!calibrated[q]) continue;
        bool still; float cur, delta = 0;
        float g = toGrams(q, r[q]);
        bool ev = trk[q].push(g, still, cur, delta);
        lastNow[q] = cur; lastStill[q] = still;
        if (ev) Serial.printf(">>> Q%d  %+.1f g  %s   (now %.1f g)%s\n", q + 1, delta, delta > 0 ? "PLACED / ADDED" : "REMOVED",
                              cur, delta >= 30 ? "   [backend would bind a scanned fruit here]" : "");
      }
    }
  }
  if (now >= nextPrint) {
    nextPrint = now + PRINT_MS;
    if (!gotReading || now - lastGoodMs > 1500) { Serial.println("No data from the HX711 (check wiring: VCC 3V3, GND, SCK->GPIO18, DOUT->GPIO19 for Q1)."); return; }
    bool first = true;
    for (int q = 0; q < 4; q++) {
      if (!ENABLED[q]) continue;
      if (plotMode) { if (calibrated[q]) { Serial.printf("%sQ%d:%.1f", first ? "" : ",", q + 1, lastNow[q]); first = false; } continue; }
      if (!first) Serial.print("  |  "); first = false;
      if (!calibrated[q]) Serial.printf("Q%d raw %ld (needs: tare, cal)", q + 1, (long)lastRaw[q]);
      else if (rawMode) Serial.printf("Q%d %7.1f g  raw %ld  %s", q + 1, lastNow[q], (long)lastRaw[q], lastStill[q] ? "still" : "moving");
      else Serial.printf("Q%d %7.1f g  %s", q + 1, lastNow[q], lastStill[q] ? "still" : "moving");
    }
    if (!first) Serial.println();
  }
}
