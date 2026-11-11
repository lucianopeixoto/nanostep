/*
 * NanoStep — configurable MIDI foot controller
 * for the Positive Grid REACTOR 50 / REACTOR 100.
 *
 * Arduino Nano, 10 footswitches, expression pedal input, wired 5-pin
 * DIN MIDI OUT. No WiFi, no Bluetooth. Minimal hardware.
 *
 * How it works
 * ------------
 * Each button sends a MIDI message. Every button has TWO actions:
 * a SHORT press and a LONG press, each independently configurable.
 * Two buttons pressed together (a COMBO) can send a third message.
 * All of it is configured over USB from a computer, and the
 * configuration is stored in EEPROM, so it survives power cycles.
 *
 * The footswitch decides what a press means. The amp (or any MIDI
 * device) only receives MIDI messages. Short/long press and combos
 * are a property of the CONTROLLER, not of the device being
 * controlled. That is how every MIDI foot controller works.
 *
 * MIDI OUT uses SoftwareSerial (TX on D10) so the hardware UART
 * (D0/D1, USB) stays free for the configuration protocol.
 *
 * Configuration protocol (USB Serial, 115200 baud, one command per line):
 *   PING                          -> PONG
 *   HELP                          -> list commands
 *   GET                           -> dump the config as commands
 *   BTN <idx> <SHORT|LONG> <PC|CC|NONE> [num] [value] [TRIG|TOG]
 *   COMBO <slot> <a> <b> <PC|CC|NONE> [num] [value] [TRIG|TOG]
 *   COMBO <slot> OFF              -> disable a combo slot
 *   EXP <cc> <invert 0|1> <deadband>
 *   CHAN <1-16>                   -> MIDI channel
 *   LONGMS <ms>                   -> long-press threshold (default 500)
 *   COMBOMS <ms>                  -> combo window (default 100)
 *   SAVE                          -> write config to EEPROM
 *   DEFAULTS                      -> restore factory defaults in RAM
 *
 * Action modes (CC only):
 *   TRIG  send the value every time (bank, tuner, tap tempo)
 *   TOG   alternate value / 0 on each press (effect on/off)
 *
 * MIDI implementation (official REACTOR 50 & 100 User Manual v1.0):
 *   All messages on MIDI Channel 1 (configurable).
 *   Presets:  Program Change 0-7
 *   Effects:  CC 0 Gate, CC 1 Comp, CC 2 Drive, CC 3 Wah, CC 4 EQ,
 *             CC 5 Delay, CC 6 Mod, CC 7 Reverb, CC 10 FX Loop
 *   Bank:     CC 15 | Tuner: CC 35 | Tap Tempo: CC 36
 *   Output Volume: CC 30 (continuous) | Line Out: CC 31 | Send: CC 32
 *   Amp slots: CC 21-26
 *
 * Wiring (v2 — note Bank/Tuner moved vs the simple v1 sketch):
 *   MIDI OUT (DIN 5-pin, solder side):
 *     DIN pin 5 -- 220R -- Nano D10 (SoftwareSerial TX)
 *     DIN pin 4 -- 220R -- Nano 5V
 *     DIN pin 2 -- Nano GND
 *     DIN pins 1, 3 -- not connected
 *   Footswitches (each between the pin and GND, INPUT_PULLUP):
 *     D2 Preset 1   D6 Effect 1 (Drive)
 *     D3 Preset 2   D7 Effect 2 (Delay)
 *     D4 Preset 3   D8 Effect 3 (Mod)
 *     D5 Preset 4   D9 Effect 4 (Reverb)
 *     D11 Bank      D13 Tuner
 *   Expression pedal (TRS jack):
 *     Tip    -- Nano A0 (wiper/signal)
 *     Ring   -- Nano 5V
 *     Sleeve -- Nano GND
 *     A0 -- 100k resistor -- GND (pull-down)
 *   Preset LEDs (optional):
 *     A1 Preset 1, A2 Preset 2, A3 Preset 3, A4 Preset 4
 *     (LED anode to the pin, cathode through 220-330R to GND)
 *
 * Power: USB cable (5V) or 9V battery into VIN. The amp's MIDI IN
 * does not supply power.
 *
 * License: MIT
 */

#include <SoftwareSerial.h>
#include <EEPROM.h>

// ---------- MIDI OUT (SoftwareSerial, TX on D10) ----------
// RX pin (D12) is not connected; this port is transmit-only.
SoftwareSerial midiSerial(12, 10);

// ---------- Action model ----------
#define ACT_NONE 0
#define ACT_PC   1
#define ACT_CC   2

#define MODE_TRIG 0  // send the value every time
#define MODE_TOG  1  // alternate value / 0 on each press

struct ButtonAction {
  byte type;    // ACT_NONE, ACT_PC, ACT_CC
  byte mode;    // MODE_TRIG, MODE_TOG (CC only)
  byte number;  // PC number or CC number
  byte value;   // CC value
};

struct Combo {
  byte btnA;  // button index 0-9, 255 = slot disabled
  byte btnB;
  ButtonAction action;
};

#define CONFIG_VERSION 1
#define NUM_BUTTONS 10
#define NUM_COMBOS 4

struct Config {
  char magic[2];  // 'R','S'
  byte version;
  byte midiChannel;       // 1-16
  uint16_t longPressMs;   // default 500
  uint16_t comboWindowMs; // default 100
  byte expCC;             // default 30 (Output Volume)
  byte expInvert;         // 0 or 1
  byte expDeadband;       // default 2
  ButtonAction btnShort[NUM_BUTTONS];
  ButtonAction btnLong[NUM_BUTTONS];
  Combo combos[NUM_COMBOS];
};

Config cfg;

// ---------- Pins ----------
const byte BTN_PINS[NUM_BUTTONS] = {2, 3, 4, 5, 6, 7, 8, 9, 11, 13};
const byte PIN_EXP = A0;
const byte LED_PINS[4] = {A1, A2, A3, A4};

// ---------- Runtime state ----------
struct BtnState {
  byte stable;              // debounced level (HIGH = released)
  byte reading;             // raw level
  unsigned long changedAt;  // last raw change (debounce)
  unsigned long pressStart; // debounced press time
  bool pending;             // pressed, action not yet fired
  bool longFired;           // long-press action already fired
  bool togShort;            // toggle state, short-press CC
  bool togLong;             // toggle state, long-press CC
};
BtnState btn[NUM_BUTTONS];
bool togCombo[NUM_COMBOS];

byte currentPreset = 0;  // 0-3, position inside the bank (for the LEDs)
int lastExp = -1;

const unsigned long DEBOUNCE_MS = 25;
const unsigned long EXP_READ_MS = 10;

// ---------- Factory defaults ----------
void loadDefaults() {
  cfg.magic[0] = 'R';
  cfg.magic[1] = 'S';
  cfg.version = CONFIG_VERSION;
  cfg.midiChannel = 1;
  cfg.longPressMs = 500;
  cfg.comboWindowMs = 100;
  cfg.expCC = 30;
  cfg.expInvert = 0;
  cfg.expDeadband = 2;

  // Short press: presets 1-4 (PC 0-3), effects, bank, tuner.
  // Long press on a preset button: same preset in the Green bank (PC 4-7).
  ButtonAction none = {ACT_NONE, MODE_TRIG, 0, 0};
  for (byte i = 0; i < NUM_BUTTONS; i++) {
    cfg.btnShort[i] = none;
    cfg.btnLong[i] = none;
  }
  for (byte i = 0; i < 4; i++) {
    cfg.btnShort[i] = {ACT_PC, MODE_TRIG, i, 0};
    cfg.btnLong[i] = {ACT_PC, MODE_TRIG, (byte)(4 + i), 0};
  }
  // Effect toggles: Drive, Delay, Mod, Reverb.
  const byte fxCC[4] = {2, 5, 6, 7};
  for (byte i = 0; i < 4; i++) {
    cfg.btnShort[4 + i] = {ACT_CC, MODE_TOG, fxCC[i], 127};
  }
  cfg.btnShort[8] = {ACT_CC, MODE_TRIG, 15, 127};  // Bank
  cfg.btnShort[9] = {ACT_CC, MODE_TRIG, 35, 127};  // Tuner

  // Combo example: buttons 1+2 together = Tap Tempo.
  for (byte i = 0; i < NUM_COMBOS; i++) {
    cfg.combos[i].btnA = 255;
    cfg.combos[i].btnB = 255;
    cfg.combos[i].action = none;
  }
  cfg.combos[0].btnA = 0;
  cfg.combos[0].btnB = 1;
  cfg.combos[0].action = {ACT_CC, MODE_TRIG, 36, 127};  // Tap Tempo
}

// ---------- EEPROM ----------
void loadConfig() {
  EEPROM.get(0, cfg);
  if (cfg.magic[0] != 'R' || cfg.magic[1] != 'S' ||
      cfg.version != CONFIG_VERSION) {
    loadDefaults();
  }
}

void saveConfig() {
  EEPROM.put(0, cfg);
}

// ---------- MIDI send ----------
void sendPC(byte program) {
  midiSerial.write(0xC0 | ((cfg.midiChannel - 1) & 0x0F));
  midiSerial.write(program & 0x7F);
}

void sendCC(byte cc, byte value) {
  midiSerial.write(0xB0 | ((cfg.midiChannel - 1) & 0x0F));
  midiSerial.write(cc & 0x7F);
  midiSerial.write(value & 0x7F);
}

// ---------- LEDs ----------
void updatePresetLeds() {
  for (byte i = 0; i < 4; i++) {
    digitalWrite(LED_PINS[i], (i == currentPreset) ? HIGH : LOW);
  }
}

// ---------- Firing actions ----------
// kind: 0 = short press, 1 = long press, 2 = combo.
// index: button index (0-9) or combo slot (0-3).
void fireAction(const ButtonAction &a, byte kind, byte index) {
  if (a.type == ACT_NONE) return;
  if (a.type == ACT_PC) {
    sendPC(a.number);
    if (a.number < 8) {
      currentPreset = a.number % 4;
      updatePresetLeds();
    }
    return;
  }
  // ACT_CC
  byte value = a.value;
  if (a.mode == MODE_TOG) {
    bool *state;
    if (kind == 0) state = &btn[index].togShort;
    else if (kind == 1) state = &btn[index].togLong;
    else state = &togCombo[index];
    value = *state ? 0 : a.value;
    *state = !*state;
  }
  sendCC(a.number, value);
}

// ---------- Button state machine ----------
void checkCombo(byte justPressed, unsigned long now) {
  for (byte j = 0; j < NUM_BUTTONS; j++) {
    if (j == justPressed) continue;
    if (!btn[j].pending) continue;
    if ((now - btn[j].pressStart) > cfg.comboWindowMs) continue;
    for (byte c = 0; c < NUM_COMBOS; c++) {
      Combo &combo = cfg.combos[c];
      if (combo.btnA == 255) continue;
      if ((combo.btnA == j && combo.btnB == justPressed) ||
          (combo.btnA == justPressed && combo.btnB == j)) {
        fireAction(combo.action, 2, c);
        btn[j].pending = false;
        btn[justPressed].pending = false;
        return;
      }
    }
  }
}

void updateButtons() {
  unsigned long now = millis();

  for (byte i = 0; i < NUM_BUTTONS; i++) {
    byte reading = digitalRead(BTN_PINS[i]);
    if (reading != btn[i].reading) {
      btn[i].changedAt = now;
      btn[i].reading = reading;
    }
    if ((now - btn[i].changedAt) > DEBOUNCE_MS && reading != btn[i].stable) {
      btn[i].stable = reading;
      if (reading == LOW) {
        // Fresh press.
        btn[i].pressStart = now;
        btn[i].pending = true;
        btn[i].longFired = false;
        checkCombo(i, now);
      } else {
        // Release: short press, unless the long press already fired
        // or this press was consumed by a combo.
        if (btn[i].pending && !btn[i].longFired) {
          fireAction(cfg.btnShort[i], 0, i);
        }
        btn[i].pending = false;
      }
    }
  }

  // Long-press detection for buttons still held down.
  for (byte i = 0; i < NUM_BUTTONS; i++) {
    if (btn[i].pending && !btn[i].longFired && btn[i].stable == LOW &&
        (now - btn[i].pressStart) >= cfg.longPressMs) {
      btn[i].longFired = true;
      fireAction(cfg.btnLong[i], 1, i);
    }
  }
}

// ---------- Expression pedal ----------
void updateExpression() {
  static unsigned long lastRead = 0;
  unsigned long now = millis();
  if (now - lastRead < EXP_READ_MS) return;
  lastRead = now;

  int value = analogRead(PIN_EXP) >> 3;  // 0-1023 -> 0-127
  if (cfg.expInvert) value = 127 - value;

  if (abs(value - lastExp) >= cfg.expDeadband) {
    sendCC(cfg.expCC, (byte)value);
    lastExp = value;
  }
}

// ---------- Config protocol (USB Serial) ----------
#define CMD_BUF_SIZE 96
char cmdBuf[CMD_BUF_SIZE];
byte cmdLen = 0;

const char *actionTypeName(byte t) {
  if (t == ACT_PC) return "PC";
  if (t == ACT_CC) return "CC";
  return "NONE";
}

void printAction(const ButtonAction &a) {
  Serial.print(actionTypeName(a.type));
  if (a.type == ACT_PC) {
    Serial.print(' ');
    Serial.print(a.number);
  } else if (a.type == ACT_CC) {
    Serial.print(' ');
    Serial.print(a.number);
    Serial.print(' ');
    Serial.print(a.value);
    Serial.print(a.mode == MODE_TOG ? " TOG" : " TRIG");
  }
}

void dumpConfig() {
  Serial.print("CHAN ");
  Serial.println(cfg.midiChannel);
  Serial.print("LONGMS ");
  Serial.println(cfg.longPressMs);
  Serial.print("COMBOMS ");
  Serial.println(cfg.comboWindowMs);
  Serial.print("EXP ");
  Serial.print(cfg.expCC);
  Serial.print(' ');
  Serial.print(cfg.expInvert);
  Serial.print(' ');
  Serial.println(cfg.expDeadband);
  for (byte i = 0; i < NUM_BUTTONS; i++) {
    Serial.print("BTN ");
    Serial.print(i);
    Serial.print(" SHORT ");
    printAction(cfg.btnShort[i]);
    Serial.println();
    Serial.print("BTN ");
    Serial.print(i);
    Serial.print(" LONG ");
    printAction(cfg.btnLong[i]);
    Serial.println();
  }
  for (byte c = 0; c < NUM_COMBOS; c++) {
    Serial.print("COMBO ");
    Serial.print(c);
    if (cfg.combos[c].btnA == 255) {
      Serial.println(" OFF");
    } else {
      Serial.print(' ');
      Serial.print(cfg.combos[c].btnA);
      Serial.print(' ');
      Serial.print(cfg.combos[c].btnB);
      Serial.print(' ');
      printAction(cfg.combos[c].action);
      Serial.println();
    }
  }
  Serial.println("END");
}

// Parse "PC|CC|NONE [num] [value] [TRIG|TOG]" starting at token index t.
// Returns false on bad input.
bool parseAction(char *tokens[], byte ntok, byte t, ButtonAction &a) {
  a.type = ACT_NONE;
  a.mode = MODE_TRIG;
  a.number = 0;
  a.value = 0;
  if (t >= ntok) return false;
  if (strcmp(tokens[t], "NONE") == 0) return true;
  if (strcmp(tokens[t], "PC") == 0) {
    if (t + 1 >= ntok) return false;
    a.type = ACT_PC;
    a.number = (byte)atoi(tokens[t + 1]);
    return true;
  }
  if (strcmp(tokens[t], "CC") == 0) {
    if (t + 2 >= ntok) return false;
    a.type = ACT_CC;
    a.number = (byte)atoi(tokens[t + 1]);
    a.value = (byte)atoi(tokens[t + 2]);
    if (t + 3 < ntok && strcmp(tokens[t + 3], "TOG") == 0) {
      a.mode = MODE_TOG;
    }
    return true;
  }
  return false;
}

void printHelp() {
  Serial.println("Commands (one per line):");
  Serial.println(" PING");
  Serial.println(" GET");
  Serial.println(" BTN <idx> <SHORT|LONG> <PC|CC|NONE> [num] [value] [TRIG|TOG]");
  Serial.println(" COMBO <slot> <a> <b> <PC|CC|NONE> [num] [value] [TRIG|TOG]");
  Serial.println(" COMBO <slot> OFF");
  Serial.println(" EXP <cc> <invert 0|1> <deadband>");
  Serial.println(" CHAN <1-16>");
  Serial.println(" LONGMS <ms>");
  Serial.println(" COMBOMS <ms>");
  Serial.println(" SAVE");
  Serial.println(" DEFAULTS");
  Serial.println(" HELP");
}

void handleCommand(char *line) {
  // Tokenise by spaces.
  char *tokens[10];
  byte ntok = 0;
  char *tok = strtok(line, " ");
  while (tok != NULL && ntok < 10) {
    tokens[ntok++] = tok;
    tok = strtok(NULL, " ");
  }
  if (ntok == 0) return;

  if (strcmp(tokens[0], "PING") == 0) {
    Serial.println("PONG");
  } else if (strcmp(tokens[0], "HELP") == 0) {
    printHelp();
  } else if (strcmp(tokens[0], "GET") == 0) {
    dumpConfig();
  } else if (strcmp(tokens[0], "SAVE") == 0) {
    saveConfig();
    Serial.println("OK SAVED");
  } else if (strcmp(tokens[0], "DEFAULTS") == 0) {
    loadDefaults();
    Serial.println("OK DEFAULTS");
  } else if (strcmp(tokens[0], "CHAN") == 0 && ntok >= 2) {
    int ch = atoi(tokens[1]);
    if (ch >= 1 && ch <= 16) {
      cfg.midiChannel = (byte)ch;
      Serial.println("OK");
    } else {
      Serial.println("ERR channel 1-16");
    }
  } else if (strcmp(tokens[0], "LONGMS") == 0 && ntok >= 2) {
    cfg.longPressMs = (uint16_t)atoi(tokens[1]);
    Serial.println("OK");
  } else if (strcmp(tokens[0], "COMBOMS") == 0 && ntok >= 2) {
    cfg.comboWindowMs = (uint16_t)atoi(tokens[1]);
    Serial.println("OK");
  } else if (strcmp(tokens[0], "EXP") == 0 && ntok >= 4) {
    cfg.expCC = (byte)atoi(tokens[1]);
    cfg.expInvert = (byte)atoi(tokens[2]);
    cfg.expDeadband = (byte)atoi(tokens[3]);
    Serial.println("OK");
  } else if (strcmp(tokens[0], "BTN") == 0 && ntok >= 4) {
    byte idx = (byte)atoi(tokens[1]);
    if (idx >= NUM_BUTTONS) {
      Serial.println("ERR button 0-9");
      return;
    }
    bool isLong;
    if (strcmp(tokens[2], "SHORT") == 0) isLong = false;
    else if (strcmp(tokens[2], "LONG") == 0) isLong = true;
    else {
      Serial.println("ERR SHORT or LONG");
      return;
    }
    ButtonAction a;
    if (!parseAction(tokens, ntok, 3, a)) {
      Serial.println("ERR bad action");
      return;
    }
    if (isLong) cfg.btnLong[idx] = a;
    else cfg.btnShort[idx] = a;
    Serial.println("OK");
  } else if (strcmp(tokens[0], "COMBO") == 0 && ntok >= 2) {
    byte slot = (byte)atoi(tokens[1]);
    if (slot >= NUM_COMBOS) {
      Serial.println("ERR combo 0-3");
      return;
    }
    if (ntok >= 3 && strcmp(tokens[2], "OFF") == 0) {
      cfg.combos[slot].btnA = 255;
      cfg.combos[slot].btnB = 255;
      cfg.combos[slot].action.type = ACT_NONE;
      Serial.println("OK");
      return;
    }
    if (ntok < 6) {
      Serial.println("ERR COMBO <slot> <a> <b> <action>");
      return;
    }
    byte a = (byte)atoi(tokens[2]);
    byte b = (byte)atoi(tokens[3]);
    if (a >= NUM_BUTTONS || b >= NUM_BUTTONS || a == b) {
      Serial.println("ERR buttons 0-9, a != b");
      return;
    }
    ButtonAction act;
    if (!parseAction(tokens, ntok, 4, act)) {
      Serial.println("ERR bad action");
      return;
    }
    cfg.combos[slot].btnA = a;
    cfg.combos[slot].btnB = b;
    cfg.combos[slot].action = act;
    Serial.println("OK");
  } else {
    Serial.println("ERR unknown command, send HELP");
  }
}

void processSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdLen > 0) {
        cmdBuf[cmdLen] = '\0';
        handleCommand(cmdBuf);
        cmdLen = 0;
      }
    } else if (cmdLen < CMD_BUF_SIZE - 1) {
      cmdBuf[cmdLen++] = c;
    }
  }
}

// ---------- Setup / loop ----------
void setup() {
  Serial.begin(115200);  // USB config protocol
  midiSerial.begin(31250);  // MIDI OUT

  loadConfig();

  for (byte i = 0; i < NUM_BUTTONS; i++) {
    pinMode(BTN_PINS[i], INPUT_PULLUP);
    btn[i].stable = HIGH;
    btn[i].reading = HIGH;
    btn[i].changedAt = 0;
    btn[i].pressStart = 0;
    btn[i].pending = false;
    btn[i].longFired = false;
    btn[i].togShort = false;
    btn[i].togLong = false;
  }
  for (byte c = 0; c < NUM_COMBOS; c++) {
    togCombo[c] = false;
  }

  for (byte i = 0; i < 4; i++) {
    pinMode(LED_PINS[i], OUTPUT);
  }
  updatePresetLeds();

  // Settle the expression pedal reading so we do not send a spurious
  // volume message at startup (e.g. when no pedal is plugged in).
  delay(100);
  lastExp = analogRead(PIN_EXP) >> 3;
  if (cfg.expInvert) lastExp = 127 - lastExp;
}

void loop() {
  updateButtons();
  updateExpression();
  processSerial();
}
