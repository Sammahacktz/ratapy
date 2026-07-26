// Standalone DS18B20 hardware probe -- NOT part of RATA. Flash it, open the
// serial monitor at 115200, and it scans a set of pins for a 1-Wire device and
// prints how many it finds plus the temperature. This isolates "is the sensor
// wired correctly?" from "is RATA's firmware correct?".
//
//   ./firmware/flash.sh --fqbn arduino:avr:mega --port /dev/ttyUSB0 firmware/ds18b20_probe
//   (then read the serial output)
//
// Restore RATA afterwards:  ./firmware/flash.sh --board mega
#include <OneWire.h>
#include <DallasTemperature.h>

// Scan the whole Mega digital range, so a wrong-pin wiring shows up too.
uint8_t PINS[52];
uint8_t N = 0;
void buildPins() { for (uint8_t p = 2; p <= 53; p++) PINS[N++] = p; }

void scan(uint8_t pin) {
  OneWire wire(pin);
  DallasTemperature sensors(&wire);
  sensors.begin();
  uint8_t count = sensors.getDeviceCount();
  if (count == 0) return;                 // only print pins that FIND something
  Serial.print("pin ");
  Serial.print(pin);
  Serial.print(": ");
  Serial.print(count);
  Serial.println(" device(s) on the 1-Wire bus");

  DeviceAddress addr;
  for (uint8_t i = 0; i < count; i++) {
    if (!sensors.getAddress(addr, i)) continue;
    Serial.print("   [");
    Serial.print(i);
    Serial.print("] addr ");
    for (uint8_t j = 0; j < 8; j++) {
      if (addr[j] < 16) Serial.print('0');
      Serial.print(addr[j], HEX);
    }
    Serial.print("  family=0x");
    Serial.print(addr[0], HEX);           // 0x28 == DS18B20
    Serial.println();
  }
  sensors.requestTemperatures();          // blocking here -- fine for a probe
  for (uint8_t i = 0; i < count; i++) {
    float c = sensors.getTempCByIndex(i);
    Serial.print("   temp[");
    Serial.print(i);
    Serial.print("] = ");
    Serial.print(c);
    Serial.println(" C  (-127 = disconnected/bad wiring)");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  buildPins();
  Serial.println("=== DS18B20 probe: scanning pins 2..53 ===");
  for (uint8_t i = 0; i < N; i++) scan(PINS[i]);
  Serial.println("=== done (no line above == nothing found on any pin) ===");
}

void loop() {}
