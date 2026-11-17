#include "HX711.h"
HX711 scale;

void setup() {
  Serial.begin(115200);
  scale.begin(23, 18);   // DT = G23, SCK = G18
}

void loop() {
  if (scale.is_ready()) {
    Serial.println(scale.read());
  } else {
    Serial.println("HX711 not found");
  }
  delay(200);
}