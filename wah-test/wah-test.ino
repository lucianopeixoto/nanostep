/*
 * Reactor Wah CC Test
 * ===================
 * Finds out whether ANY MIDI CC controls the Wah position on the
 * Positive Grid REACTOR 50/100 over the DIN MIDI IN port.
 *
 * The official manual's MIDI chart has no Wah position CC. This sketch
 * tests every unassigned CC to see if one of them moves the Wah.
 *
 * How to use:
 *   1. Wire the Nano's D10 (via SoftwareSerial) to the DIN MIDI OUT
 *      circuit (same as the main project, but TX is D10, not D1):
 *        DIN pin 5 -- 220R -- Nano D10
 *        DIN pin 4 -- 220R -- Nano 5V
 *        DIN pin 2 -- Nano GND
 *   2. Connect the DIN cable to the amp's MIDI IN.
 *   3. On the amp, select a preset that has the Wah effect in the
 *      signal chain. The Wah must be in the chain for its position
 *      to be audible.
 *   4. Open the Serial Monitor (115200 baud).
 *   5. Upload and run. The sketch turns the Wah ON, then tests each
 *      candidate CC in turn, printing the CC number to the monitor.
 *   6. Play a note or chord and listen. When a CC moves the Wah, you
 *      will hear the Wah sweep as the value goes 0 -> 127 -> 0.
 *   7. Note the CC number shown on the monitor at that moment.
 *      That is the Wah position CC (if one exists).
 *   8. If no CC moves the Wah, the DIN MIDI port really cannot control
 *      Wah position, and the Wah is only available via the REACTOR
 *      Control footswitch.
 *
 * Note: this sketch uses SoftwareSerial for MIDI so the hardware Serial
 * (USB) stays free for the debug output. MIDI is transmit-only here,
 * which SoftwareSerial handles fine at 31250 baud.
 */

#include <SoftwareSerial.h>

// RX pin is not connected (transmit only). TX is D10.
SoftwareSerial midiSerial(11, 10);

const byte CC_WAH_ONOFF = 3;

// CCs to skip: the ones already assigned in the manual, plus the ones
// that would mute the amp or change banks/amp slots mid-test.
//   0-7   effect toggles
//   10    FX loop
//   12,13 heat | 15 bank | 21-26 amp slots | 27,28 push/smooth
//   30,31,32 volumes (would mute!) | 35 tuner (mutes) | 36 tap tempo
bool skipCC(byte cc) {
  if (cc <= 7) return true;
  if (cc == 10) return true;
  if (cc == 12 || cc == 13) return true;
  if (cc == 15) return true;
  if (cc >= 21 && cc <= 28) return true;
  if (cc >= 30 && cc <= 32) return true;
  if (cc == 35 || cc == 36) return true;
  return false;
}

void sendCC(byte cc, byte value) {
  midiSerial.write(0xB0);  // Control Change, channel 1
  midiSerial.write(cc & 0x7F);
  midiSerial.write(value & 0x7F);
}

void setup() {
  Serial.begin(115200);
  midiSerial.begin(31250);
  delay(500);
  Serial.println();
  Serial.println("Reactor Wah CC test");
  Serial.println("Make sure the Wah is in the preset's signal chain.");
  Serial.println("Play a note and listen for the Wah sweeping.");
  Serial.println();
  // Make sure the Wah is ON.
  sendCC(CC_WAH_ONOFF, 127);
  delay(500);
}

void loop() {
  for (byte cc = 0; cc < 128; cc++) {
    if (skipCC(cc)) continue;
    Serial.print("Testing CC ");
    Serial.println(cc);
    // Sweep the value 0 -> 127 -> 0 so a Wah position CC is audible.
    sendCC(cc, 0);
    delay(400);
    sendCC(cc, 127);
    delay(400);
    sendCC(cc, 0);
    delay(200);
    // Re-enable the Wah in case this CC toggled something.
    sendCC(CC_WAH_ONOFF, 127);
    delay(200);
  }
  Serial.println();
  Serial.println("Sweep complete. If no CC moved the Wah, DIN MIDI cannot control Wah position.");
  Serial.println("Restarting the sweep in 5 seconds...");
  delay(5000);
  sendCC(CC_WAH_ONOFF, 127);
}
