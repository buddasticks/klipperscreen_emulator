# KlipperScreen Panel Emulator

This harness loads **real KlipperScreen panel modules** from a local KlipperScreen checkout and runs them in a desktop GTK window with fake printer/Moonraker state.

## Important Windows note

KlipperScreen panels use **GTK 3 + PyGObject (`gi`)**. On Windows, the practical supported route is **MSYS2** using **MSYS2's Python**, not the normal `python.org` install from PowerShell. The PyGObject docs list MSYS2 as the Windows install path, and MSYS2 provides current `python-gobject` and `gtk3` packages.

## Windows setup (recommended)

1. Install MSYS2.
2. Open the **UCRT64** shell.
3. Update packages:

```bash
pacman -Suy
```

4. Install dependencies:

```bash
pacman -S mingw-w64-ucrt-x86_64-python \
          mingw-w64-ucrt-x86_64-python-gobject \
          mingw-w64-ucrt-x86_64-gtk3 \
          mingw-w64-ucrt-x86_64-python-cairo \
          mingw-w64-ucrt-x86_64-python-jinja
```

5. Run the emulator **inside that UCRT64 shell**:

```bash
cd /c/Users/<you>/Desktop/ks_panel_emulator
python klipperscreen_panel_emulator.py --repo /c/Users/<you>/path/to/KlipperScreen --panel main_menu
```

## Linux setup

On Debian/Ubuntu-style systems, install GTK 3 bindings and Jinja first:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo python3-jinja2
```

Then run:

```bash
python3 klipperscreen_panel_emulator.py --repo ~/KlipperScreen --panel main_menu
```

## Example

```bash
python klipperscreen_panel_emulator.py --repo /c/Users/<you>/src/KlipperScreen --panel main_menu
python klipperscreen_panel_emulator.py --repo /c/Users/<you>/src/KlipperScreen --panel extrude --vertical
python klipperscreen_panel_emulator.py --repo /c/Users/<you>/src/KlipperScreen --panel menu --state ./example_state.json
```

## What it emulates

- fake `screen`
- fake `printer`
- fake Klippy/Moonraker websocket actions
- menu panel navigation
- temp devices and targets
- popup/confirmation logging
- panel action log in the terminal

## Limits

Some panels may still need extra fake fields or stub methods, depending on how much of KlipperScreen internals they touch.
