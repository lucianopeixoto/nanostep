# NanoStep

Configurable DIY MIDI foot controller based on the Arduino Nano.

10 footswitches, expression pedal input, wired 5-pin DIN MIDI OUT.
No WiFi, no Bluetooth. Minimal hardware, maximum flexibility: every
button is configurable over USB, and the configuration lives in EEPROM,
so it survives power cycles. It works with any MIDI device, an amp, a
multi-effects unit, a DAW, a looper. The factory default is set up for
the Positive Grid REACTOR 50 / REACTOR 100, but nothing in the design
is tied to it. Change the PC and CC numbers in the configurator and it
drives anything that speaks MIDI.

## What it does

- **10 buttons**, each with a **short press** and a **long press** action.
- **Button combinations**: press two buttons together to send a third
  message (e.g. buttons 1+2 = tuner).
- **Expression pedal** input (TRS jack) for continuous control.
- **USB configuration**: a Python tool (and the plain text protocol it
  speaks) lets you reassign every button, combo, and the expression
  pedal without re-flashing the firmware.

The footswitch decides what a press means. The amp only receives MIDI
messages. Short/long press and combos are a property of the controller,
not of the device being controlled. That is how every MIDI foot
controller works, from the Behringer FCB1010 to the Morningstar series.

## Default layout

| Button | Short press | Long press |
|---|---|---|
| 1-4 | Preset 1-4 (PC 0-3, Red bank) | Preset 5-8 (PC 4-7, Green bank) |
| 5-8 | Toggle Drive, Delay, Mod, Reverb (CC 2, 5, 6, 7) | — |
| 9 | Bank toggle (CC 15) | — |
| 10 | Tuner (CC 35) | — |
| 1+2 | Tap Tempo (CC 36) | |
| EXP pedal | Output Volume (CC 30) | |

Everything above is just the factory default. Change it with the
configurator.

## Hardware

- 1x Arduino Nano (ATmega328P, 5V)
- 10x momentary footswitches, normally open
- 1x 5-pin DIN socket, panel mount (MIDI OUT)
- 1x 1/4" TRS jack, panel mount (expression pedal)
- 2x 220 ohm resistors (MIDI OUT)
- 1x 100k ohm resistor (expression pedal pull-down)
- 4x LEDs + 4x 220-330 ohm resistors (optional preset indicators)
- USB cable for power (or 9V battery into VIN)
- Enclosure, hookup wire, MIDI cable (5-pin DIN to 5-pin DIN)

## Wiring

### MIDI OUT (DIN 5-pin socket, solder side)

```
DIN pin 5 -- 220R -- Nano D10 (SoftwareSerial TX)
DIN pin 4 -- 220R -- Nano 5V
DIN pin 2 -- Nano GND
DIN pins 1, 3 -- not connected
```

### Footswitches (each between the pin and GND, INPUT_PULLUP)

```
D2  Preset 1        D6  Effect 1 (Drive)
D3  Preset 2        D7  Effect 2 (Delay)
D4  Preset 3        D8  Effect 3 (Mod)
D5  Preset 4        D9  Effect 4 (Reverb)
D11 Bank            D13 Tuner
```

### Expression pedal (TRS jack)

```
Tip    -- Nano A0 (wiper/signal)
Ring   -- Nano 5V
Sleeve -- Nano GND
A0 -- 100k resistor -- GND (pull-down, stops A0 floating with no pedal)
```

If the pedal reads backwards (toe down = quiet), flip the pedal's
polarity switch or set invert in the configurator. The M-Audio EX-P
has a polarity switch and works well here.

### Preset LEDs (optional)

```
A1 Preset 1, A2 Preset 2, A3 Preset 3, A4 Preset 4
LED anode to the pin, cathode through a 220-330R resistor to GND.
```

### Power

USB cable (5V) or a 9V battery into VIN. The amp's MIDI IN port does
not supply power.

## Firmware

`firmware/nanostep/nanostep.ino`. Open it in the Arduino IDE,
select Arduino Nano (ATmega328P), upload. No libraries needed besides
the built-in SoftwareSerial and EEPROM.

MIDI OUT uses SoftwareSerial (TX on D10) so the hardware UART (USB)
stays free for configuration. The hardware UART is still the more
robust MIDI path; if you do not need USB configuration, the simpler
`reactor-footswitch` sketch (hardware UART MIDI, fixed functions) is
the alternative.

## Configurator

`config/configure.py` (needs `pip install pyserial`).

```
python configure.py --list
python configure.py --port COM3 --get
python configure.py --port COM3 --get --out config.json
python configure.py --port COM3 --set config.json
python configure.py --port COM3 --defaults
```

The pedal speaks a plain text protocol over USB serial (115200 baud),
one command per line. You can also talk to it by hand from the Arduino
Serial Monitor. Send `HELP` for the command list. The protocol is
documented in the header comment of the sketch.

Config JSON format: see `config/example-config.json`. Action types are
`PC`, `CC`, and `NONE`. CC actions have a mode: `TRIG` (send the value
every time, for bank/tuner/tap tempo) or `TOG` (alternate value / 0 on
each press, for effect on/off).

## MIDI reference (REACTOR 50 & 100 User Manual v1.0, p.14)

All messages on MIDI Channel 1 (configurable).

| Action | Type | Number |
|---|---|---|
| Preset slot 1-8 | Program Change | 0-7 |
| Noise Gate / Compressor / Drive / Wah / EQ / Delay / Mod / Reverb | CC | 0-7 |
| FX Loop on/off | CC | 10 |
| Bank toggle | CC | 15 |
| Amp slot Clean/Warm/Grit/Crunch/Hi-Gain/Extreme | CC | 21-26 |
| Push / Smooth | CC | 27 / 28 |
| Heat + / Heat - | CC | 12 / 13 |
| Output Volume (continuous) | CC | 30 |
| Line Out Volume / Send Volume | CC | 31 / 32 |
| Tuner toggle | CC | 35 |
| Tap Tempo | CC | 36 |

## Also works with: Line 6 Flextone II

The Flextone II (2000) has a standard 5-pin DIN MIDI In/Out, and
Line 6 published the full MIDI spec ("Flextone II Midi / Sysex
Specification and Notes", 2000-04-03). So the same hardware drives it,
just with a different config. Load
`config/example-config-flextone-ii.json` with the configurator and the
pedal becomes a Flextone II controller. No tap tempo on this amp (the
delay time is set by CC 30/62 coarse/fine), so the 1+2 combo is off in
that config.

Flextone II layout in that config:

| Button | Short press | Long press |
|---|---|---|
| 1-4 | Channel 1-4 (PC 0-3) | Channel 5-8 (PC 4-7) |
| 5-8 | Toggle Distortion, Delay, Reverb, Tremolo/Rotary (CC 25, 28, 36, 50) | — |
| 9 | Noise Gate toggle (CC 22) | — |
| 10 | EQ toggle (CC 27) | — |
| EXP pedal | Wah position (CC 4) | |

The big difference from the Reactor: the Flextone II **does** accept
Wah position over MIDI. CC 4 is the Wah Level (0-127), so the
expression pedal input becomes a real Wah pedal on this amp. CC 7 is
the Volume Pedal level if you would rather have volume. Other useful
CCs from the Line 6 spec: Amp Model CC 12 (0-31), Drive CC 13,
Bass CC 14, Mid CC 15, Treble CC 16, Presence CC 21, Channel Volume
CC 17, Effects Select CC 19, Effects Tweak CC 1, Bright Switch CC 73.
Effect on/off is 0-63 = off, 64-127 = on. Program Changes 0-35 select
the 36 stored programs (4 onboard channels plus 32 with the Floor
Board). MIDI channel 1 by default; if the amp ignores the pedal,
check the amp's MIDI channel setting.

This is also the proof that the generic name was the right call. One
pedal, two amps, just a different JSON.

## Known limitations

### Wah sweep is not available over DIN MIDI

The manual's MIDI chart has no CC for Wah sweep or Wah position. Wah
on/off works over MIDI (CC 3), but the Wah sweep can only be driven by
an expression pedal plugged into the official REACTOR Control
footswitch (its own TRS input, proprietary link). So the expression
pedal input on this controller drives Output Volume (CC 30) by default.
Use `wah-test/` to check empirically whether any undocumented CC moves
the Wah. If Positive Grid adds a Wah position CC in a future firmware
update, point the expression pedal at it in the configurator.

### The amp sends nothing back

The Reactor has a MIDI IN port only. No MIDI OUT or THRU, so the amp
sends no state back. The firmware tracks the bank, the active preset,
and the effect toggle states locally and drives the preset LEDs from
that tracking. This works as long as the footswitch is the only thing
changing presets and effects. If you change a preset or an effect from
the amp panel or the app, the footswitch's tracking gets out of sync;
press the buttons on the footswitch again to line it up. This is the
same limitation every standard DIN MIDI controller has with the
Reactor. Only the official REACTOR Control gets two-way feedback, over
its proprietary Bluetooth/TRS link, which is undocumented.

## Wah test

`wah-test/wah-test.ino` sweeps every unassigned MIDI CC to find out
whether any of them moves the Wah position. See its header comment for
instructions. If no CC moves the Wah, DIN MIDI really cannot control
Wah position.

## Future work: reverse engineering the REACTOR Control protocol

The DIN MIDI route cannot do Wah sweep or two-way state, but the
official REACTOR Control does both over Bluetooth (BLE) or the wired
TRS link, so the amp clearly accepts a Wah position message and sends
state back over that proprietary link.

Precedent: the Positive Grid Spark 40's Bluetooth protocol was fully
reverse engineered by the community (Paul Hamshere's "Spark Protocol
Description", msgpack payloads in SysEx-like 0xf001...0xf7 frames,
two-way). No public Reactor reverse engineering has surfaced yet.

The practical path is to sniff the REACTOR app to amp BLE link. First
step, free and five minutes: open the nRF Connect app on a phone, scan,
and list the amp's advertised GATT services and characteristics. From
there, a BLE sniffer (nRF52840 dongle) or decompiling the Android APK
(jadx) can reveal the message that sets Wah position. Possible
obstacle: the BLE link may be encrypted, in which case the APK route is
the way in. If the protocol is cracked, the footswitch grows a BLE
radio (ESP32) and gains Wah sweep plus true two-way LED state.

## License

MIT. Build it, mod it, share it.
