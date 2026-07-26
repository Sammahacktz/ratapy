// RATA firmware -- Raspberry-pi Attached Things on Arduino
// =========================================================
// The Arduino starts with no hardware knowledge. The master (Raspberry Pi)
// describes every attached device at runtime via ADD_DEVICE, then drives them
// with WRITE / READ. This lets one firmware image control LEDs, servos,
// steppers and sensors in any combination, decided entirely by the master.
//
// Transport is Serial for now (development over USB); the framing is designed
// to move to I2C/Wire unchanged -- see Transport.h.

#include "Config.h"
#include "Protocol.h"
#include "Transport.h"
#include "FrameParser.h"
#include "Devices.h"

static const uint32_t SERIAL_BAUD = 115200;

// The transport is chosen at compile time (see Config.h): serial by default,
// or an I2C slave if RATA_I2C_ADDRESS is defined. Everything below is identical.
#if defined(RATA_I2C_ADDRESS)
WireTransport   transport;
#else
SerialTransport transport(Serial);
#endif

FrameParser     parser;
DeviceManager   devices;

// Writes buffered by CMD_STAGE, applied back-to-back by CMD_COMMIT so several
// devices start their action in the same loop() pass (microseconds apart).
struct StagedWrite {
  uint8_t id;
  uint8_t len;
  uint8_t data[RATA_STAGE_DATA];
};
static StagedWrite staged[RATA_MAX_STAGED];
static uint8_t     stagedCount = 0;

static void nack(uint8_t err) {
  transport.sendFrame(proto::RSP_NACK, &err, 1);
}

static void handle(const FrameParser::Frame& f) {
  switch (f.cmd) {

    case proto::CMD_PING: {
      // Report who we are so the master can verify the right firmware/board.
      uint8_t body[4] = { proto::PROTO_VERSION, devices.count(),
                          RATA_MAX_DEVICES, RATA_NUM_PINS };
      transport.sendFrame(proto::RSP_PONG, body, 4);
      break;
    }

    case proto::CMD_RESET:
      devices.reset();
      stagedCount = 0;
      transport.sendFrame(proto::RSP_ACK, nullptr, 0);
      break;

    case proto::CMD_ADD_DEVICE: {
      // payload: [id, type, params...]
      if (f.len < 2) { nack(proto::ERR_BAD_PARAMS); break; }
      uint8_t err = devices.add(f.payload[0], f.payload[1],
                                f.payload + 2, f.len - 2);
      if (err == proto::ERR_NONE) transport.sendFrame(proto::RSP_ACK, nullptr, 0);
      else                        nack(err);
      break;
    }

    case proto::CMD_WRITE: {
      // payload: [id, data...]
      if (f.len < 1) { nack(proto::ERR_BAD_PARAMS); break; }
      Device* d = devices.get(f.payload[0]);
      if (!d) { nack(proto::ERR_UNKNOWN_ID); break; }
      if (d->write(f.payload + 1, f.len - 1))
        transport.sendFrame(proto::RSP_ACK, nullptr, 0);
      else
        nack(proto::ERR_BAD_PARAMS);
      break;
    }

    case proto::CMD_STAGE: {
      // payload: [id, data...] -- like WRITE, but only buffered until COMMIT.
      if (f.len < 1 || f.len - 1 > RATA_STAGE_DATA) { nack(proto::ERR_BAD_PARAMS); break; }
      if (!devices.get(f.payload[0])) { nack(proto::ERR_UNKNOWN_ID); break; }
      if (stagedCount >= RATA_MAX_STAGED) { nack(proto::ERR_STAGE_FULL); break; }
      StagedWrite& s = staged[stagedCount++];
      s.id  = f.payload[0];
      s.len = f.len - 1;
      for (uint8_t i = 0; i < s.len; i++) s.data[i] = f.payload[1 + i];
      transport.sendFrame(proto::RSP_ACK, nullptr, 0);
      break;
    }

    case proto::CMD_COMMIT: {
      // Apply every staged write in one tight pass -- near-simultaneous start.
      uint8_t err = proto::ERR_NONE;
      for (uint8_t i = 0; i < stagedCount; i++) {
        Device* d = devices.get(staged[i].id);
        if (!d) { if (err == proto::ERR_NONE) err = proto::ERR_UNKNOWN_ID; continue; }
        if (!d->write(staged[i].data, staged[i].len) && err == proto::ERR_NONE)
          err = proto::ERR_BAD_PARAMS;
      }
      stagedCount = 0;
      if (err == proto::ERR_NONE) transport.sendFrame(proto::RSP_ACK, nullptr, 0);
      else                        nack(err);
      break;
    }

    case proto::CMD_READ: {
      // payload: [id] -> RSP_VALUE [id, value bytes...] (length depends on device)
      if (f.len < 1) { nack(proto::ERR_BAD_PARAMS); break; }
      Device* d = devices.get(f.payload[0]);
      if (!d) { nack(proto::ERR_UNKNOWN_ID); break; }
      uint8_t body[1 + proto::MAX_VALUE_BYTES];
      body[0] = d->id();
      uint8_t n = d->readInto(body + 1);
      transport.sendFrame(proto::RSP_VALUE, body, 1 + n);
      break;
    }

    case proto::CMD_READ_MULTI: {
      // payload: [id0, id1, ...] -> RSP_VALUES [id, nbytes, bytes...] per device.
      // One round-trip reads many devices (the HID gamepad poll). Stops before the
      // reply overflows MAX_PAYLOAD; the master keeps each request small enough.
      uint8_t body[proto::MAX_PAYLOAD];
      uint8_t pos = 0;
      for (uint8_t i = 0; i < f.len; i++) {
        Device* d = devices.get(f.payload[i]);
        if (!d) { nack(proto::ERR_UNKNOWN_ID); return; }
        uint8_t tmp[proto::MAX_VALUE_BYTES];
        uint8_t n = d->readInto(tmp);
        if (pos + 2 + n > sizeof(body)) break;      // out of room; return what fits
        body[pos++] = d->id();
        body[pos++] = n;
        for (uint8_t k = 0; k < n; k++) body[pos++] = tmp[k];
      }
      transport.sendFrame(proto::RSP_VALUES, body, pos);
      break;
    }

    case proto::CMD_DEVICE_INFO: {
      // payload: [index] -> RSP_DEVICE [index, id, type, nparams, params...]
      if (f.len < 1) { nack(proto::ERR_BAD_PARAMS); break; }
      Device* d = devices.at(f.payload[0]);
      if (!d) { nack(proto::ERR_UNKNOWN_ID); break; }
      uint8_t body[4 + Device::MAX_PARAMS];
      body[0] = f.payload[0];
      body[1] = d->id();
      body[2] = d->type();
      body[3] = d->nparams();
      for (uint8_t i = 0; i < d->nparams(); i++) body[4 + i] = d->params()[i];
      transport.sendFrame(proto::RSP_DEVICE, body, 4 + d->nparams());
      break;
    }

    case proto::CMD_SAVE:
      // Persist the current registry so it survives a reset / power-cycle.
      devices.save();
      transport.sendFrame(proto::RSP_ACK, nullptr, 0);
      break;

    default:
      nack(proto::ERR_UNKNOWN_CMD);
      break;
  }
}

// Feed one received byte through the parser; handle a completed frame.
// Shared by the serial loop and the I2C receive path.
static void feedByte(uint8_t b) {
  FrameParser::Frame f;
  if (parser.push(b, f)) {
    handle(f);
  } else if (parser.takeBadChecksum()) {
    nack(proto::ERR_BAD_CHECKSUM);
  }
}

#if defined(RATA_I2C_ADDRESS)
// I2C mode. onReceive/onRequest run in ISR context, so keep them tiny: buffer
// the incoming bytes and let loop() do the real work (parsing, device writes),
// which also keeps device access single-threaded with updateAll().
volatile uint8_t i2cIn[3 + proto::MAX_PAYLOAD + 1];
volatile uint8_t i2cInLen   = 0;
volatile bool    i2cInReady = false;

void onReceive(int count) {
  uint8_t k = 0;
  while (Wire.available() && k < sizeof(i2cIn)) i2cIn[k++] = (uint8_t)Wire.read();
  i2cInLen   = k;
  i2cInReady = true;
}

void onRequest() {
  transport.flush();          // send the reply prepared by the last command
}
#endif

void setup() {
#if defined(RATA_I2C_ADDRESS)
  Wire.begin(RATA_I2C_ADDRESS);
  Wire.onReceive(onReceive);
  Wire.onRequest(onRequest);
#else
  Serial.begin(SERIAL_BAUD);
#endif
  // Re-create any devices persisted with CMD_SAVE, so a board that was set up by
  // an earlier session comes back with the same devices after a reset/power-cycle.
  devices.load();
}

void loop() {
#if defined(RATA_I2C_ADDRESS)
  if (i2cInReady) {
    // Copy out of the volatile buffer with interrupts off, then process.
    uint8_t buf[sizeof(i2cIn)];
    noInterrupts();
    uint8_t len = i2cInLen;
    for (uint8_t i = 0; i < len; i++) buf[i] = i2cIn[i];
    i2cInReady = false;
    interrupts();
    for (uint8_t i = 0; i < len; i++) feedByte(buf[i]);
  }
#else
  while (transport.available()) feedByte((uint8_t)transport.read());
#endif
  // Tick every device so long-running actions (stepper moves, ...) progress
  // concurrently while the transport stays responsive.
  devices.updateAll();
}
