<div align="center">

# LeGo Decky Toolbox

**The Legion Go's hardware controls, together in the Steam Quick Access menu.**

Power and automatic TDP, fan curve, stick and power lights, charge limit,
button remapping, swapped menu buttons and per-controller gyro for emulators.

**[User manual (PDF)](docs/Legion-Go-Toolbox-Manual.pdf)** · [Features](#features) · [Requirements](#requirements) · [Installation](#installation) · [Using the tabs](#using-the-tabs) · [Troubleshooting](#troubleshooting) · [How it works](#how-it-works) · [Credits](#credits)

</div>

---

## Features

One Decky plugin, six tabs (switch with **LB / RB**). Nothing is changed on
your device until you switch a feature on, and every feature that your system
cannot do says so, with the reason, instead of pretending.

| Tab | What you can do |
|---|---|
| **Home** | See every module at a glance, limit charging to 80 %, reset |
| **Power** | Pick a power mode or set the TDP in watts, per game if you like. **Auto TDP** finds the lowest power that still holds a frame rate you choose |
| **Fan** | Draw a ten-point fan curve, presets, full speed, live temperature, per game and on battery vs charger |
| **Lights** | Stick lights: effect, colour, brightness, speed. Power-button light on/off, and off while sleeping |
| **Controls** | Swap View/Menu with the Legion buttons, remap Y1 Y2 Y3 M2 M3, switch the touchpad off |
| **Gyro** | Gyro in ordinary Steam games (handheld), and each detached controller as its own motion device for Dolphin, Switch emulators and others (DSU / CemuHook) |

Saved settings are applied when SteamOS starts, after sleep, and when a
controller reconnects, also while the menu is closed.

## Requirements

| | |
|---|---|
| Device | Lenovo **Legion Go** (83E1). Built and tested for this model |
| System | SteamOS with [Decky Loader](https://decky.xyz) |

### What needs what

| Feature | Works when |
|---|---|
| Gyro, stick lights, remapping, touchpad | The controllers are connected |
| Power light | Always on a Legion Go (three ways to reach it are tried) |
| Charge limit | SteamOS exposes the battery's *Long Life* mode (current versions do) |
| TDP and power modes | SteamOS has the Lenovo power-limit driver (current versions do) |
| Auto TDP | The above, in Gaming Mode (the frame rate comes from gamescope) |
| Swapped menu buttons, gyro in Steam games | InputPlumber is running (it is on SteamOS) |
| **Fan curve** | **The `acpi_call` kernel module is installed. SteamOS does not include it** |

**About the fan curve.** The Legion Go only accepts a fan table through a
Lenovo firmware call, and Linux can only make that call with the `acpi_call`
module. Installing a kernel module on SteamOS means changing the read-only
system and repeating that after every system update, so this plugin
deliberately does not do it for you. If the module is present (for example
installed with Legion Center's *Install Fan Support*, or on Bazzite), the
curve editor appears by itself. Without it the fan follows the firmware's own
curve, which is safe.

## Installation

1. Install [Decky Loader](https://decky.xyz).
2. Uninstall other plugins that control the same things (SimpleDeckyTDP,
   Legion Center, HueSync, DeckyPlumber): two plugins steering the same
   hardware will fight.
3. Decky → settings → **General → Developer mode** on.
4. Download `legion-go-toolbox.zip` from this repository's
   [Releases](../../releases) page and copy it to the Legion Go.
5. **Developer → Install plugin from ZIP file** → choose the zip.
6. Open the Quick Access menu → Decky → **Legion Go Toolbox** (the plugin's
   name inside Decky).

## Using the tabs

### Power

- **Manage power** hands TDP control to the plugin. Turn off Steam's own
  *TDP limit* in the Performance menu, otherwise both keep overwriting each
  other.
- **Power mode**: *Custom* gives you a watt slider; the other entries are the
  firmware's own modes (Quiet, Balanced, Performance).
- **Auto TDP for a frame rate**: choose a target (for example 60 fps). The
  plugin measures the game's real frame rate and
  - adds power immediately when the frame rate drops below the target,
  - tries one watt less whenever the target has been held for a few seconds,
  - remembers settings that turned out too low, so it settles instead of
    bouncing.

  *Maximum TDP* and *Minimum TDP* are the limits it stays within. It works
  best with a frame limit (in the game or Steam) equal to the target. In
  menus and loading screens it simply keeps the last setting.
- **Separate settings per game** stores a profile for the running game.
- **CPU boost** off runs cooler for a small performance cost.

### Smooth frame rate (per game)

For console-like smoothness, frames must arrive at even intervals, not just
average the right number. While a game runs, choose a cap in **Smooth frame
rate**. The plugin then:

- adds MangoHud's limiter with `fps_limit_method=early` to the game's launch
  options (the Linux counterpart of RTSS's async / front-edge limiter; games
  without MangoHud's Vulkan layer fall back to DXVK's limiter). The settings
  go at the very start, so wrappers you use (lsfg-vk's `~/lsfg`,
  `gamemoderun`, ...) keep working; your own launch options are kept, and
  switching off removes exactly what was added.
- switches the screen to a refresh rate the cap divides evenly while the game
  runs (60 fps: 60 Hz, 72 fps: 144 Hz), with gamescope's own limiter left
  off, and hands the refresh rate back when the game closes.
- makes Auto TDP aim at that cap and judge the slowest frames, not only the
  average, so it never cuts power into stutter.

Caps: 30, 40, 45, 50, 60, 72, 90, 100, 120 and 144 fps (the same list as
Auto TDP). The ones marked with a screen rate - 30 and 60 at 60 Hz, 72 and
144 at 144 Hz on the Legion Go - are perfectly even; the others do not divide
the screen's refresh rate, so some frames stay on screen longer. Restart the game after changing it. For the best
result turn off Steam's Framerate limit and the game's own limiter and
V-Sync for that game. With **lsfg-vk frame generation** nothing extra is
needed: **Frame generation** (below the cap) is on *Auto* and reads the
game's multiplier from lsfg-vk's own settings. The cap stays on the game's
own frames, and the screen rate and Auto TDP follow the generated rate
(60 × 2 = 120). Smooth mode refuses to add a second limiter when a game
already has one.

Other launch-option tools: settings from HelixSR, Decky-Framegen and similar
plugins are kept. Decky-Framegen and Steam ROM Manager *replace* a game's
whole launch options when they apply; the Power tab then says the cap is
missing and offers to add it again. For emulators added with Steam ROM
Manager prefer the emulator's own frame limiter: MangoHud's limiter cannot
reach Flatpak apps, and the DXVK fallback only works for DirectX games. Shader-compilation and loading stutter come from the
game and cannot be removed this way.

### Fan

Needs `acpi_call` (see above). The firmware keeps control of the fan and of
overheating protection; the plugin only changes the table it follows.

- The curve always rises with temperature and never goes below Lenovo's own
  minimum for the Legion Go (44 % at 10 °C rising to 100 % at 90 °C, the same
  limit Handheld Daemon enforces). *Silent* is exactly that minimum.
- The firmware throws away *full speed* and the custom curve whenever the
  power mode changes - whether Steam, another tool or this plugin changes it.
  The plugin reads both back every 5 seconds (and one second after each of
  its own power changes) and puts them back. The Fan tab shows how often it
  had to.
- The firmware uses a custom table only in the *Custom* power mode.
- **Separate settings per game** and **Separate settings on charger** give a
  game, the charger, or a game on the charger its own fan setting. The plugin
  uses the most specific one that exists (this game on the charger → this
  game → all games on the charger → all games) and switches by itself when a
  game starts or closes and when you plug in or unplug. The controls always
  edit the case you are in right now; *Saved fan settings* lists them all.

### Lights

Stick lights are stored in the controllers. *Off while sleeping* switches the
power light off when the device suspends and back on when it wakes.

### Controls

- **Swap menu buttons** with two layouts:

  | Layout | Press | Gets |
  |---|---|---|
  | **Steam ↔ Menu, QAM ↔ View** (default) | Menu / View | Steam / Quick Access |
  | | Legion L / Legion R | Menu / View |
  | Steam ↔ View, QAM ↔ Menu | View / Menu | Steam / Quick Access |
  | | Legion L / Legion R | View / Menu |

  Done with an InputPlumber profile on top of the active one, and restored
  when you switch it off.
- **Remap back buttons** uses Lenovo's own remapping, stored in the
  controllers. Steam still sees the back buttons as extra buttons too, so
  leave them unassigned in Steam Input for games where you use this.

### Gyro

**In Steam games.** Steam only offers gyro for controllers that have one,
and InputPlumber on its own presents the Legion Go as an Xbox controller.
This plugin presents it as a **Steam Deck controller** by default (also
selectable: DualSense, DualSense Edge, or back to Xbox), so Steam shows its
normal gyro options for every game (Steam button → Controller settings →
Gyro).

Choose a type for **all games**, and optionally a different one for the
game that is running: it is remembered, switched to when that game starts
and back when it closes. *Games with their own type* lists them; select one
to remove it.

**Button symbols**: most games show Xbox symbols whatever type is picked,
because Steam Input hands them an Xbox-style controller. Games with their own
PlayStation support may show PlayStation symbols with a DualSense (most offer
a button-prompt setting); Steam's own menus always match the type. The Steam
Deck type keeps A/B/X/Y lettering.

This uses the motion sensor inside the tablet,
so it works with the controllers attached; it cannot use a detached
controller's own sensor. Switching the type reconnects the controller once,
so do it before starting a game. Controller layouts are stored per
controller type, so a game may start with that type's default layout.

**In emulators.** Add a DSU / CemuHook motion server in your emulator: `127.0.0.1`, port
`26760`. Slot 0 = whole handheld, slot 1 = left controller, slot 2 = right
controller.

- **Dolphin**: *Controllers → Alternate Input Sources → DSU Client*, then in
  the Wii Remote's *Motion Input* tab choose `DSUClient/2/…` and press
  *Default*.
- **Ryujinx**: *Input → Motion → Use CemuHook compatible motion*, slot 1 and
  *Right JoyCon Slot* 2.
- **Eden / Citron / yuzu forks**: *Controls → Advanced → Motion/Touch →
  Configure*, add the server, then map *Motion 1* / *Motion 2* by shaking a
  controller.

Press **Calibrate** once and leave the controllers alone for a few seconds.

## With frame generation and upscalers

- **HelixSR** (upscaling only): use Smooth mode and Auto TDP as usual; both
  keep HelixSR's launch settings. Auto TDP settles at fewer watts.
- **lsfg-vk 2.0** (frame generation): Smooth mode caps the game's own frames
  and lsfg-vk multiplies them (tested on a Legion Go: a 30 cap with 2× shows
  60).
  1. In decky-lsfg-vk turn it on for the game with the multiplier you want
     (for example 2×) and leave its **Base FPS cap off** (the Power tab
     warns when it is on: two limiters).
  2. Power tab → Smooth frame rate: choose the game's cap, for example 60.
     **Frame generation** below it stays on *Auto* and shows what it read,
     for example *Auto · lsfg-vk 2× · 60 → 120 fps*. A multiplier changed in
     decky-lsfg-vk is followed within seconds, even mid-game.
  3. Steam's Framerate limit off. The plugin sets the screen rate for the
     final rate and Auto TDP aims at it (120), not at the cap.
  4. Prefer a fixed value? Pick Off or 2×-4× instead of Auto; the Power tab
     says when it differs from lsfg-vk's setting.
  5. Even on the Legion Go's 144 Hz screen: 72 × 2 = 144 and 48 × 3 = 144.
     60 × 2 = 120 and 45 × 2 = 90 run at 144 Hz there, marked *uneven*; even on a
     120 Hz monitor (for example when streaming).
- **Decky-Framegen** (OptiScaler frame generation inside the game): its
  generated frames pass the same limiter, so a Smooth cap would cap the
  final rate. Not verified on a device yet; the safe setup is Smooth mode
  off, the base rate capped with the game's or OptiScaler's own limit, and
  Auto TDP with the **final** rate as target. If a game with a Smooth cap
  shows far more frames than the cap without Frame generation set, the
  plugin detects it and aims Auto TDP at the target instead.

## Troubleshooting

- **A feature says "not available"** – the text under it gives the reason.
- **TDP jumps back** – Steam's own TDP limit is still on, or another TDP
  plugin is installed.
- **Auto TDP says "waiting for the game to draw frames"** – no game is in
  focus, or the game is paused. Otherwise the line shows why no frame rate
  is measured. While streaming (Steam Remote Play, Punktfunk) gamescope does
  not report frame times by default; the plugin switches its frame
  reporting (`mangoapp_use_output_timing`) while it measures and restores it
  afterwards. Steam's performance overlay is not affected.
- **Streaming shows a different frame rate than the device** – the stream
  runs at the client's refresh rate and repeats frames when the game is
  slower. The game's real frame rate is what the Power tab shows.
- **Auto TDP stays at the maximum** – the target frame rate is not reachable
  within your maximum TDP; raise the maximum or lower the target.
- **Stick lights or remapping report "controllers not found"** – wake the
  controllers by pressing a button.
- **Menu buttons swap back** – InputPlumber restarted; the plugin re-applies
  the swap within a few seconds.
- Logs: `~/homebrew/logs/Legion Go Toolbox/`.

## Scope and limits

- Used on a Legion Go (83E1), and verified with simulated hardware (144
  automated tests). Every module reads the device state back after a change
  and reports it when a change did not take.
- Legion Go 2 and Legion Go S are recognised for the parts that are known to
  be identical (power limits, charge limit, power light); the rest stays off.
- Gyro in Steam games comes from the tablet's sensor through SteamOS's own
  input layer; per-controller gyro is for emulators only.

## How it works

```
main.py                     Decky entry point
py_modules/lgo_gyro/        gyro: controller HID reader + DSU server
py_modules/lgo_toolbox/
  hub.py                    applies saved settings, re-applies after sleep
  power.py                  firmware power limits, Auto TDP
  fps_probe.py              game frame rate from gamescope
  fan.py  acpi.py           fan table through Lenovo's firmware call
  powerled.py               power-button light (EC)
  battery.py                charge limit
  controller.py             stick lights, remapping, touchpad
  plumber.py                swapped menu buttons (InputPlumber)
src/                        the tabs (React)
tests/                      backend tests with simulated hardware
```

The backend is plain Python (standard library only) and runs as root, as
Decky plugins with hardware access do.

## Development

```bash
pnpm install
python3 -m unittest discover -s tests     # backend tests
pnpm run build                            # UI -> dist/
bash scripts/package.sh                   # -> release/legion-go-toolbox.zip
```

The PDF manual and README live in `docs/`. To rebuild them after editing
`docs/src/manual.html` or this README (needs Node with `marked` and
Playwright):

```bash
cd docs/src
node readme.cjs ../../README.md readme.html print.css
node render.cjs && mv *.pdf ..
```

## Credits

This plugin is its own code, but it stands on what these projects worked out
about the hardware:

- [Handheld Daemon](https://github.com/hhd-dev/hhd) and
  [hwinfo](https://github.com/hhd-dev/hwinfo) – controller protocol, Lenovo
  firmware methods
- [Legion Center](https://github.com/InnoVision-Games/legion-center) /
  LegionGoRemapper – remapping, fan table, charge limit
- [HueSync](https://github.com/honjow/HueSync) – power light locations
- [SimpleDeckyTDP](https://github.com/aarron-lee/SimpleDeckyTDP) – Lenovo
  power-limit interface
- [DeckyPlumber](https://github.com/aarron-lee/DeckyPlumber) and
  [InputPlumber](https://github.com/ShadowBlip/InputPlumber) – menu-button
  swap
- [Panel de Control](https://github.com/Hooandee/panel-de-control) – the idea
  of reading frame times from gamescope's control interface
- [decky-lsfg-vk](https://github.com/xXJSONDeruloXx/decky-lsfg-vk) – tabs in
  the Quick Access menu
- [Legion Go 2 Companion](https://github.com/Rayekkk/LegionGo2Companion) –
  the module-overview layout

MIT licensed.
