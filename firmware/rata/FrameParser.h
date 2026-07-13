#pragma once
#include <Arduino.h>
#include "Protocol.h"

// Incremental frame parser. Feed it one byte at a time; it resynchronises on
// the START byte and reports a complete, checksum-verified frame via poll().
// A byte-wise state machine keeps this identical for a Serial stream and for
// I2C, where bytes arrive inside a Wire receive callback.

class FrameParser {
public:
  struct Frame {
    uint8_t cmd;
    uint8_t len;
    uint8_t payload[proto::MAX_PAYLOAD];
  };

  // Push one byte. Returns true when `out` holds a valid, complete frame.
  bool push(uint8_t b, Frame& out) {
    switch (_state) {
      case WAIT_START:
        if (b == proto::START_BYTE) _state = READ_CMD;
        break;
      case READ_CMD:
        _cmd = b; _state = READ_LEN;
        break;
      case READ_LEN:
        _len = b;
        _idx = 0;
        if (_len > proto::MAX_PAYLOAD) { _state = WAIT_START; break; }  // bogus
        _state = (_len == 0) ? READ_CHECKSUM : READ_PAYLOAD;
        break;
      case READ_PAYLOAD:
        _payload[_idx++] = b;
        if (_idx >= _len) _state = READ_CHECKSUM;
        break;
      case READ_CHECKSUM:
        _state = WAIT_START;
        if (b == proto::checksum(_cmd, _len, _payload)) {
          out.cmd = _cmd;
          out.len = _len;
          for (uint8_t i = 0; i < _len; i++) out.payload[i] = _payload[i];
          return true;
        }
        _badChecksum = true;   // surfaced so the sketch can NACK
        break;
    }
    return false;
  }

  bool takeBadChecksum() { bool b = _badChecksum; _badChecksum = false; return b; }

private:
  enum State : uint8_t { WAIT_START, READ_CMD, READ_LEN, READ_PAYLOAD, READ_CHECKSUM };
  State   _state = WAIT_START;
  uint8_t _cmd = 0, _len = 0, _idx = 0;
  uint8_t _payload[proto::MAX_PAYLOAD];
  bool    _badChecksum = false;
};
