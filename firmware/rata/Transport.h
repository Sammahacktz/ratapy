#pragma once
#include <Arduino.h>
#include "Protocol.h"
#include "Config.h"

// A Transport is raw byte IO plus one helper to emit a framed response.
// SerialTransport writes the response straight to the wire; WireTransport (I2C)
// buffers it for the next onRequest -- nothing above this layer changes.

class Transport {
public:
  virtual ~Transport() {}

  virtual int  available() = 0;     // bytes ready to read
  virtual int  read()      = 0;     // next byte, or -1
  virtual void send(const uint8_t* data, uint8_t len) = 0;

  // Build and emit a complete response frame.
  void sendFrame(uint8_t cmd, const uint8_t* payload, uint8_t len) {
    uint8_t frame[3 + proto::MAX_PAYLOAD + 1];
    frame[0] = proto::START_BYTE;
    frame[1] = cmd;
    frame[2] = len;
    for (uint8_t i = 0; i < len; i++) frame[3 + i] = payload[i];
    frame[3 + len] = proto::checksum(cmd, len, payload);
    send(frame, 4 + len);
  }
};

class SerialTransport : public Transport {
  Stream& io;
public:
  explicit SerialTransport(Stream& s) : io(s) {}
  int  available() override { return io.available(); }
  int  read()      override { return io.read(); }
  void send(const uint8_t* data, uint8_t len) override { io.write(data, len); }
};

#if defined(RATA_I2C_ADDRESS)
#include <Wire.h>

// I2C slave transport. On I2C the reply cannot be written during the command
// handler -- it must wait for the master's *read* transaction (onRequest). So
// send() buffers the framed response, and flush() writes it when the master
// reads. Incoming bytes arrive via onReceive and are fed through the parser in
// loop(), so available()/read() are unused here.
class WireTransport : public Transport {
  uint8_t _buf[3 + proto::MAX_PAYLOAD + 1];
  volatile uint8_t _len = 0;
public:
  int  available() override { return 0; }
  int  read()      override { return -1; }

  void send(const uint8_t* data, uint8_t len) override {
    if (len > sizeof(_buf)) len = sizeof(_buf);
    for (uint8_t i = 0; i < len; i++) _buf[i] = data[i];
    _len = len;                       // ready for the next onRequest
  }

  // Called from the Wire onRequest ISR: hand the buffered reply to the master.
  void flush() {
    if (_len) Wire.write((const uint8_t*)_buf, _len);
    _len = 0;
  }
};
#endif  // RATA_I2C_ADDRESS
