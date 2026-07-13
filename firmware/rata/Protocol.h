#pragma once
#include <Arduino.h>

// RATA wire protocol 
//
// Frame layout (identical on every transport):
//
//   +-------+-----+-----+------------------+----------+
//   | START | CMD | LEN | PAYLOAD[LEN]     | CHECKSUM |
//   +-------+-----+-----+------------------+----------+
//     0xAA                                   XOR of CMD, LEN and every payload byte
//
// The master (Raspberry Pi) sends command frames; the Arduino answers with a
// response frame using the same layout.

namespace proto {

const uint8_t START_BYTE   = 0xAA;
const uint8_t MAX_PAYLOAD  = 32;      // per-frame payload cap (fits I2C buffers)
const uint8_t MAX_VALUE_BYTES = 8;    // max bytes a read() can return (4x int16)
const uint8_t PROTO_VERSION = 6;

// Commands: master -> Arduino
enum Command : uint8_t {
  CMD_PING        = 0x01,  // payload: none            -> RSP_PONG
  CMD_RESET       = 0x02,  // payload: none            -> RSP_ACK  (drop all devices)
  CMD_ADD_DEVICE  = 0x10,  // payload: id, type, params...   -> RSP_ACK / RSP_NACK
  CMD_WRITE       = 0x20,  // payload: id, data...           -> RSP_ACK / RSP_NACK
  CMD_READ        = 0x21,  // payload: id                    -> RSP_VALUE / RSP_NACK
  CMD_STAGE       = 0x22,  // payload: id, data...  buffer a WRITE, apply on COMMIT
  CMD_COMMIT      = 0x23,  // payload: none          apply all staged writes at once
  CMD_DEVICE_INFO = 0x24,  // payload: index -> RSP_DEVICE (introspect registered devices)
  CMD_SAVE        = 0x25,  // payload: none -> RSP_ACK  (persist registry to EEPROM)
  CMD_READ_MULTI  = 0x26,  // payload: id0,id1,... -> RSP_VALUES (read several in one frame)
};

// Responses: Arduino -> master
enum Response : uint8_t {
  RSP_ACK    = 0x01,  // payload: none
  RSP_NACK   = 0x02,  // payload: errorCode
  RSP_PONG   = 0x03,  // payload: PROTO_VERSION, deviceCount, maxDevices, numDigitalPins
  RSP_VALUE  = 0x04,  // payload: id, then 1..N value bytes (big-endian int16s)
  RSP_DEVICE = 0x05,  // payload: index, id, type, nparams, params... (device config)
  RSP_VALUES = 0x06,  // payload: [id, nbytes, bytes...] repeated (batch read reply)
};

// Device types (extend as new hardware is supported)
enum DeviceType : uint8_t {
  DEV_DIGITAL_OUT = 0x01,   // params: [pin];            write: [0|1]        (LED, relay)
  DEV_DIGITAL_IN  = 0x02,   // params: [pin, pullup];    read: 0|1           (button, PIR)
  DEV_PWM         = 0x03,   // params: [pin];            write: [0..255]     (brightness, speed)
  DEV_SERVO       = 0x04,   // params: [pin];            write: [angle 0..180]
  DEV_STEPPER     = 0x05,   // params: [pin1..pin4];     write: [stepsHi,stepsLo,speedHi,speedLo]
  DEV_ANALOG_IN   = 0x06,   // params: [channel];        read: 0..1023       (pot, LDR, sensors)
  DEV_ULTRASONIC  = 0x07,   // params: [trigPin, echoPin]; read: distance mm (-1 = no echo)
  DEV_DHT         = 0x08,   // params: [pin, kind(11|22)]; read: tempC*10, humidity%*10 (2x int16)
  DEV_ENCODER     = 0x09,   // params: [pinA, pinB]; read: signed position; write: reset to 0
};

// Error codes carried in RSP_NACK
enum Error : uint8_t {
  ERR_NONE          = 0x00,
  ERR_BAD_CHECKSUM  = 0x01,
  ERR_UNKNOWN_CMD   = 0x02,
  ERR_UNKNOWN_TYPE  = 0x03,
  ERR_UNKNOWN_ID    = 0x04,
  ERR_BAD_PARAMS    = 0x05,
  ERR_NO_SPACE      = 0x06,
  ERR_STAGE_FULL    = 0x07,
};

// XOR checksum over CMD, LEN and the payload bytes.
inline uint8_t checksum(uint8_t cmd, uint8_t len, const uint8_t* payload) {
  uint8_t c = cmd ^ len;
  for (uint8_t i = 0; i < len; i++) c ^= payload[i];
  return c;
}

}  // namespace proto
