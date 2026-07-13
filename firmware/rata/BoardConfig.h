#pragma once
#include <Arduino.h>

// Per-board tuning, chosen automatically at COMPILE TIME from the target MCU.

// RATA_MAX_DEVICES is driven by SRAM: each device is a small heap object plus a
// slot pointer, so a 2 KB Uno/Nano must be far more conservative than an 8 KB
// Mega. Pin counts come from the Arduino core (NUM_DIGITAL_PINS /
// NUM_ANALOG_INPUTS)

#if defined(__AVR_ATmega2560__)          // Arduino Mega / Mega2560 (8 KB SRAM)
  static const uint8_t RATA_MAX_DEVICES = 32;
  static const uint8_t RATA_MAX_STAGED  = 8;   // pending writes held for COMMIT

#elif defined(__AVR_ATmega328P__)        // Arduino Uno / Nano (2 KB SRAM)
  static const uint8_t RATA_MAX_DEVICES = 12;
  static const uint8_t RATA_MAX_STAGED  = 4;

#elif defined(__AVR_ATmega32U4__)        // Leonardo / Micro (2.5 KB SRAM)
  static const uint8_t RATA_MAX_DEVICES = 12;
  static const uint8_t RATA_MAX_STAGED  = 4;

#else                                     // unknown board: play it safe
  static const uint8_t RATA_MAX_DEVICES = 8;
  static const uint8_t RATA_MAX_STAGED  = 4;
#endif

// Data bytes one staged write can carry (a stepper write needs 4).
static const uint8_t RATA_STAGE_DATA = 8;

// Highest usable digital pin number (0 .. RATA_NUM_PINS-1).
static const uint8_t RATA_NUM_PINS = (uint8_t)NUM_DIGITAL_PINS;

// Number of analog input channels (A0 == channel 0 .. RATA_NUM_ANALOG-1).
static const uint8_t RATA_NUM_ANALOG = (uint8_t)NUM_ANALOG_INPUTS;
