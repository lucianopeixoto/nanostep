#!/usr/bin/env python3
"""NanoStep configurator.

USB serial config tool for the NanoStep MIDI foot controller
(Arduino Nano). Talks to the pedal over USB at 115200 baud using the
pedal's text command protocol. No other dependencies besides pyserial:

    pip install pyserial

Usage:
    python configure.py --list
    python configure.py --port COM3 --get
    python configure.py --port COM3 --get --out config.json
    python configure.py --port COM3 --set config.json
    python configure.py --port COM3 --defaults

Config JSON format (see example-config.json):
    {
      "midiChannel": 1,
      "longPressMs": 500,
      "comboWindowMs": 100,
      "expression": {"cc": 30, "invert": false, "deadband": 2},
      "buttons": [
        {"short": {"type": "PC", "number": 0},
         "long":  {"type": "PC", "number": 4}},
        ...
      ],
      "combos": [
        {"buttons": [0, 1],
         "action": {"type": "CC", "number": 36, "value": 127, "mode": "TRIG"}},
        ...
      ]
    }

Action types: "PC", "CC", "NONE".
CC modes: "TRIG" (send the value every time) or "TOG" (alternate
value / 0 on each press). PC ignores value and mode.
"""

import argparse
import json
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("pyserial is required: pip install pyserial", file=sys.stderr)
    sys.exit(1)


BAUD = 115200


def list_ports():
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return
    for p in ports:
        print(f"{p.device}\t{p.description}")


class Pedal:
    def __init__(self, port):
        self.ser = serial.Serial(port, BAUD, timeout=2)
        time.sleep(0.5)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def _cmd(self, cmd, expect="OK"):
        self.ser.write((cmd + "\n").encode())
        lines = []
        deadline = time.time() + 2
        while time.time() < deadline:
            raw = self.ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if line:
                lines.append(line)
            if line == expect or line.startswith("ERR") or line == "END":
                break
        return lines

    def ping(self):
        lines = self._cmd("PING", expect="PONG")
        return "PONG" in lines

    def get_config(self):
        self.ser.write(b"GET\n")
        lines = []
        deadline = time.time() + 3
        while time.time() < deadline:
            raw = self.ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if line == "END":
                break
            if line:
                lines.append(line)
        return parse_config_lines(lines)

    def send_config(self, cfg):
        # Globals.
        self._cmd(f"CHAN {cfg.get('midiChannel', 1)}")
        self._cmd(f"LONGMS {cfg.get('longPressMs', 500)}")
        self._cmd(f"COMBOMS {cfg.get('comboWindowMs', 100)}")
        exp = cfg.get("expression", {})
        self._cmd(
            f"EXP {exp.get('cc', 30)} "
            f"{1 if exp.get('invert') else 0} "
            f"{exp.get('deadband', 2)}"
        )
        # Buttons.
        for idx, b in enumerate(cfg.get("buttons", [])):
            for press in ("short", "long"):
                act = b.get(press)
                if act is None:
                    continue
                self._cmd(
                    f"BTN {idx} {press.upper()} {action_to_cmd(act)}"
                )
        # Combos.
        for slot, combo in enumerate(cfg.get("combos", [])):
            if not combo:
                self._cmd(f"COMBO {slot} OFF")
                continue
            buttons = combo.get("buttons", [])
            if len(buttons) != 2:
                self._cmd(f"COMBO {slot} OFF")
                continue
            self._cmd(
                f"COMBO {slot} {buttons[0]} {buttons[1]} "
                f"{action_to_cmd(combo.get('action', {}))}"
            )
        lines = self._cmd("SAVE", expect="OK SAVED")
        return "OK SAVED" in lines

    def defaults(self):
        self._cmd("DEFAULTS")
        lines = self._cmd("SAVE", expect="OK SAVED")
        return "OK SAVED" in lines


def action_to_cmd(act):
    t = (act.get("type") or "NONE").upper()
    if t == "NONE":
        return "NONE"
    if t == "PC":
        return f"PC {int(act.get('number', 0))}"
    if t == "CC":
        mode = (act.get("mode") or "TRIG").upper()
        return f"CC {int(act.get('number', 0))} {int(act.get('value', 127))} {mode}"
    raise ValueError(f"unknown action type: {t}")


def parse_action(tokens):
    """tokens: ['PC', '0'] or ['CC', '2', '127', 'TOG'] or ['NONE']."""
    t = tokens[0].upper()
    if t == "NONE":
        return {"type": "NONE"}
    if t == "PC":
        return {"type": "PC", "number": int(tokens[1])}
    if t == "CC":
        act = {
            "type": "CC",
            "number": int(tokens[1]),
            "value": int(tokens[2]),
        }
        if len(tokens) > 3:
            act["mode"] = tokens[3].upper()
        return act
    raise ValueError(f"unknown action: {tokens}")


def parse_config_lines(lines):
    cfg = {
        "midiChannel": 1,
        "longPressMs": 500,
        "comboWindowMs": 100,
        "expression": {"cc": 30, "invert": False, "deadband": 2},
        "buttons": [
            {"short": {"type": "NONE"}, "long": {"type": "NONE"}}
            for _ in range(10)
        ],
        "combos": [None, None, None, None],
    }
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "CHAN":
            cfg["midiChannel"] = int(parts[1])
        elif parts[0] == "LONGMS":
            cfg["longPressMs"] = int(parts[1])
        elif parts[0] == "COMBOMS":
            cfg["comboWindowMs"] = int(parts[1])
        elif parts[0] == "EXP":
            cfg["expression"] = {
                "cc": int(parts[1]),
                "invert": bool(int(parts[2])),
                "deadband": int(parts[3]),
            }
        elif parts[0] == "BTN":
            idx = int(parts[1])
            press = parts[2].lower()
            cfg["buttons"][idx][press] = parse_action(parts[3:])
        elif parts[0] == "COMBO":
            slot = int(parts[1])
            if parts[2] == "OFF":
                cfg["combos"][slot] = None
            else:
                cfg["combos"][slot] = {
                    "buttons": [int(parts[2]), int(parts[3])],
                    "action": parse_action(parts[4:]),
                }
    return cfg


def main():
    ap = argparse.ArgumentParser(description="NanoStep configurator")
    ap.add_argument("--port", help="serial port, e.g. COM3 or /dev/ttyUSB0")
    ap.add_argument("--list", action="store_true", help="list serial ports")
    ap.add_argument("--get", action="store_true", help="read config from pedal")
    ap.add_argument("--set", metavar="FILE", help="write config from JSON file")
    ap.add_argument("--out", metavar="FILE", help="save --get output to JSON file")
    ap.add_argument("--defaults", action="store_true",
                    help="restore factory defaults on the pedal")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return

    if not args.port:
        ap.error("--port is required (or use --list to find it)")

    pedal = Pedal(args.port)
    try:
        if not pedal.ping():
            print("No reply from the pedal. Is it connected and powered?",
                  file=sys.stderr)
            sys.exit(1)

        if args.defaults:
            if pedal.defaults():
                print("Factory defaults restored and saved.")
            else:
                print("Failed to save defaults.", file=sys.stderr)
                sys.exit(1)
            return

        if args.set:
            with open(args.set) as f:
                cfg = json.load(f)
            if pedal.send_config(cfg):
                print(f"Config from {args.set} written and saved.")
            else:
                print("Failed to save config.", file=sys.stderr)
                sys.exit(1)
            return

        if args.get:
            cfg = pedal.get_config()
            text = json.dumps(cfg, indent=2)
            if args.out:
                with open(args.out, "w") as f:
                    f.write(text + "\n")
                print(f"Config saved to {args.out}")
            else:
                print(text)
            return

        ap.error("nothing to do: use --get, --set or --defaults")
    finally:
        pedal.close()


if __name__ == "__main__":
    main()
