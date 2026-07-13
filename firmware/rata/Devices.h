#pragma once
#include <Arduino.h>
#include <EEPROM.h>
#include <AccelStepper.h>
#include <Servo.h>
#include <DHTStable.h>
#include "Protocol.h"
#include "BoardConfig.h"

// Device model
// ------------
// Every piece of hardware the master attaches is a Device subclass. The base
// class defines the lifecycle (begin / write / read / update); adding support
// for a servo or sensor later means writing one new subclass and one line in
// DeviceManager::create() -- nothing else changes.
//
// IMPORTANT: write() must NEVER block. A long-running action (stepper move,
// fade, ...) only *stores its goal* in write(); the actual work happens in
// update(), which loop() calls thousands of times per second for every device.
// That is what lets many devices act at the same time.

class Device {
public:
  explicit Device(uint8_t id) : _id(id) {}
  virtual ~Device() {}

  uint8_t id() const { return _id; }
  virtual uint8_t type() const = 0;

  // Configure hardware from the ADD_DEVICE params. Return false on bad params.
  virtual bool begin(const uint8_t* params, uint8_t n) = 0;

  // Remember the raw config (pins etc.) so the master can introspect this
  // device later via CMD_DEVICE_INFO. Filled by DeviceManager after begin().
  static const uint8_t MAX_PARAMS = 5;          // stepper uses 4; 5 is headroom
  void rememberParams(const uint8_t* params, uint8_t n) {
    _nparams = n < MAX_PARAMS ? n : MAX_PARAMS;
    for (uint8_t i = 0; i < _nparams; i++) _params[i] = params[i];
  }
  uint8_t nparams() const { return _nparams; }
  const uint8_t* params() const { return _params; }

  // Actuators override write(); return false if the data is unusable.
  // Must return immediately -- set a goal, don't do the work here.
  virtual bool write(const uint8_t* data, uint8_t n) { (void)data; (void)n; return false; }

  // Single-value sensors override read() (a 16-bit value). Long-running
  // actuators also report progress here (e.g. stepper: 1 while moving, 0 done).
  virtual int16_t read() { return 0; }

  // Fill `out` with this device's value bytes and return the count. The default
  // packs read() as one big-endian int16; multi-value sensors (e.g. a DHT
  // returning temperature + humidity) override this to write several int16s.
  virtual uint8_t readInto(uint8_t* out) {
    int16_t v = read();
    out[0] = (uint8_t)(v >> 8);
    out[1] = (uint8_t)(v & 0xFF);
    return 2;
  }

  // Called every loop() pass; do one small slice of pending work.
  virtual void update() {}

protected:
  uint8_t _id;
  uint8_t _params[MAX_PARAMS];
  uint8_t _nparams = 0;
};

// --- Concrete devices ------------------------------------------------------

// A simple on/off pin, e.g. an LED. params: [pin].
// write: [0]=off, [1]=on, or [2, countHi,countLo, onHi,onLo, offHi,offLo]=blink.
//   Blinking is NON-BLOCKING: the goal is stored and the pin is toggled in
//   update(); count 0 means forever. read() is 1 while blinking, 0 when idle.
class DigitalOutput : public Device {
  uint8_t  _pin = 0xFF;
  bool     _level = false;
  uint16_t _onMs = 0, _offMs = 0;     // 0/0 = not blinking
  uint16_t _cyclesLeft = 0;           // remaining blinks (ignored if infinite)
  bool     _infinite = false;
  uint32_t _nextToggle = 0;           // millis() of the next edge
public:
  explicit DigitalOutput(uint8_t id) : Device(id) {}
  uint8_t type() const override { return proto::DEV_DIGITAL_OUT; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 1) return false;
    if (params[0] >= RATA_NUM_PINS) return false;   // reject pins this board lacks
    _pin = params[0];
    pinMode(_pin, OUTPUT);
    setLevel(false);
    return true;
  }

  bool write(const uint8_t* data, uint8_t n) override {
    if (n < 1) return false;
    if (data[0] <= 1) {                             // plain off/on -> cancel blink
      _onMs = _offMs = 0;
      setLevel(data[0] == 1);
      return true;
    }
    if (data[0] == 2) {                             // start a blink pattern
      if (n < 7) return false;
      uint16_t count = ((uint16_t)data[1] << 8) | data[2];
      _onMs  = ((uint16_t)data[3] << 8) | data[4];
      _offMs = ((uint16_t)data[5] << 8) | data[6];
      _infinite   = (count == 0);
      _cyclesLeft = count;
      setLevel(true);                               // begin the first ON phase
      _nextToggle = millis() + _onMs;
      return true;
    }
    return false;
  }

  // Busy (1) while a blink is still running, so wait()/is_busy() can track it.
  int16_t read() override { return (_onMs || _offMs) ? 1 : 0; }

  void update() override {
    if (!_onMs && !_offMs) return;                  // not blinking
    if ((int32_t)(millis() - _nextToggle) < 0) return;
    if (_level) {                                   // end of an ON phase -> OFF
      setLevel(false);
      _nextToggle = millis() + _offMs;
    } else {                                        // end of a full cycle
      if (!_infinite && --_cyclesLeft == 0) {
        _onMs = _offMs = 0;                         // done -> stay off
        return;
      }
      setLevel(true);
      _nextToggle = millis() + _onMs;
    }
  }

private:
  void setLevel(bool on) { _level = on; digitalWrite(_pin, on ? HIGH : LOW); }
};

// A 4-wire stepper on a driver board (e.g. 28BYJ-48 + ULN2003), driven by the
// AccelStepper library so several steppers can run at the same time.
// params: [pin1, pin2, pin3, pin4]  (passed to AccelStepper in this order)
// write:  [stepsHi, stepsLo, speedHi, speedLo]
//         steps: signed 16-bit relative move; speed: unsigned steps/second
// read:   1 while a move is in progress, 0 when idle
// A 4-wire stepper (AccelStepper). write:
//   [stepsHi,stepsLo, speedHi,speedLo]   MOVE relative (signed steps) at speed
//   [0]                                  STOP now (halts a move or a run)
//   [1, speedHi,speedLo]                 RUN continuously at signed speed (fwd/rev)
// read() is 1 while moving or running, 0 when idle. Modes: 0 idle, 1 move, 2 run.
class StepperDevice : public Device {
  AccelStepper* _stepper = nullptr;
  uint8_t _mode = 0;
public:
  explicit StepperDevice(uint8_t id) : Device(id) {}
  ~StepperDevice() override { delete _stepper; }
  uint8_t type() const override { return proto::DEV_STEPPER; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 4) return false;
    for (uint8_t i = 0; i < 4; i++)
      if (params[i] >= RATA_NUM_PINS) return false;
    _stepper = new AccelStepper(AccelStepper::FULL4WIRE,
                                params[0], params[1], params[2], params[3]);
    _stepper->disableOutputs();          // no coil current until a move starts
    return true;
  }

  bool write(const uint8_t* data, uint8_t n) override {
    if (!_stepper) return false;
    if (n == 4) {                        // relative move at speed
      int16_t  steps = (int16_t)(((uint16_t)data[0] << 8) | data[1]);
      uint16_t speed = ((uint16_t)data[2] << 8) | data[3];
      if (speed == 0) return false;
      _stepper->enableOutputs();
      _stepper->setMaxSpeed(speed);
      _stepper->move(steps);             // relative target; returns immediately
      _stepper->setSpeed(speed);         // AFTER move(): move() recomputes speed
      _mode = 1;
      return true;
    }
    if (n == 1 && data[0] == 0) {        // stop
      _stepper->setSpeed(0);
      _stepper->moveTo(_stepper->currentPosition());   // clear any pending target
      _stepper->disableOutputs();
      _mode = 0;
      return true;
    }
    if (n == 3 && data[0] == 1) {        // run continuously at signed speed
      int16_t speed = (int16_t)(((uint16_t)data[1] << 8) | data[2]);
      uint16_t mag = speed < 0 ? -speed : speed;
      _stepper->enableOutputs();
      _stepper->setMaxSpeed(mag ? mag : 1);
      _stepper->setSpeed(speed);
      _mode = 2;
      return true;
    }
    return false;
  }

  int16_t read() override { return _mode != 0 ? 1 : 0; }

  void update() override {
    if (!_stepper) return;
    if (_mode == 1) {                    // finite move
      if (_stepper->distanceToGo() != 0) _stepper->runSpeedToPosition();
      else { _stepper->disableOutputs(); _mode = 0; }
    } else if (_mode == 2) {             // continuous run
      _stepper->runSpeed();
    }
  }
};

// A PWM output (analogWrite): LED brightness, DC-motor speed via a driver, etc.
// params: [pin]. write: [value 0..255]. The Python side checks the pin is
// PWM-capable; analogWrite on a non-PWM pin just acts as on/off at 128.
// A PWM output. write:
//   [value]                                   set duty 0..255 now (cancels anim)
//   [1, target, durHi,durLo]                  FADE to target over dur ms
//   [2, cyclesHi,cyclesLo, max, perHi,perLo]  PULSE (breathe) 0..max, N cycles
//   [3, cyclesHi,cyclesLo, max, onHi,onLo, offHi,offLo]   BLINK max/0, N cycles
//   (cycles 0 = forever). Fades/pulses/blinks run NON-BLOCKING in update();
//   read() is 1 while animating.
class PWMOutput : public Device {
  uint8_t  _pin = 0xFF;
  uint8_t  _value = 0;
  // one linear ramp segment: _from -> _to over _dur ms starting at _t0
  uint8_t  _from = 0, _to = 0;
  uint16_t _dur = 0;                 // 0 = no ramp in progress
  uint32_t _t0 = 0;
  // pulse state (repeated up/down ramps)
  bool     _pulsing = false, _infinite = false, _rising = false;
  uint16_t _cyclesLeft = 0, _half = 0, _peak = 0;
  // blink state (square on/off, separate from the ramp engine)
  uint16_t _onMs = 0, _offMs = 0;    // 0/0 = not blinking
  bool     _blinkLevel = false;
  uint32_t _nextToggle = 0;
public:
  explicit PWMOutput(uint8_t id) : Device(id) {}
  uint8_t type() const override { return proto::DEV_PWM; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 1 || params[0] >= RATA_NUM_PINS) return false;
    _pin = params[0];
    pinMode(_pin, OUTPUT);
    set(0);
    return true;
  }

  bool write(const uint8_t* data, uint8_t n) override {
    if (n < 1) return false;
    if (n == 1) { cancel(); set(data[0]); return true; }   // plain set
    if (data[0] == 1 && n >= 4) {                          // fade
      cancel();
      startRamp(_value, data[1], ((uint16_t)data[2] << 8) | data[3]);
      return true;
    }
    if (data[0] == 2 && n >= 6) {                          // pulse / breathe
      cancel();
      uint16_t cycles = ((uint16_t)data[1] << 8) | data[2];
      _peak = data[3];
      _half = (((uint16_t)data[4] << 8) | data[5]) / 2;
      _infinite = (cycles == 0); _cyclesLeft = cycles;
      _pulsing = true; _rising = true;
      startRamp(0, _peak, _half);
      return true;
    }
    if (data[0] == 3 && n >= 8) {                          // blink max/0
      cancel();
      uint16_t cycles = ((uint16_t)data[1] << 8) | data[2];
      _peak  = data[3];
      _onMs  = ((uint16_t)data[4] << 8) | data[5];
      _offMs = ((uint16_t)data[6] << 8) | data[7];
      _infinite = (cycles == 0); _cyclesLeft = cycles;
      _blinkLevel = true; set(_peak);
      _nextToggle = millis() + _onMs;
      return true;
    }
    return false;
  }

  int16_t read() override { return (_dur || _pulsing || _onMs || _offMs) ? 1 : 0; }

  void update() override {
    if (_onMs || _offMs) { updateBlink(); return; }
    if (!_dur) return;                                    // nothing animating
    uint32_t elapsed = millis() - _t0;
    if (elapsed < _dur) {                                 // interpolate the ramp
      set(_from + (int32_t)(_to - _from) * (int32_t)elapsed / _dur);
      return;
    }
    set(_to);                                             // segment finished
    _dur = 0;
    if (!_pulsing) return;
    if (_rising) { _rising = false; startRamp(_peak, 0, _half); }   // top -> fall
    else {                                                          // bottom -> cycle done
      if (!_infinite && --_cyclesLeft == 0) { _pulsing = false; return; }
      _rising = true; startRamp(0, _peak, _half);
    }
  }

private:
  void set(int v) { _value = (uint8_t)constrain(v, 0, 255); analogWrite(_pin, _value); }
  void cancel()   { _dur = 0; _pulsing = false; _onMs = _offMs = 0; }
  void startRamp(uint8_t from, uint8_t to, uint16_t dur) {
    _from = from; _to = to; _dur = dur ? dur : 1; _t0 = millis(); set(from);
  }
  void updateBlink() {
    if ((int32_t)(millis() - _nextToggle) < 0) return;
    if (_blinkLevel) { set(0); _blinkLevel = false; _nextToggle = millis() + _offMs; }
    else {
      if (!_infinite && --_cyclesLeft == 0) { _onMs = _offMs = 0; return; }
      set(_peak); _blinkLevel = true; _nextToggle = millis() + _onMs;
    }
  }
};

// A hobby servo. params: [pin]. write: [angle 0..180]. The Servo library keeps
// the control pulse going on its own, so write() is instant and non-blocking.
// A hobby servo. write:
//   [angle]                     move to angle 0..180 now (cancels a sweep)
//   [1, angle, durHi,durLo]     SWEEP smoothly to angle over dur ms (non-blocking)
// read() is 1 while a sweep is in progress.
class ServoDevice : public Device {
  Servo    _servo;
  uint8_t  _pin = 0xFF;
  uint8_t  _angle = 0, _from = 0, _to = 0;
  uint16_t _dur = 0;                 // 0 = no sweep in progress
  uint32_t _t0 = 0;
public:
  explicit ServoDevice(uint8_t id) : Device(id) {}
  ~ServoDevice() override { _servo.detach(); }
  uint8_t type() const override { return proto::DEV_SERVO; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 1 || params[0] >= RATA_NUM_PINS) return false;
    _pin = params[0];
    _servo.attach(_pin);
    return true;
  }

  bool write(const uint8_t* data, uint8_t n) override {
    if (n < 1) return false;
    if (n == 1) { _dur = 0; setAngle(data[0]); return true; }   // instant move
    if (data[0] == 1 && n >= 4) {                               // timed sweep
      _from = _angle;
      _to = data[1] > 180 ? 180 : data[1];
      _dur = (((uint16_t)data[2] << 8) | data[3]);
      if (!_dur) { setAngle(_to); return true; }
      _t0 = millis();
      return true;
    }
    return false;
  }

  int16_t read() override { return _dur ? 1 : 0; }

  void update() override {
    if (!_dur) return;
    uint32_t elapsed = millis() - _t0;
    if (elapsed < _dur) setAngle(_from + (int32_t)(_to - _from) * (int32_t)elapsed / _dur);
    else { setAngle(_to); _dur = 0; }
  }

private:
  void setAngle(uint8_t a) { _angle = a > 180 ? 180 : a; _servo.write(_angle); }
};

// A digital input (button, switch, PIR, limit switch).
// params: [pin, pullup]  (pullup != 0 -> INPUT_PULLUP). read: 0 or 1.
class DigitalInput : public Device {
  uint8_t _pin = 0xFF;
public:
  explicit DigitalInput(uint8_t id) : Device(id) {}
  uint8_t type() const override { return proto::DEV_DIGITAL_IN; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 1 || params[0] >= RATA_NUM_PINS) return false;
    _pin = params[0];
    bool pullup = (n >= 2 && params[1]);
    pinMode(_pin, pullup ? INPUT_PULLUP : INPUT);
    return true;
  }

  int16_t read() override { return digitalRead(_pin); }
};

// An analog input (potentiometer, LDR, and any 0..Vcc sensor).
// params: [channel]  (0 == A0). read: 0..1023. Real-unit conversion is the
// master's job -- the firmware just returns the raw ADC value.
class AnalogInput : public Device {
  uint8_t _channel = 0xFF;
public:
  explicit AnalogInput(uint8_t id) : Device(id) {}
  uint8_t type() const override { return proto::DEV_ANALOG_IN; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 1 || params[0] >= RATA_NUM_ANALOG) return false;
    _channel = params[0];
    return true;                       // analog pins need no pinMode
  }

  int16_t read() override { return analogRead(_channel); }
};

// An incremental rotary encoder (quadrature, e.g. KY-040). params: [pinA, pinB].
// The position must be tracked on the board -- pulses come faster than the
// master could poll -- so update() decodes every A/B transition into a signed
// count. read: current position; write: reset the count to 0.
class EncoderDevice : public Device {
  uint8_t _a = 0xFF, _b = 0xFF;
  uint8_t _last = 0;
  int16_t _pos = 0;
public:
  explicit EncoderDevice(uint8_t id) : Device(id) {}
  uint8_t type() const override { return proto::DEV_ENCODER; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 2 || params[0] >= RATA_NUM_PINS || params[1] >= RATA_NUM_PINS) return false;
    _a = params[0];
    _b = params[1];
    pinMode(_a, INPUT_PULLUP);
    pinMode(_b, INPUT_PULLUP);
    _last = (uint8_t)((digitalRead(_a) << 1) | digitalRead(_b));
    _pos = 0;
    return true;
  }

  bool write(const uint8_t* data, uint8_t n) override {
    (void)data; (void)n;
    _pos = 0;                            // any write resets the count
    return true;
  }

  int16_t read() override { return _pos; }

  void update() override {
    // Quadrature transition table, indexed by (last<<2)|current 2-bit states.
    static const int8_t QTAB[16] = { 0, -1,  1,  0,
                                     1,  0,  0, -1,
                                    -1,  0,  0,  1,
                                     0,  1, -1,  0 };
    uint8_t cur = (uint8_t)((digitalRead(_a) << 1) | digitalRead(_b));
    if (cur != _last) {
      _pos += QTAB[(_last << 2) | cur];
      _last = cur;
    }
  }
};

// An HC-SR04 ultrasonic distance sensor. params: [trigPin, echoPin].
// read: distance in millimetres, or -1 if no echo came back (out of range).
// NOTE: the read blocks in pulseIn for up to ~25 ms, briefly stalling other
// devices' update() -- fine for on-demand reads, avoid in tight motion loops.
class UltrasonicDevice : public Device {
  uint8_t _trig = 0xFF, _echo = 0xFF;
public:
  explicit UltrasonicDevice(uint8_t id) : Device(id) {}
  uint8_t type() const override { return proto::DEV_ULTRASONIC; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 2 || params[0] >= RATA_NUM_PINS || params[1] >= RATA_NUM_PINS) return false;
    _trig = params[0];
    _echo = params[1];
    pinMode(_trig, OUTPUT);
    pinMode(_echo, INPUT);
    digitalWrite(_trig, LOW);
    return true;
  }

  int16_t read() override {
    digitalWrite(_trig, LOW);  delayMicroseconds(2);
    digitalWrite(_trig, HIGH); delayMicroseconds(10);
    digitalWrite(_trig, LOW);
    unsigned long us = pulseIn(_echo, HIGH, 25000UL);   // ~4 m ceiling
    if (us == 0) return -1;                             // no echo
    return (int16_t)((us * 343UL) / 2000UL);            // mm (v_sound/2)
  }
};

// A DHT11 / DHT22 temperature + humidity sensor. params: [pin, kind(11|22)].
// read: two int16s -- temperature (degC x10) and humidity (% x10). On a read
// error both come back as INT16_MIN, which the master turns into an error.
class DHTDevice : public Device {
  DHTStable _dht;
  uint8_t   _pin = 0xFF;
  uint8_t   _kind = 22;
public:
  explicit DHTDevice(uint8_t id) : Device(id) {}
  uint8_t type() const override { return proto::DEV_DHT; }

  bool begin(const uint8_t* params, uint8_t n) override {
    if (n < 2 || params[0] >= RATA_NUM_PINS) return false;
    if (params[1] != 11 && params[1] != 22) return false;
    _pin = params[0];
    _kind = params[1];
    return true;
  }

  uint8_t readInto(uint8_t* out) override {
    int status = (_kind == 11) ? _dht.read11(_pin) : _dht.read22(_pin);
    int16_t t, h;
    if (status != DHTLIB_OK) {
      t = h = INT16_MIN;                                // sentinel -> error
    } else {
      t = (int16_t)lround(_dht.getTemperature() * 10.0);
      h = (int16_t)lround(_dht.getHumidity() * 10.0);
    }
    out[0] = (uint8_t)(t >> 8); out[1] = (uint8_t)(t & 0xFF);
    out[2] = (uint8_t)(h >> 8); out[3] = (uint8_t)(h & 0xFF);
    return 4;
  }
};

// --- Registry --------------------------------------------------------------

class DeviceManager {
public:
  // Board-dependent, set at compile time in BoardConfig.h (SRAM-driven).
  static const uint8_t MAX_DEVICES = RATA_MAX_DEVICES;

  DeviceManager() { for (uint8_t i = 0; i < MAX_DEVICES; i++) _devices[i] = nullptr; }

  Device* get(uint8_t id) {
    for (uint8_t i = 0; i < MAX_DEVICES; i++)
      if (_devices[i] && _devices[i]->id() == id) return _devices[i];
    return nullptr;
  }

  // The index-th registered device (0..count-1), for CMD_DEVICE_INFO. The
  // ordering is stable between adds, which is all the master needs to enumerate.
  Device* at(uint8_t index) {
    uint8_t c = 0;
    for (uint8_t i = 0; i < MAX_DEVICES; i++)
      if (_devices[i]) { if (c == index) return _devices[i]; c++; }
    return nullptr;
  }

  uint8_t count() const {
    uint8_t c = 0;
    for (uint8_t i = 0; i < MAX_DEVICES; i++) if (_devices[i]) c++;
    return c;
  }

  // Add (or replace) a device. Returns an Error code (ERR_NONE on success).
  uint8_t add(uint8_t id, uint8_t deviceType, const uint8_t* params, uint8_t n) {
    Device* dev = create(id, deviceType);
    if (!dev) return proto::ERR_UNKNOWN_TYPE;
    if (!dev->begin(params, n)) { delete dev; return proto::ERR_BAD_PARAMS; }
    dev->rememberParams(params, n);         // keep config for CMD_DEVICE_INFO

    // Replace an existing device with the same id.
    for (uint8_t i = 0; i < MAX_DEVICES; i++) {
      if (_devices[i] && _devices[i]->id() == id) {
        delete _devices[i];
        _devices[i] = dev;
        return proto::ERR_NONE;
      }
    }
    // Otherwise take the first free slot.
    for (uint8_t i = 0; i < MAX_DEVICES; i++) {
      if (!_devices[i]) { _devices[i] = dev; return proto::ERR_NONE; }
    }
    delete dev;
    return proto::ERR_NO_SPACE;
  }

  void reset() {
    for (uint8_t i = 0; i < MAX_DEVICES; i++) {
      delete _devices[i];
      _devices[i] = nullptr;
    }
  }

  // --- persistence (EEPROM) ----------------------------------------------
  // Save the current registry so the board re-creates the same devices on its
  // next boot -- the config survives a power-cycle / reset (and a serial
  // connection that auto-resets the board). Format at EE_BASE:
  //   [ 'R', 'A', FORMAT, count, {id, type, nparams, params[nparams]} x count ]
  // save() writes with EEPROM.update (only changed cells) to spare the ~100k
  // write-cycle budget; call it when the registry changes, not in a loop.

  bool save() {
    uint16_t addr = EE_BASE;
    EEPROM.update(addr++, EE_MAGIC0);
    EEPROM.update(addr++, EE_MAGIC1);
    EEPROM.update(addr++, EE_FORMAT);
    EEPROM.update(addr++, count());
    for (uint8_t i = 0; i < MAX_DEVICES; i++) {
      Device* d = _devices[i];
      if (!d) continue;
      EEPROM.update(addr++, d->id());
      EEPROM.update(addr++, d->type());
      uint8_t n = d->nparams();
      EEPROM.update(addr++, n);
      for (uint8_t j = 0; j < n; j++) EEPROM.update(addr++, d->params()[j]);
    }
    return true;
  }

  // Re-create devices from EEPROM, if a valid image is stored. Called at boot.
  void load() {
    uint16_t addr = EE_BASE;
    if (EEPROM.read(addr) != EE_MAGIC0 || EEPROM.read(addr + 1) != EE_MAGIC1
        || EEPROM.read(addr + 2) != EE_FORMAT) return;         // nothing valid saved
    addr += 3;
    uint8_t c = EEPROM.read(addr++);
    for (uint8_t k = 0; k < c && k < MAX_DEVICES; k++) {
      uint8_t id   = EEPROM.read(addr++);
      uint8_t type = EEPROM.read(addr++);
      uint8_t n    = EEPROM.read(addr++);
      if (n > Device::MAX_PARAMS) return;                      // corrupt -> stop
      uint8_t params[Device::MAX_PARAMS];
      for (uint8_t j = 0; j < n; j++) params[j] = EEPROM.read(addr++);
      add(id, type, params, n);                                // begin() + remember
    }
  }

  // Give every device a slice of CPU; called once per loop() pass.
  void updateAll() {
    for (uint8_t i = 0; i < MAX_DEVICES; i++)
      if (_devices[i]) _devices[i]->update();
  }

private:
  Device* _devices[MAX_DEVICES];

  // EEPROM persistence header (see save()/load()).
  static const uint16_t EE_BASE   = 0;
  static const uint8_t  EE_MAGIC0 = 'R';
  static const uint8_t  EE_MAGIC1 = 'A';
  static const uint8_t  EE_FORMAT = 1;

  // Factory: map a wire type code to a concrete Device.
  static Device* create(uint8_t id, uint8_t deviceType) {
    switch (deviceType) {
      case proto::DEV_DIGITAL_OUT: return new DigitalOutput(id);
      case proto::DEV_DIGITAL_IN:  return new DigitalInput(id);
      case proto::DEV_PWM:         return new PWMOutput(id);
      case proto::DEV_SERVO:       return new ServoDevice(id);
      case proto::DEV_STEPPER:     return new StepperDevice(id);
      case proto::DEV_ANALOG_IN:   return new AnalogInput(id);
      case proto::DEV_ULTRASONIC:  return new UltrasonicDevice(id);
      case proto::DEV_DHT:         return new DHTDevice(id);
      case proto::DEV_ENCODER:     return new EncoderDevice(id);
      default:                     return nullptr;
    }
  }
};
