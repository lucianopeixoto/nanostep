#!/usr/bin/env python3
"""NanoStep Companion, graphical version.

A simple Tkinter GUI for the NanoStep MIDI foot controller. Same
protocol and same config as the CLI (configure.py in this folder),
which stays available for command-line use. Works on Linux, Windows
and macOS: Tkinter ships with Python on all three, and the only extra
dependency is pyserial:

    pip install pyserial

Run:
    python configure_gui.py

Layout, FileZilla style: a connection bar on top (serial port
dropdown, connect/disconnect), the config editor in the middle, action
buttons, and a status message log at the bottom.

The editor is responsive: the buttons use two columns, and the whole
middle area scrolls vertically, so the window stays usable on
low-resolution screens. Serial work runs in a background thread so
the window stays responsive; log lines and results come back through
a queue.
"""

import json
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    import serial.tools.list_ports
except ImportError:
    tk.Tk().withdraw()
    messagebox.showerror(
        "NanoStep Companion",
        "pyserial is required.\n\nInstall it with:\n\n    pip install pyserial",
    )
    sys.exit(1)

import configure


# ---------------------------------------------------------------------------
# Serial worker (background thread)
# ---------------------------------------------------------------------------

class GuiPedal(configure.Pedal):
    """Pedal that logs every command and reply through a queue."""

    def __init__(self, port, log_queue):
        self._log_queue = log_queue
        super().__init__(port)

    def _cmd(self, cmd, expect="OK"):
        self._log_queue.put(("log", f"> {cmd}"))
        lines = super()._cmd(cmd, expect)
        for line in lines:
            self._log_queue.put(("log", f"< {line}"))
        return lines


def list_port_devices():
    """Return [(device, description)] for every serial port found."""
    found = []
    for p in serial.tools.list_ports.comports():
        found.append((p.device, p.description))
    return found


# ---------------------------------------------------------------------------
# Action editor: one PC/CC/NONE action (type, number, value, mode)
# ---------------------------------------------------------------------------

class ActionEditor:
    """Four compact widgets for one action, with type-driven enable/disable."""

    def __init__(self, parent, row, col):
        self.type_var = tk.StringVar(value="NONE")
        self.number_var = tk.IntVar(value=0)
        self.value_var = tk.IntVar(value=127)
        self.mode_var = tk.StringVar(value="TRIG")

        self.type_menu = ttk.OptionMenu(
            parent, self.type_var, "NONE", "PC", "CC", "NONE",
            command=lambda _v: self._sync(),
        )
        self.type_menu.config(width=5)
        self.number_spin = ttk.Spinbox(
            parent, from_=0, to=127, width=3, textvariable=self.number_var
        )
        self.value_spin = ttk.Spinbox(
            parent, from_=0, to=127, width=3, textvariable=self.value_var
        )
        self.mode_menu = ttk.OptionMenu(
            parent, self.mode_var, "TRIG", "TRIG", "TOG"
        )
        self.mode_menu.config(width=5)
        self.type_menu.grid(row=row, column=col, padx=1, pady=1, sticky="w")
        self.number_spin.grid(row=row, column=col + 1, padx=1, pady=1)
        self.value_spin.grid(row=row, column=col + 2, padx=1, pady=1)
        self.mode_menu.grid(row=row, column=col + 3, padx=1, pady=1, sticky="w")
        self._sync()

    def _sync(self):
        t = self.type_var.get()
        if t == "NONE":
            state = "disabled"
        else:
            state = "normal"
        self.number_spin.config(state=state)
        if t == "CC":
            self.value_spin.config(state="normal")
            self.mode_menu.config(state="normal")
        else:
            self.value_spin.config(state="disabled")
            self.mode_menu.config(state="disabled")

    def get(self):
        t = self.type_var.get()
        if t == "NONE":
            return {"type": "NONE"}
        if t == "PC":
            return {"type": "PC", "number": int(self.number_var.get())}
        return {
            "type": "CC",
            "number": int(self.number_var.get()),
            "value": int(self.value_var.get()),
            "mode": self.mode_var.get(),
        }

    def set(self, act):
        act = act or {"type": "NONE"}
        t = (act.get("type") or "NONE").upper()
        self.type_var.set(t)
        self.number_var.set(int(act.get("number", 0)))
        self.value_var.set(int(act.get("value", 127)))
        self.mode_var.set((act.get("mode") or "TRIG").upper())
        self._sync()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class CompanionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NanoStep Companion")
        self.root.minsize(780, 560)

        self.pedal = None
        self.busy = False
        self.msg_queue = queue.Queue()
        self.root.after(100, self._poll_queue)

        self._build_connection_bar()
        self._build_scroll_area()
        self._build_globals(self.scroll_frame)
        self._build_expression(self.scroll_frame)
        self._build_buttons(self.scroll_frame)
        self._build_combos(self.scroll_frame)
        self._build_actions(self.scroll_frame)
        self._build_log()

        self.refresh_ports()
        self.log("NanoStep Companion ready. Pick a port and Connect.")

    # -- layout -----------------------------------------------------------

    def _build_connection_bar(self):
        bar = ttk.LabelFrame(self.root, text="Connection")
        bar.pack(fill="x", padx=8, pady=4)

        ttk.Label(bar, text="Serial port:").grid(row=0, column=0, padx=4, pady=4)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(bar, textvariable=self.port_var, width=28)
        self.port_combo.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        self.refresh_btn = ttk.Button(bar, text="Refresh", command=self.refresh_ports)
        self.refresh_btn.grid(row=0, column=2, padx=4, pady=4)
        self.connect_btn = ttk.Button(bar, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=3, padx=4, pady=4)
        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(bar, textvariable=self.status_var, foreground="red")
        self.status_label.grid(row=0, column=4, padx=10, pady=4, sticky="w")

    def _build_scroll_area(self):
        """Scrollable middle area so the window works on low-res screens."""
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=8, pady=0)

        self.canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.scroll_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.scroll_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(
                self.canvas.find_withtag("all")[0], width=e.width
            ) if self.canvas.find_withtag("all") else None,
        )

        def on_wheel(event):
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")
            else:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.canvas.bind_all("<MouseWheel>", on_wheel)
        self.canvas.bind_all("<Button-4>", on_wheel)
        self.canvas.bind_all("<Button-5>", on_wheel)

    def _build_globals(self, parent):
        frame = ttk.LabelFrame(parent, text="Globals")
        frame.pack(fill="x", pady=4)
        ttk.Label(frame, text="MIDI channel:").grid(row=0, column=0, padx=4, pady=4)
        self.channel_var = tk.IntVar(value=1)
        ttk.Spinbox(frame, from_=1, to=16, width=4, textvariable=self.channel_var).grid(
            row=0, column=1, padx=4, pady=4
        )
        ttk.Label(frame, text="Long press (ms):").grid(row=0, column=2, padx=4, pady=4)
        self.long_ms_var = tk.IntVar(value=500)
        ttk.Spinbox(frame, from_=100, to=2000, width=6, textvariable=self.long_ms_var).grid(
            row=0, column=3, padx=4, pady=4
        )
        ttk.Label(frame, text="Combo window (ms):").grid(row=0, column=4, padx=4, pady=4)
        self.combo_ms_var = tk.IntVar(value=100)
        ttk.Spinbox(frame, from_=0, to=1000, width=6, textvariable=self.combo_ms_var).grid(
            row=0, column=5, padx=4, pady=4
        )

    def _build_expression(self, parent):
        frame = ttk.LabelFrame(parent, text="Expression pedal")
        frame.pack(fill="x", pady=4)
        ttk.Label(frame, text="CC:").grid(row=0, column=0, padx=4, pady=4)
        self.exp_cc_var = tk.IntVar(value=30)
        ttk.Spinbox(frame, from_=0, to=127, width=4, textvariable=self.exp_cc_var).grid(
            row=0, column=1, padx=4, pady=4
        )
        self.exp_invert_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Invert", variable=self.exp_invert_var).grid(
            row=0, column=2, padx=8, pady=4
        )
        ttk.Label(frame, text="Deadband:").grid(row=0, column=3, padx=4, pady=4)
        self.exp_db_var = tk.IntVar(value=2)
        ttk.Spinbox(frame, from_=0, to=20, width=4, textvariable=self.exp_db_var).grid(
            row=0, column=4, padx=4, pady=4
        )

    def _build_button_row(self, parent, row, number):
        """One button row: label + short editor + long editor."""
        ttk.Label(parent, text=f"Button {number}").grid(
            row=row, column=0, padx=4, pady=1, sticky="e"
        )
        short = ActionEditor(parent, row, 1)
        ttk.Label(parent, text="").grid(row=row, column=5, padx=2)
        long_ed = ActionEditor(parent, row, 6)
        return short, long_ed

    def _build_button_column(self, parent, numbers):
        """A column of button rows with a shared header."""
        headers = ["", "Short: type", "num", "val", "mode", "", "Long: type", "num", "val", "mode"]
        for col, text in enumerate(headers):
            ttk.Label(parent, text=text).grid(row=0, column=col, padx=1, pady=2)
        editors = []
        for i, number in enumerate(numbers):
            editors.append(self._build_button_row(parent, i + 1, number))
        return editors

    def _build_buttons(self, parent):
        frame = ttk.LabelFrame(parent, text="Buttons (short press / long press)")
        frame.pack(fill="x", pady=4)
        left = ttk.Frame(frame)
        left.pack(side="left", padx=4, pady=2)
        right = ttk.Frame(frame)
        right.pack(side="left", padx=4, pady=2)
        editors_left = self._build_button_column(left, [1, 2, 3, 4, 5])
        editors_right = self._build_button_column(right, [6, 7, 8, 9, 10])
        self.button_editors = editors_left + editors_right

    def _build_combo(self, parent, row, slot):
        """One combo row: enable + buttons A/B + action editor."""
        ttk.Label(parent, text=f"Combo {slot + 1}").grid(
            row=row, column=0, padx=4, pady=2, sticky="e"
        )
        enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="On", variable=enabled_var).grid(
            row=row, column=1, padx=2, pady=2
        )
        ttk.Label(parent, text="A:").grid(row=row, column=2, padx=2, pady=2)
        a_var = tk.IntVar(value=0)
        ttk.Spinbox(parent, from_=0, to=9, width=3, textvariable=a_var).grid(
            row=row, column=3, padx=2, pady=2
        )
        ttk.Label(parent, text="B:").grid(row=row, column=4, padx=2, pady=2)
        b_var = tk.IntVar(value=1)
        ttk.Spinbox(parent, from_=0, to=9, width=3, textvariable=b_var).grid(
            row=row, column=5, padx=2, pady=2
        )
        action = ActionEditor(parent, row, 6)
        return enabled_var, a_var, b_var, action

    def _build_combos(self, parent):
        frame = ttk.LabelFrame(parent, text="Button combinations")
        frame.pack(fill="x", pady=4)
        left = ttk.Frame(frame)
        left.pack(side="left", padx=4, pady=2)
        right = ttk.Frame(frame)
        right.pack(side="left", padx=4, pady=2)
        combos_left = [self._build_combo(left, i, i) for i in range(2)]
        combos_right = [self._build_combo(right, i, i + 2) for i in range(2)]
        self.combo_editors = combos_left + combos_right

    def _build_actions(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=4)
        self.read_btn = ttk.Button(frame, text="Read from pedal", command=self.read_config)
        self.read_btn.pack(side="left", padx=2)
        self.write_btn = ttk.Button(frame, text="Write to pedal", command=self.write_config)
        self.write_btn.pack(side="left", padx=2)
        self.defaults_btn = ttk.Button(frame, text="Factory defaults", command=self.factory_defaults)
        self.defaults_btn.pack(side="left", padx=2)
        self.load_btn = ttk.Button(frame, text="Load from file", command=self.load_file)
        self.load_btn.pack(side="left", padx=2)
        self.save_btn = ttk.Button(frame, text="Save to file", command=self.save_file)
        self.save_btn.pack(side="left", padx=2)

    def _build_log(self):
        frame = ttk.LabelFrame(self.root, text="Status")
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.log_widget = scrolledtext.ScrolledText(
            frame, height=8, state="disabled", font=("TkDefaultFont", 9)
        )
        self.log_widget.pack(fill="both", expand=True, padx=4, pady=4)
        clear_btn = ttk.Button(frame, text="Clear log", command=self.clear_log)
        clear_btn.pack(side="right", padx=4, pady=2)

    # -- status log -------------------------------------------------------

    def log(self, message):
        stamp = time.strftime("%H:%M:%S")
        self.log_widget.config(state="normal")
        self.log_widget.insert("end", f"[{stamp}] {message}\n")
        self.log_widget.see("end")
        self.log_widget.config(state="disabled")

    def clear_log(self):
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.config(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "config":
                    self.set_config(payload)
                    self.log("Config loaded into the editor.")
                elif kind == "done":
                    self._set_busy(False)
                    if payload:
                        self.log(payload)
                elif kind == "error":
                    self._set_busy(False)
                    self.log(f"ERROR: {payload}")
                    messagebox.showerror("NanoStep Companion", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self.read_btn, self.write_btn, self.defaults_btn,
                    self.load_btn, self.save_btn, self.connect_btn):
            btn.config(state=state)

    def _run_in_thread(self, func):
        self._set_busy(True)
        thread = threading.Thread(target=func, daemon=True)
        thread.start()

    # -- connection -------------------------------------------------------

    def refresh_ports(self):
        ports = list_port_devices()
        devices = [device for device, _desc in ports]
        self.port_combo["values"] = devices
        if devices and not self.port_var.get():
            self.port_var.set(devices[0])
        if ports:
            for device, desc in ports:
                self.log(f"Found port {device} ({desc})")
        else:
            self.log("No serial ports found. Is the Nano connected?")

    def connect(self):
        if self.pedal is not None:
            self.disconnect()
            return
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("NanoStep Companion", "Pick a serial port first.")
            return
        self.log(f"Connecting to {port} ...")

        def work():
            try:
                pedal = GuiPedal(port, self.msg_queue)
            except Exception as exc:
                self.msg_queue.put(("error", f"Could not open {port}: {exc}"))
                return
            try:
                if pedal.ping():
                    self.pedal = pedal
                    self.msg_queue.put(("log", f"Connected to {port}. Pedal answered PING."))
                    self.msg_queue.put(("done", None))
                    self.root.after(0, self._show_connected)
                else:
                    pedal.close()
                    self.msg_queue.put(("error", "No reply from the pedal. Is it the NanoStep firmware?"))
            except Exception as exc:
                try:
                    pedal.close()
                except Exception:
                    pass
                self.msg_queue.put(("error", f"Connection failed: {exc}"))

        self._run_in_thread(work)

    def _show_connected(self):
        self.status_var.set("Connected")
        self.status_label.config(foreground="green")
        self.connect_btn.config(text="Disconnect")

    def disconnect(self):
        if self.pedal is not None:
            try:
                self.pedal.close()
            except Exception:
                pass
            self.pedal = None
        self.status_var.set("Disconnected")
        self.status_label.config(foreground="red")
        self.connect_btn.config(text="Connect")
        self.log("Disconnected.")

    # -- config get/set ---------------------------------------------------

    def get_config(self):
        return {
            "midiChannel": int(self.channel_var.get()),
            "longPressMs": int(self.long_ms_var.get()),
            "comboWindowMs": int(self.combo_ms_var.get()),
            "expression": {
                "cc": int(self.exp_cc_var.get()),
                "invert": bool(self.exp_invert_var.get()),
                "deadband": int(self.exp_db_var.get()),
            },
            "buttons": [
                {"short": short.get(), "long": long_ed.get()}
                for short, long_ed in self.button_editors
            ],
            "combos": [
                (
                    {"buttons": [int(a_var.get()), int(b_var.get())],
                     "action": action.get()}
                    if enabled_var.get()
                    else None
                )
                for enabled_var, a_var, b_var, action in self.combo_editors
            ],
        }

    def set_config(self, cfg):
        self.channel_var.set(int(cfg.get("midiChannel", 1)))
        self.long_ms_var.set(int(cfg.get("longPressMs", 500)))
        self.combo_ms_var.set(int(cfg.get("comboWindowMs", 100)))
        exp = cfg.get("expression", {})
        self.exp_cc_var.set(int(exp.get("cc", 30)))
        self.exp_invert_var.set(bool(exp.get("invert", False)))
        self.exp_db_var.set(int(exp.get("deadband", 2)))
        for idx, b in enumerate(cfg.get("buttons", [])):
            if idx >= 10:
                break
            short, long_ed = self.button_editors[idx]
            short.set(b.get("short"))
            long_ed.set(b.get("long"))
        for slot, combo in enumerate(cfg.get("combos", [])):
            if slot >= 4:
                break
            enabled_var, a_var, b_var, action = self.combo_editors[slot]
            if not combo:
                enabled_var.set(False)
                continue
            enabled_var.set(True)
            buttons = combo.get("buttons", [0, 1])
            a_var.set(int(buttons[0]))
            b_var.set(int(buttons[1]))
            action.set(combo.get("action"))

    def _require_pedal(self):
        if self.pedal is None:
            messagebox.showwarning(
                "NanoStep Companion", "Connect to the pedal first."
            )
            return False
        return True

    def read_config(self):
        if not self._require_pedal():
            return
        self.log("Reading config from the pedal ...")

        def work():
            try:
                cfg = self.pedal.get_config()
                self.msg_queue.put(("config", cfg))
                self.msg_queue.put(("done", "Config read from the pedal."))
            except Exception as exc:
                self.msg_queue.put(("error", f"Read failed: {exc}"))

        self._run_in_thread(work)

    def write_config(self):
        if not self._require_pedal():
            return
        cfg = self.get_config()
        self.log("Writing config to the pedal ...")

        def work():
            try:
                if self.pedal.send_config(cfg):
                    self.msg_queue.put(("done", "Config written and saved to EEPROM."))
                else:
                    self.msg_queue.put(("error", "Pedal did not confirm the save."))
            except Exception as exc:
                self.msg_queue.put(("error", f"Write failed: {exc}"))

        self._run_in_thread(work)

    def factory_defaults(self):
        if not self._require_pedal():
            return
        if not messagebox.askyesno(
            "NanoStep Companion",
            "Restore factory defaults on the pedal? This overwrites the current config.",
        ):
            return
        self.log("Restoring factory defaults ...")

        def work():
            try:
                if self.pedal.defaults():
                    cfg = self.pedal.get_config()
                    self.msg_queue.put(("config", cfg))
                    self.msg_queue.put(("done", "Factory defaults restored and saved."))
                else:
                    self.msg_queue.put(("error", "Pedal did not confirm the save."))
            except Exception as exc:
                self.msg_queue.put(("error", f"Restore failed: {exc}"))

        self._run_in_thread(work)

    # -- file load/save ---------------------------------------------------

    def load_file(self):
        path = filedialog.askopenfilename(
            title="Load config JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path) as f:
                cfg = json.load(f)
            self.set_config(cfg)
            self.log(f"Loaded config from {path}.")
        except Exception as exc:
            self.log(f"ERROR: could not load {path}: {exc}")
            messagebox.showerror("NanoStep Companion", f"Could not load file:\n{exc}")

    def save_file(self):
        path = filedialog.asksaveasfilename(
            title="Save config JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump(self.get_config(), f, indent=2)
                f.write("\n")
            self.log(f"Saved config to {path}.")
        except Exception as exc:
            self.log(f"ERROR: could not save {path}: {exc}")
            messagebox.showerror("NanoStep Companion", f"Could not save file:\n{exc}")


def main():
    root = tk.Tk()
    CompanionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
