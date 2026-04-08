#!/usr/bin/env python3
"""
KlipperScreen panel emulator for desktop testing.

This harness loads real panel modules from a local KlipperScreen checkout,
creates a fake Screen/Printer/Moonraker environment, and renders the panel
inside a normal GTK window so you can iterate on panel code without needing
an attached touchscreen.

Usage examples:
  python klipperscreen_panel_emulator.py --repo ~/KlipperScreen --panel main_menu
  python klipperscreen_panel_emulator.py --repo ~/KlipperScreen --panel extrude --vertical
  python klipperscreen_panel_emulator.py --repo ~/KlipperScreen --panel menu --state ./state.json
"""

from __future__ import annotations

import argparse
import builtins
import configparser
import importlib
import json
import logging
import os
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any


def _print_windows_gtk_help_and_exit(exc: Exception) -> None:
    msg = "\n".join([
        f"Missing PyGObject / GTK bindings: {exc}",
        "",
        "This emulator loads real KlipperScreen GTK 3 panels, so it needs gi + GTK 3.",
        "On Windows, the supported/easiest route is MSYS2 with its own Python, not the",
        "standard python.org install you launched from PowerShell.",
        "",
        "Recommended Windows setup:",
        "  1) Install MSYS2 from https://www.msys2.org/",
        "  2) Open the UCRT64 shell",
        "  3) Update packages:",
        "       pacman -Suy",
        "  4) Install Python + GTK3 + PyGObject + extras:",
        "       pacman -S mingw-w64-ucrt-x86_64-python",
        "                 mingw-w64-ucrt-x86_64-python-gobject",
        "                 mingw-w64-ucrt-x86_64-gtk3",
        "                 mingw-w64-ucrt-x86_64-python-cairo",
        "                 mingw-w64-ucrt-x86_64-python-jinja",
        "  5) In that same UCRT64 shell, cd to this folder and run:",
        "       python klipperscreen_panel_emulator.py --repo /c/path/to/KlipperScreen --panel main_menu",
        "",
        "Notes:",
        "  - Do NOT use the Windows Store/python.org Python for this script.",
        "  - If your KlipperScreen checkout is on C:\\Users\\..., MSYS2 sees that as /c/Users/...",
        "",
        "Alternative: run this under Linux/WSL where python3-gi + GTK 3 are native.",
    ])
    print(msg, file=sys.stderr)
    raise SystemExit(1)


try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
except ModuleNotFoundError as exc:
    _print_windows_gtk_help_and_exit(exc)

from jinja2 import Environment


# KlipperScreen expects gettext helpers to exist globally.
builtins._ = getattr(builtins, "_", lambda s: s)
builtins.ngettext = getattr(
    builtins,
    "ngettext",
    lambda singular, plural, count: singular if count == 1 else plural,
)


DEFAULT_STATE: dict[str, Any] = {
    "config": {
        "extruder": {
            "max_temp": "300",
            "min_extrude_temp": "170",
            "control": "pid",
        },
        "heater_bed": {
            "max_temp": "130",
            "control": "pid",
        },
        "fan": {
            "max_power": "1.0",
            "off_below": "0.05",
        },
        "gcode_macro TEST_PANEL": {
            "gcode": "RESPOND MSG='Hello from emulator'",
        },
        "output_pin caselight": {
            "value": "0",
        },
        "temperature_sensor chamber": {},
        "temperature_fan electronics": {
            "max_temp": "70",
        },
        "axiscope": {},
        "toolchanger": {},
        "tool T0": {
            "gcode_x_offset": "0.0",
            "gcode_y_offset": "0.0",
            "gcode_z_offset": "0.0",
        },
        "tool T1": {
            "gcode_x_offset": "24.5",
            "gcode_y_offset": "-0.35",
            "gcode_z_offset": "0.18",
        },
        "tool T2": {
            "gcode_x_offset": "49.1",
            "gcode_y_offset": "0.22",
            "gcode_z_offset": "-0.05",
        },
    },
    "data": {
        "configfile": {"warnings": [], "config": {}},
        "webhooks": {"state": "ready"},
        "print_stats": {
            "state": "standby",
            "filename": "Benchy.gcode",
            "print_duration": 1834,
            "total_duration": 2050,
            "filament_used": 4721.5,
            "info": {"total_layer": 212, "current_layer": 87},
        },
        "idle_timeout": {"state": "Ready"},
        "extruder": {
            "temperature": 212.4,
            "target": 215.0,
            "power": 0.43,
        },
        "heater_bed": {
            "temperature": 60.2,
            "target": 60.0,
            "power": 0.15,
        },
        "temperature_sensor chamber": {
            "temperature": 35.7,
        },
        "temperature_fan electronics": {
            "temperature": 41.1,
            "target": 45.0,
            "power": 0.12,
        },
        "fan": {"speed": 0.74},
        "virtual_sdcard": {
            "progress": 0.41,
            "file_position": 184320,
            "is_active": True,
        },
        "toolhead": {
            "homed_axes": "xyz",
            "position": [125.0, 125.0, 12.4, 0.0],
            "max_velocity": 300,
            "max_accel": 4000,
        },
        "gcode_move": {
            "speed_factor": 1.0,
            "extrude_factor": 1.0,
            "gcode_position": [125.0, 125.0, 12.4, 0.0],
        },
        "motion_report": {
            "live_position": [125.0, 125.0, 12.4, 0.0],
            "live_velocity": 122.3,
        },
        "display_status": {
            "message": "Testing panel in emulator",
            "progress": 0.41,
        },
        "pause_resume": {"is_paused": False},
        "system_stats": {
            "cpu_usage": 18.0,
            "sysload": 0.32,
            "memavail": 1412505600,
        },
        "bed_mesh": {
            "profile_name": "default",
            "mesh_min": [20.0, 20.0],
            "mesh_max": [230.0, 230.0],
            "probed_matrix": [
                [0.08, 0.04, 0.02, 0.00, -0.03],
                [0.06, 0.03, 0.01, -0.01, -0.04],
                [0.05, 0.02, 0.00, -0.02, -0.05],
                [0.04, 0.01, -0.01, -0.03, -0.06],
                [0.03, 0.00, -0.02, -0.04, -0.07],
            ],
        },
        "firmware_retraction": {
            "retract_length": 0.8,
            "retract_speed": 35.0,
            "unretract_extra_length": 0.0,
            "unretract_speed": 35.0,
        },
        "manual_probe": {
            "is_active": False,
            "z_position": 0.0,
        },
        "toolchanger": {
            "tool_number": 0,
            "tool_numbers": [0, 1, 2],
        },
        "tool T0": {
            "gcode_x_offset": 0.0,
            "gcode_y_offset": 0.0,
            "gcode_z_offset": 0.0,
        },
        "tool T1": {
            "gcode_x_offset": 24.5,
            "gcode_y_offset": -0.35,
            "gcode_z_offset": 0.18,
        },
        "tool T2": {
            "gcode_x_offset": 49.1,
            "gcode_y_offset": 0.22,
            "gcode_z_offset": -0.05,
        },
        "axiscope": {
            "probe_results": {
                "1": {
                    "suggested_gcode_z_offset": 0.16,
                    "source": "emulator",
                },
                "2": {
                    "suggested_gcode_z_offset": -0.04,
                    "source": "emulator",
                },
            },
        },
    },
    "power_devices": [
        {"device": "printer", "status": "on"},
        {"device": "lights", "status": "off"},
    ],
    "cameras": [
        {
            "name": "Nozzle Cam",
            "enabled": True,
            "stream_url": "http://127.0.0.1:8080/stream",
        }
    ],
    "server_info": {
        "warnings": [],
        "failed_components": [],
        "missing_klippy_requirements": [],
    },
    "menu_items": [
        {
            "temperature": {
                "name": "Temperature",
                "icon": "heat-up",
                "style": "color1",
                "panel": "temperature",
                "method": False,
                "params": False,
                "confirm": None,
                "enable": "{{ True }}",
            }
        },
        {
            "extrude": {
                "name": "Extrude",
                "icon": "extrude",
                "style": "color2",
                "panel": "extrude",
                "method": False,
                "params": False,
                "confirm": None,
                "enable": "{{ True }}",
            }
        },
        {
            "move": {
                "name": "Move",
                "icon": "move",
                "style": "color3",
                "panel": "move",
                "method": False,
                "params": False,
                "confirm": None,
                "enable": "{{ True }}",
            }
        },
        {
            "console": {
                "name": "Console",
                "icon": "console",
                "style": "color4",
                "panel": "console",
                "method": False,
                "params": False,
                "confirm": None,
                "enable": "{{ True }}",
            }
        },
        {
            "bed_mesh": {
                "name": "Bed Mesh",
                "icon": "bed-level",
                "style": "color1",
                "panel": "bed_mesh",
                "method": False,
                "params": False,
                "confirm": None,
                "enable": "{{ True }}",
            }
        },
        {
            "macros": {
                "name": "Macros",
                "icon": "custom-script",
                "style": "color2",
                "panel": "gcode_macros",
                "method": False,
                "params": False,
                "confirm": None,
                "enable": "{{ True }}",
            }
        },
    ],
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ActionLog:
    def __init__(self, view: Gtk.TextView):
        self.view = view
        self.buffer = view.get_buffer()

    def add(self, message: str) -> None:
        end_iter = self.buffer.get_end_iter()
        self.buffer.insert(end_iter, message.rstrip() + "\n")
        adj = self.view.get_parent().get_vadjustment()  # ScrolledWindow
        GLib.idle_add(adj.set_value, adj.get_upper())
        logging.info(message)


class NullTimeoutObject:
    def reset_timeout(self, *args: Any, **kwargs: Any) -> None:
        return None

    def close(self, *args: Any, **kwargs: Any) -> None:
        return None

    def lock(self, *args: Any, **kwargs: Any) -> None:
        return None


class FakeFiles:
    def has_thumbnail(self, filename: str) -> bool:
        return False

    def get_thumbnail_location(self, filename: str, small: bool = False) -> None:
        return None


class FakeApiClient:
    def __init__(self) -> None:
        self.endpoint = "http://127.0.0.1:7125"
        self.api_key = ""

    def get_thumbnail_stream(self, resource: str) -> bool:
        return False


class FakeMainConfig:
    def __init__(self, section: configparser.SectionProxy):
        self.section = section

    def get(self, option: str, fallback: Any = None) -> Any:
        return self.section.get(option, fallback=fallback)

    def getboolean(self, option: str, fallback: bool = False) -> bool:
        return self.section.getboolean(option, fallback=fallback)

    def getint(self, option: str, fallback: int = 0) -> int:
        return self.section.getint(option, fallback=fallback)


class FakeConfig:
    def __init__(self) -> None:
        self.cfg = configparser.ConfigParser()
        self.cfg["main"] = {
            "font_size": "medium",
            "show_heater_power": "True",
            "keyboard_navigation": "False",
            "show_scroll_steppers": "False",
            "24htime": "True",
            "only_heaters": "False",
            "confirm_estop": "False",
        }

    def get_config(self) -> configparser.ConfigParser:
        return self.cfg

    def get_main_config(self) -> FakeMainConfig:
        return FakeMainConfig(self.cfg["main"])

    def set(self, section: str, option: str, value: str) -> None:
        if section not in self.cfg:
            self.cfg.add_section(section)
        self.cfg.set(section, option, value)

    def save_user_config_options(self) -> None:
        return None


class FakeKlippyActions:
    def __init__(self, action_log: ActionLog, printer: Any) -> None:
        self._log = action_log
        self._printer = printer

    def emergency_stop(self) -> None:
        self._log.add("[KLIPPY] emergency_stop()")
        self._printer.state = "shutdown"

    def set_tool_temp(self, tool_number: int, temp: int) -> None:
        tool_name = self._printer.get_tools()[tool_number]
        self._printer.set_stat(tool_name, {"target": temp})
        self._log.add(f"[KLIPPY] set_tool_temp(tool={tool_number}, temp={temp})")

    def set_bed_temp(self, temp: int) -> None:
        self._printer.set_stat("heater_bed", {"target": temp})
        self._log.add(f"[KLIPPY] set_bed_temp(temp={temp})")

    def set_heater_temp(self, heater_name: str, temp: int) -> None:
        self._printer.set_stat(f"heater_generic {heater_name}", {"target": temp})
        self._log.add(f"[KLIPPY] set_heater_temp({heater_name}, {temp})")

    def set_temp_fan_temp(self, fan_name: str, temp: int) -> None:
        self._printer.set_stat(f"temperature_fan {fan_name}", {"target": temp})
        self._log.add(f"[KLIPPY] set_temp_fan_temp({fan_name}, {temp})")

    def object_subscription(self, payload: dict[str, Any]) -> None:
        self._log.add(f"[KLIPPY] object_subscription({json.dumps(payload, default=str)})")

    def __getattr__(self, item: str):
        def _method(*args: Any, **kwargs: Any) -> None:
            arg_bits = []
            if args:
                arg_bits.append(", ".join(repr(a) for a in args))
            if kwargs:
                arg_bits.append(", ".join(f"{k}={v!r}" for k, v in kwargs.items()))
            pretty = ", ".join(arg_bits)
            self._log.add(f"[KLIPPY] {item}({pretty})")
        return _method


class FakeWebsocket:
    def __init__(self, action_log: ActionLog, printer: Any) -> None:
        self.connected = True
        self.klippy = FakeKlippyActions(action_log, printer)
        self._log = action_log

    def send_method(self, method: str, params: dict[str, Any] | None = None, callback: Any = None) -> None:
        params = params or {}
        self._log.add(f"[WS] {method}({json.dumps(params, default=str)})")
        if callback is None:
            return
        if method == "server.gcode_store":
            callback({"result": {"gcode_store": []}}, method, params)
            return
        if method == "machine.device_power.devices":
            callback({"result": {"devices": []}}, method, params)
            return
        callback({}, method, params)


class SimpleBasePanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.titlebar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.titlebar.get_style_context().add_class("titlebar")
        self._title = Gtk.Label(xalign=0)
        self._title.set_markup("<b>KlipperScreen Emulator</b>")
        self._status = Gtk.Label(xalign=1)
        self._status.set_text("")
        self._status.set_hexpand(True)
        self.titlebar.pack_start(self._title, True, True, 8)
        self.titlebar.pack_end(self._status, False, False, 8)

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_box.set_hexpand(True)
        self.content_box.set_vexpand(True)

        self.pack_start(self.titlebar, False, False, 0)
        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        self.pack_start(self.content_box, True, True, 0)

    def set_title(self, title: str) -> None:
        safe = GLib.markup_escape_text(title)
        self._title.set_markup(f"<b>{safe}</b>")

    def set_status(self, text: str) -> None:
        self._status.set_text(text)

    def add_content(self, widget: Gtk.Widget) -> None:
        for child in self.content_box.get_children():
            self.content_box.remove(child)
        self.content_box.add(widget)
        self.show_all()

    def remove(self, widget: Gtk.Widget) -> None:
        if widget in self.content_box.get_children():
            self.content_box.remove(widget)

    def set_control_sensitive(self, sensitive: bool, control: str = "back") -> None:
        self.set_status(f"{control}: {'enabled' if sensitive else 'disabled'}")


@dataclass
class Imports:
    Printer: Any
    KlippyGtk: Any


class EmulatorScreen(Gtk.Window):
    def __init__(
        self,
        repo_path: Path,
        panel_name: str,
        state: dict[str, Any],
        width: int,
        height: int,
        vertical_mode: bool,
        theme: str | None,
    ) -> None:
        super().__init__(title="KlipperScreen Panel Emulator")
        self.repo_path = repo_path
        self.panel_name = panel_name
        self.width = width
        self.height = height
        self.vertical_mode = vertical_mode
        self.windowed = True
        self.wayland = False
        self.show_cursor = True
        self.connected_printer = "emulated-printer"
        self.theme = theme or self._guess_theme()
        self.server_info = state.get("server_info", DEFAULT_STATE["server_info"])
        self.dialogs: list[Gtk.Dialog] = []
        self.updating = False
        self.confirm = None
        self.files = FakeFiles()
        self.apiclient = FakeApiClient()
        self._config = FakeConfig()
        self.env = Environment(autoescape=True)
        self.screensaver = NullTimeoutObject()
        self.lock_screen = NullTimeoutObject()
        self.current_panel: Any = None
        self.panels: dict[str, Any] = {}
        self._cur_panels: list[str] = []

        self.set_default_size(width, height)
        self.connect("destroy", Gtk.main_quit)

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add(outer)

        self.sidebar = self._build_sidebar()
        outer.pack_start(self.sidebar, False, False, 0)

        self.base_panel = SimpleBasePanel()
        outer.pack_start(self.base_panel, True, True, 0)

        self._imports = self._load_repo_imports()
        self.printer = self._imports.Printer(lambda *_: None, {
            "disconnected": None,
            "startup": None,
            "ready": None,
            "shutdown": None,
            "error": None,
            "paused": None,
            "printing": None,
        })

        self.log_view = self._find_log_view()
        self.action_log = ActionLog(self.log_view)
        self._ws = FakeWebsocket(self.action_log, self.printer)
        self.gtk = self._imports.KlippyGtk(self)
        self._init_temp_colors()

        self._menu_items = state.get("menu_items", DEFAULT_STATE["menu_items"])
        self.load_state(state)
        self.show_panel(panel_name)
        self.show_all()


    def _init_temp_colors(self) -> None:
        self.gtk.color_list = {
            "extruder": {"colors": ["ff6b6b", "ff8e72", "ffb36b"], "state": 0},
            "bed": {"colors": ["69b7ff", "7cc6ff", "94d4ff"], "state": 0},
            "fan": {"colors": ["7bd389", "95dd9b", "b0e7b0"], "state": 0},
            "sensor": {"colors": ["ffd166", "ffe08a", "ffebb0"], "state": 0},
        }
        if hasattr(self.gtk, "reset_temp_color"):
            self.gtk.reset_temp_color()

    def show_keyboard(self, *args: Any) -> bool:
        self.action_log.add("[EMU] show_keyboard()")
        return False

    def remove_keyboard(self, *args: Any) -> bool:
        self.action_log.add("[EMU] remove_keyboard()")
        return False

    def _guess_theme(self) -> str:
        styles_dir = self.repo_path / "styles"
        if not styles_dir.exists():
            return "z-bolt"
        names = sorted([p.name for p in styles_dir.iterdir() if p.is_dir()])
        if "z-bolt" in names:
            return "z-bolt"
        return names[0] if names else "z-bolt"

    def _prepend_repo_to_syspath(self) -> None:
        repo = str(self.repo_path)
        if repo not in sys.path:
            sys.path.insert(0, repo)

    def _load_repo_imports(self) -> Imports:
        self._prepend_repo_to_syspath()
        printer_mod = importlib.import_module("ks_includes.printer")
        gtk_mod = importlib.import_module("ks_includes.KlippyGtk")
        return Imports(Printer=printer_mod.Printer, KlippyGtk=gtk_mod.KlippyGtk)

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_size_request(300, -1)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Emulator Controls</b>")
        box.pack_start(title, False, False, 0)

        self.panel_entry = Gtk.Entry()
        self.panel_entry.set_placeholder_text("panel module name, e.g. main_menu")
        self.panel_entry.set_text(self.panel_name)
        box.pack_start(self.panel_entry, False, False, 0)

        button_row = Gtk.Box(spacing=6)
        load_btn = Gtk.Button(label="Load Panel")
        load_btn.connect("clicked", self._on_load_panel)
        reload_btn = Gtk.Button(label="Reload")
        reload_btn.connect("clicked", self._on_reload_panel)
        button_row.pack_start(load_btn, True, True, 0)
        button_row.pack_start(reload_btn, True, True, 0)
        box.pack_start(button_row, False, False, 0)

        self.state_combo = Gtk.ComboBoxText()
        for value in ["ready", "printing", "paused", "shutdown", "error"]:
            self.state_combo.append(value, value)
        self.state_combo.set_active_id("ready")
        self.state_combo.connect("changed", self._on_state_changed)
        box.pack_start(Gtk.Label(label="Printer state", xalign=0), False, False, 0)
        box.pack_start(self.state_combo, False, False, 0)

        temp_row = Gtk.Box(spacing=6)
        self.extruder_temp = Gtk.SpinButton.new_with_range(0, 320, 1)
        self.extruder_temp.set_value(212)
        self.bed_temp = Gtk.SpinButton.new_with_range(0, 150, 1)
        self.bed_temp.set_value(60)
        temp_row.pack_start(Gtk.Label(label="E", xalign=0), False, False, 0)
        temp_row.pack_start(self.extruder_temp, True, True, 0)
        temp_row.pack_start(Gtk.Label(label="B", xalign=0), False, False, 0)
        temp_row.pack_start(self.bed_temp, True, True, 0)
        box.pack_start(Gtk.Label(label="Temperatures", xalign=0), False, False, 0)
        box.pack_start(temp_row, False, False, 0)

        update_btn = Gtk.Button(label="Push Status Update")
        update_btn.connect("clicked", self._push_status_update)
        box.pack_start(update_btn, False, False, 0)

        tempstore_btn = Gtk.Button(label="Init Temp Graph Store")
        tempstore_btn.connect("clicked", lambda *_: self.init_tempstore())
        box.pack_start(tempstore_btn, False, False, 0)

        info = Gtk.Label(xalign=0)
        info.set_line_wrap(True)
        info.set_text(
            "Edits to your panel code can be tested by pressing Reload. "
            "For menu/main_menu, the emulator feeds default items unless your state JSON overrides them."
        )
        box.pack_start(info, False, False, 0)

        log_label = Gtk.Label(xalign=0)
        log_label.set_markup("<b>Action log</b>")
        box.pack_start(log_label, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        log_view = Gtk.TextView()
        log_view.set_editable(False)
        log_view.set_cursor_visible(False)
        log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroller.add(log_view)
        box.pack_start(scroller, True, True, 0)
        self._log_scroller = scroller
        return box

    def _find_log_view(self) -> Gtk.TextView:
        return self._find_widget(self.sidebar, Gtk.TextView)

    def _find_widget(self, widget: Gtk.Widget, wanted_type: type[Gtk.Widget]) -> Gtk.Widget:
        if isinstance(widget, wanted_type):
            return widget
        if hasattr(widget, "get_children"):
            for child in widget.get_children():
                found = self._find_widget(child, wanted_type)
                if found is not None:
                    return found
        return None

    def load_state(self, state: dict[str, Any]) -> None:
        config = deep_merge(DEFAULT_STATE["config"], state.get("config", {}))
        data = deep_merge(DEFAULT_STATE["data"], state.get("data", {}))
        data.setdefault("configfile", {})["config"] = config

        printer_info = {"software_version": "KlipperScreen Emulator"}
        self.printer.reinit(printer_info, data)
        self.printer.configure_power_devices({"devices": state.get("power_devices", DEFAULT_STATE["power_devices"])})
        self.printer.configure_cameras(state.get("cameras", DEFAULT_STATE["cameras"]))
        self.server_info = state.get("server_info", DEFAULT_STATE["server_info"])
        self.action_log.add("[EMU] State loaded")

    def init_tempstore(self) -> None:
        tempstore: dict[str, dict[str, list[float]]] = {}
        for device in self.printer.get_temp_devices():
            base_temp = float(self.printer.get_stat(device, "temperature") or 0)
            target = float(self.printer.get_stat(device, "target") or 0)
            power = float(self.printer.get_stat(device, "power") or 0)
            tempstore[device] = {
                "temperatures": [base_temp for _ in range(60)],
            }
            if self.printer.device_has_target(device):
                tempstore[device]["targets"] = [target for _ in range(60)]
            if self.printer.device_has_power(device):
                tempstore[device]["powers"] = [power for _ in range(60)]
        self.printer.init_temp_store(tempstore)
        self.action_log.add("[EMU] Temp store initialized")

    def _state_json_from_widgets(self) -> dict[str, Any]:
        state = {
            "data": {
                "webhooks": {"state": self.state_combo.get_active_id() or "ready"},
                "print_stats": {
                    "state": {
                        "ready": "standby",
                        "printing": "printing",
                        "paused": "paused",
                        "shutdown": "error",
                        "error": "error",
                    }[self.state_combo.get_active_id() or "ready"]
                },
                "extruder": {"temperature": self.extruder_temp.get_value()},
                "heater_bed": {"temperature": self.bed_temp.get_value()},
                "pause_resume": {"is_paused": (self.state_combo.get_active_id() == "paused")},
            }
        }
        return state

    def _apply_widget_state(self) -> None:
        patch = self._state_json_from_widgets()
        self.printer.process_update(patch["data"])
        self.printer.state = self.printer.evaluate_state()

    def _push_status_update(self, *_args: Any) -> None:
        self._apply_widget_state()
        if hasattr(self.current_panel, "process_update"):
            self.current_panel.process_update("notify_status_update", self.printer.data)
            self.action_log.add("[EMU] notify_status_update pushed")

    def _on_state_changed(self, *_args: Any) -> None:
        self._apply_widget_state()
        self.base_panel.set_status(f"state: {self.printer.state}")
        if hasattr(self.current_panel, "process_update"):
            self.current_panel.process_update("notify_status_update", self.printer.data)

    def _on_load_panel(self, *_args: Any) -> None:
        self.show_panel(self.panel_entry.get_text().strip() or self.panel_name)

    def _on_reload_panel(self, *_args: Any) -> None:
        self.show_panel(self.panel_entry.get_text().strip() or self.panel_name, force_reload=True)

    def _module_for_panel(self, panel: str, force_reload: bool = False) -> ModuleType:
        self._prepend_repo_to_syspath()
        module_name = f"panels.{panel}"
        if force_reload and module_name in sys.modules:
            del sys.modules[module_name]
        return importlib.import_module(module_name)

    def _make_panel_kwargs(self, panel: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if panel in {"menu", "main_menu"}:
            kwargs["items"] = self._menu_items
        return kwargs

    def show_panel(
        self,
        panel: str,
        title: str | None = None,
        remove_all: bool = False,
        panel_name: str | None = None,
        force_reload: bool = False,
        **kwargs: Any,
    ) -> None:
        del remove_all, panel_name  # Kept for compatibility with panel calls.
        self.panel_name = panel
        self.panel_entry.set_text(panel)
        self._apply_widget_state()
        merged_kwargs = self._make_panel_kwargs(panel)
        merged_kwargs.update(kwargs)
        title = title or panel.replace("_", " ").title()

        try:
            module = self._module_for_panel(panel, force_reload=force_reload)
            panel_obj = module.Panel(self, title, **merged_kwargs)
            self.current_panel = panel_obj
            self.panels[panel] = panel_obj
            self._cur_panels = [panel]
            self.base_panel.set_title(title)
            self.base_panel.add_content(panel_obj.content)
            self.base_panel.set_status(f"panel: {panel}")
            self.action_log.add(f"[EMU] Loaded panel '{panel}'")
            if hasattr(panel_obj, "activate"):
                panel_obj.activate()
        except Exception:
            trace = traceback.format_exc()
            self.show_error_modal(f"Unable to load panel '{panel}'", trace)

    def _go_to_submenu(self, _widget: Gtk.Widget, key: str) -> None:
        if self.current_panel and hasattr(self.current_panel, "load_menu"):
            self.current_panel.load_menu(None, key, key)
            self.action_log.add(f"[EMU] load_menu('{key}')")

    def confirm_save(self, *_args: Any, **_kwargs: Any) -> None:
        self.action_log.add("[EMU] confirm_save()")

    def _send_action(self, _widget: Gtk.Widget, method: str, params: dict[str, Any] | None = None) -> None:
        params = params or {}
        self.action_log.add(f"[ACTION] {method} params={params}")
        if method == "printer.gcode.script":
            self._emulate_gcode_script(str(params.get("script", "")))

    def _set_position(self, position: list[float]) -> None:
        self.printer.set_stat("gcode_move", {"gcode_position": position[:]})
        self.printer.set_stat("motion_report", {"live_position": position[:]})
        self.printer.set_stat("toolhead", {"position": position[:]})

    def _notify_current_panel(self) -> None:
        if hasattr(self.current_panel, "process_update"):
            self.current_panel.process_update("notify_status_update", self.printer.data)

    def _emulate_gcode_script(self, script: str) -> None:
        lines = [line.strip() for line in script.splitlines() if line.strip()]
        if not lines:
            return
        position = list(self.printer.get_stat("gcode_move", "gcode_position") or [0.0, 0.0, 0.0, 0.0])
        while len(position) < 4:
            position.append(0.0)
        relative = False
        changed_position = False

        for raw in lines:
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            tool_match = re.fullmatch(r"T(\d+)", line, flags=re.IGNORECASE)
            if tool_match:
                self.printer.set_stat("toolchanger", {"tool_number": int(tool_match.group(1))})
                continue
            upper = line.upper()
            if upper == "G91":
                relative = True
                continue
            if upper == "G90":
                relative = False
                continue
            if upper.startswith(("G0", "G1")):
                for axis, index in (("X", 0), ("Y", 1), ("Z", 2), ("E", 3)):
                    match = re.search(rf"{axis}([-+]?\d*\.?\d+)", line, flags=re.IGNORECASE)
                    if not match:
                        continue
                    value = float(match.group(1))
                    position[index] = position[index] + value if relative else value
                    changed_position = True
                continue
            if upper.startswith("AXISCOPE_SET_ENDSTOP_POSITION"):
                x_match = re.search(r"X=([-+]?\d*\.?\d+)", line, flags=re.IGNORECASE)
                y_match = re.search(r"Y=([-+]?\d*\.?\d+)", line, flags=re.IGNORECASE)
                current = dict(self.printer.get_stat("axiscope") or {})
                current["endstop_position"] = {
                    "x": float(x_match.group(1)) if x_match else None,
                    "y": float(y_match.group(1)) if y_match else None,
                }
                self.printer.set_stat("axiscope", current)
                continue
            if upper.startswith("AXISCOPE_SAVE_TOOL_OFFSET"):
                tool_match = re.search(r'TOOL_NAME="([^"]+)"', line)
                offset_match = re.search(r'OFFSETS="\[([^\]]+)\]"', line)
                if tool_match and offset_match:
                    parts = [float(part.strip()) for part in offset_match.group(1).split(",")[:3]]
                    while len(parts) < 3:
                        parts.append(0.0)
                    self.printer.set_stat(tool_match.group(1), {
                        "gcode_x_offset": parts[0],
                        "gcode_y_offset": parts[1],
                        "gcode_z_offset": parts[2],
                    })
                continue

        if changed_position:
            self._set_position(position)
        self._notify_current_panel()

    def _confirm_send_action(
        self,
        _widget: Gtk.Widget,
        message: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.action_log.add(f"[CONFIRM] {message}")
        self._send_action(_widget, method, params)

    def show_popup_message(self, message: str, level: int = 3, from_ws: bool = False) -> None:
        del from_ws
        self.action_log.add(f"[POPUP L{level}] {message}")
        self.base_panel.set_status(message)

    def show_error_modal(self, title: str, detail: str) -> None:
        self.action_log.add(f"[ERROR] {title}\n{detail}")
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        dialog.format_secondary_text(detail[-5000:])
        dialog.connect("response", lambda d, *_: d.destroy())
        dialog.show_all()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Desktop emulator for KlipperScreen panels")
    parser.add_argument("--repo", required=True, help="Path to a local KlipperScreen checkout")
    parser.add_argument("--panel", default="main_menu", help="Panel module name to load")
    parser.add_argument("--state", help="Optional JSON file to override emulator printer state")
    parser.add_argument("--width", type=int, default=1280, help="Window width")
    parser.add_argument("--height", type=int, default=800, help="Window height")
    parser.add_argument("--vertical", action="store_true", help="Use vertical/tall layout")
    parser.add_argument("--theme", help="KlipperScreen theme directory name to use")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def load_state_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    repo_path = Path(os.path.expanduser(args.repo)).resolve()
    if not repo_path.exists():
        print(f"KlipperScreen repo path does not exist: {repo_path}", file=sys.stderr)
        return 2
    if not (repo_path / "panels").exists():
        print(f"Not a KlipperScreen checkout (missing panels/): {repo_path}", file=sys.stderr)
        return 2

    state = load_state_file(args.state)
    win = EmulatorScreen(
        repo_path=repo_path,
        panel_name=args.panel,
        state=state,
        width=args.width,
        height=args.height,
        vertical_mode=args.vertical,
        theme=args.theme,
    )
    win.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
