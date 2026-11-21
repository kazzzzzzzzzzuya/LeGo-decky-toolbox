<div align="center">

# LeGo Decky Toolbox

**The Legion Go's hardware controls, together in the Steam Quick Access menu.**

Power and automatic TDP, fan curve, stick and power lights, charge limit,
button remapping, swapped menu buttons and per-controller gyro for emulators.

**[User manual (PDF)](docs/Legion-Go-Toolbox-Manual.pdf)** · [Features](#features) · [Requirements](#requirements) · [Installation](#installation) · [Using the tabs](#using-the-tabs) · [Troubleshooting](#troubleshooting) · [How it works](#how-it-works) · [Credits](#credits)

</div>

---

## Features

One Decky plugin, three tabs (switch with **LB / RB**), ordered by what you
need most. Nothing is changed on your device until you choose something, and
every feature that your system cannot do says so, with the reason.

| Tab | What it holds |
|---|---|
| **Game** | What is happening now in plain words (frame rate, watts, hours left), a red alert only when something broke, and **one choice per game**: *Longest battery*, *Balanced* or *Smoothest*. Each sets the game's power, frame cap, fan and frame generation together, shows the hours it gives (learned per game) and is remembered |
| **Device** | Set-once settings: stop charging at 80 %, power-off after a long sleep, better speakers (Speaker EQ), buttons, lights, gyro in Steam games, and whether your Steam mods (SLSsteam, CloudRedirect, ASSella / Uran) still work |
| **More** | Every detailed control, nothing removed: power and TDP (Auto TDP), frame rate cap, battery goal, fan curve, gyro for emulators (DSU), Steam mods and backups, backup / updates / about. A change here overrides the game's mode for that game |

Saved settings are applied when SteamOS starts, after sleep, and when a
controller reconnects, also while the menu is closed.

The look is the **Dot theme**: true black, white and grey with one red accent
for what is on or needs a look. Tabs are a row of round outlined icons (the
current one filled white), titles and big readings (battery, watts, frame rate,
sleep drain) are in dot-matrix type, and notes sit in outlined cards. Frame
Suite has the same look.

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
| **Fan curve** | **The `acpi_call` kernel module. SteamOS does not include it; More → Fan curve installs it** |

**About the fan curve.** The Legion Go only accepts a fan table through a
Lenovo firmware call, and Linux can only make that call with the `acpi_call`
module. When it is missing, More → Fan curve shows **Install acpi_call**: the
plugin builds the module on the device (internet, about 4 GB of free space
during the build, several minutes) and loads it. The build happens in a
throw-away overlay, the same technique Legion Center uses, but nothing is
written to SteamOS's system partition: the finished module is kept in the
plugin's data folder and loaded at start. After a SteamOS update that brings
a new kernel that page asks you to build it once more. A module that is
already present (Legion Center's *Install Fan Support*, Bazzite) is used as
it is. Without the module the fan follows the firmware's own curve, which is
safe. The installer's mechanics are tested, but it has not been run on a
Legion Go yet.

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

**Updating:** the Game tab says when a newer release exists: press
**Update to …** at the top and confirm Decky's prompt. **More → Backup,
updates, about** has **Check for updates** and **Install another version**.
Settings stay.

**Coming from 2.x:** the version numbers started again at **1.0.0** with the
simpler three-tab layout. Install 1.0.0 once by hand (the zip from the
release, or *Install another version*, which lists it as older); your
settings stay and later updates are offered as usual.

## Using the tabs

### The Game tab: one choice per game

Start a game, open the plugin, pick how it should run:

| Mode | Frame cap | Power (Auto TDP) | Fan* | Frame generation |
|---|---|---|---|---|
| **Longest battery** | 36 fps | 5–12 W, aims at 36 fps | silent | off |
| **Balanced** | 60 fps | 8–20 W, aims at 60 fps | quiet | off |
| **Smoothest** | none | 10–25 W, aims at 60 fps | cooler | **on**: Frame Suite's Boost (needs Frame Suite) |

\* Only while the custom fan curve is on (More → Fan curve); otherwise the firmware's own curve.

The choice is remembered per game and applied by setting that game's own
power profile, frame cap (in its launch options: restart the game once) and
fan curve; Smoothest asks Frame Suite to turn its Boost on, which starts with
the game's next start. The hours shown per mode are learned while the game
runs in that mode on battery. The frame rate on the Game tab is the one from
just **before you opened the menu** ("Before menu"): the open menu slows the
game down and pauses MAKO's frame generation. Anything changed under **More** overrides the
mode for that game. Without a mode a game runs exactly as before.

### The Device and More tabs

Rows with **›** open a page; **B** (or the top row) goes back. The sections
below describe those pages.

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
    bouncing,
  - remembers the watts each game settled at, separately for battery and
    charger, and starts there next time instead of searching again.

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
  without MangoHud's Vulkan layer fall back to DXVK's limiter). The launch
  options point MangoHud at a small cap file
  (`~/.config/lgo-toolbox/smooth/<appid>.conf`) that the plugin keeps up to
  date, so after the first start cap changes and frame generation apply
  while the game runs. The settings go at the very start, so wrappers you
  use (lsfg-vk's `~/lsfg`, `gamemoderun`, ...) keep working; your own launch
  options are kept, and switching off removes exactly what was added.
- switches the screen to a refresh rate the cap divides evenly while the game
  runs (60 fps: 60 Hz, 72 fps: 144 Hz), with gamescope's own limiter left
  off, and hands the refresh rate back when the game closes.
- makes Auto TDP aim at that cap and judge the slowest frames, not only the
  average, so it never cuts power into stutter. Unevenness the screen causes
  itself (90 fps at 144 Hz) is not counted, and unevenness a few more watts
  do not fix (frame generation, shader stutter) does not push power to the
  maximum.

Caps: 30, 36, 45, 50, 60, 72, 90, 100, 120 and 144 fps (36 instead of
Auto TDP's 40, so 2× frame generation gives 72). The ones marked with a
screen rate - 30 and 60 at 60 Hz, 36, 72 and 144 at 144 Hz on the Legion Go - are perfectly even; the others do not divide
the screen's refresh rate, so some frames stay on screen longer. Restart the game once after first choosing a cap. For the best
result turn off Steam's Framerate limit and the game's own limiter and
V-Sync for that game. With **lsfg-vk frame generation** nothing extra is
needed: **Frame generation** (below the cap) is on *Auto* and reads the
game's multiplier from lsfg-vk's own settings. The cap stays on the game's
own frames, and the screen rate and Auto TDP follow the generated rate
(60 × 2 = 120). Smooth mode refuses to add a second limiter when a game
already has one.

Other launch-option tools: settings from HelixSR, Frame Suite, Decky-Framegen
and similar plugins are kept. Decky-Framegen's own panel and Steam ROM Manager
*replace* a game's whole launch options when they apply (Frame Suite adds its
settings next to the cap instead); More → Frame rate cap then says the cap is
missing and offers to add it again. For emulators added with Steam ROM
Manager prefer the emulator's own frame limiter: MangoHud's limiter cannot
reach Flatpak apps, and the DXVK fallback only works for DirectX games. Shader-compilation and loading stutter come from the
game and cannot be removed this way.

### Battery playtime (per game)

Choose how long the running game should last on battery, for example
**4 h**, or **As long as possible**. Before you choose, the section shows how
long the battery lasts at the current draw and the **longest this game can
reach** from the current charge at your lowest frame rate. That estimate
learns what the game draws at each power limit while you play on battery, so
it gets more exact over time.

With a goal the plugin works out a power budget (energy left ÷ hours to go)
and checks the battery's real draw against it every few seconds:

1. **Power limit first.** Too much drawn: the TDP comes down, a watt or a few
   at a time. Plenty to spare for two minutes: it goes back up.
2. **Then the frame rate, evenly.** When the game can no longer keep its
   Smooth cap on that budget, the cap steps down to the next even one the
   screen divides (60 → 48 → 36 → 30), never below your **Lowest frame
   rate** (30 by default). Your own cap in Smooth mode stays as you set it;
   the lower one is used only while the goal needs it.
3. **Frame generation, with Frame Suite.** If the Frame Suite plugin is
   installed with lsfg-vk set up, the first step down is "half the frames,
   doubled by lsfg-vk" instead (60 → 30 × 2 = 60 on screen), which looks
   the same and costs far less. Frame Suite prepares lsfg-vk for the game
   (off until needed), which lsfg-vk picks up from the game's **next start**;
   from then on the plugin switches it on and off while you play. If even
   that is too much, frame generation's own cost goes too (30 fps without it).
   Switch **Frame generation for battery time** off to keep it out.
4. **Your lowest frame rate wins.** If the goal is out of reach at that frame
   rate, the plugin says so and makes the battery last as long as it can
   without going lower.

The goal counts only while the game runs on battery; on the charger
everything goes back to your own settings and the count waits. After charging
(10 % or more), the count starts again. Setting a goal switches **Manage
power** on, since the goal works through the power limit. Screen brightness
matters a lot: the screen alone draws several watts.

Without a Smooth frame rate for the game only the power limit is used, and the
frame rate falls unevenly instead of stepping to an even cap: set one first.
Not verified on a device yet.

### Fan

Needs `acpi_call` (see above). The firmware keeps control of the fan and of
overheating protection; the plugin only changes the table it follows.

- The curve always rises with temperature and never goes below Lenovo's own
  minimum for the Legion Go (44 % at 10 °C rising to 100 % at 90 °C, the same
  limit Handheld Daemon enforces). *Silent* is exactly that minimum.
- The firmware throws away *full speed* and the custom curve whenever the
  power mode changes - whether Steam, another tool or this plugin changes it.
  The plugin reads both back every 5 seconds (and one second after each of
  its own power changes) and puts them back. The fan page shows how often it
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

- **Swap menu buttons** puts Steam and Quick Access on the View and Menu buttons and View and Menu on the
  Legion buttons, in any combination:

  | Layout | Legion L / Legion R | View button | Menu button |
  |---|---|---|---|
  | L View, R Menu · View = Steam | View / Menu | Steam | Quick Access |
  | **L View, R Menu · Menu = Steam** (default) | View / Menu | Quick Access | Steam |
  | L Menu, R View · Menu = Steam | Menu / View | Quick Access | Steam |
  | L Menu, R View · View = Steam | Menu / View | Steam | Quick Access |

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

### Device: sound, sleep, Steam mods

**Speaker EQ.** SteamOS plays the speakers without the processing Windows
gives them. The EQ sits in front of the built-in speakers only: headphones,
Bluetooth and USB never get it, and it comes back when they disconnect. Pick
a sound and adjust bass and treble; the presets are starting points tuned by
ear. Your volume stays where it was. It runs as a separate PipeWire client:
nothing is written to SteamOS or your PipeWire settings, and switching it off
removes it.

**Sleep.** Every sleep longer than a minute is measured (hours, battery before
and after, percent per hour). **Power off after a long sleep** sets the
clock's wake alarm before sleeping; if the device is still asleep after the
hours you choose, it wakes and shuts down. Waking it earlier cancels that.
*Only on battery* is on by default. Unsaved game progress is lost, as with any
shutdown. Hibernation, swap and boot settings are not touched.

**Steam update check.** Every minute, and a minute after Steam starts, the
tab checks that each installed Steam client mod (SLSsteam, CloudRedirect,
ASSella / Uran) is still loaded and its settings file is readable, and
notifies you when one stopped working after a Steam update. It only reads.
Their settings files are backed up whenever everything works (last 8 kept)
and can be restored from the tab. **Hold Steam client updates** writes Valve's
`steam.cfg` switch so the client stays on its build until your mods catch up;
SteamOS updates are not affected, and a `steam.cfg` of your own is left alone.

## With frame generation and upscalers

- **HelixSR** (upscaling only): use Smooth mode and Auto TDP as usual; both
  keep HelixSR's launch settings. Auto TDP settles at fewer watts.
- **lsfg-vk 2.0** (frame generation): MangoHud's limiter usually comes after
  lsfg-vk and sees the generated frames too, so the plugin sets it to the
  frame rate on screen (cap × multiplier: 120 for 60 × 2) and the game
  settles at the cap. Where MangoHud comes first (lsfg-vk installed
  system-wide), it caps the game's own frames instead; the plugin tells the
  two apart from where each is installed.
  1. In decky-lsfg-vk turn it on for the game with the multiplier you want
     (for example 2×) and leave its **Base FPS cap off** (More → Frame rate cap
     warns when it is on: two limiters).
  2. More → Frame rate cap: choose the game's cap, for example 60.
     **Frame generation** below it stays on *Auto* and shows what it read,
     for example *Auto · lsfg-vk 2× · 60 → 120 fps*. A multiplier changed in
     decky-lsfg-vk is followed within seconds, even mid-game.
  3. Steam's Framerate limit off. The plugin sets the screen rate for the
     final rate and Auto TDP aims at it (120), not at the cap.
  4. Prefer a fixed value? Pick Off or 2×-4× instead of Auto; More → Frame rate cap
     says when it differs from lsfg-vk's setting.
  5. Even on the Legion Go's 144 Hz screen: 72 × 2 = 144 and 48 × 3 = 144.
     60 × 2 = 120 and 45 × 2 = 90 run at 144 Hz there, marked *uneven*; even on a
     120 Hz monitor (for example when streaming).
- **MAKO** (adaptive frame generation; bundled in Frame Suite 1.2.0 and newer):
  nothing to set. With MAKO's adaptive mode the screen holds MAKO's target
  (for example 72 fps) and MAKO generates whatever the game does not make.
  The plugin reads that target from Frame Suite: Smooth mode puts the screen
  at a rate the target divides (72 → 144 Hz) and its limiter only backs MAKO
  up, Auto TDP finds the least power that keeps the target on screen (so MAKO
  uses its generated frames before watts are added), and Battery playtime
  moves only the power limit, since MAKO already trades real for generated
  frames as power drops. MAKO's fixed mode (2×, 3×) counts like any frame
  generation: cap × frames. A fixed Frame generation setting in Smooth mode
  wins over MAKO. Not verified on a device yet.
- **Frame Suite** (MAKO, decky-lsfg-vk, Decky-Framegen and HelixSR Manager in
  one plugin): nothing to set. Its lsfg-vk games are followed like any other
  lsfg-vk game. For games it set up with OptiScaler, **Frame generation**
  on *Auto* follows the switch **Frame generation is on in the game** in
  Frame Suite: turn that on when you enable frame generation in the game's
  settings and More → Frame rate cap shows *Auto · in-game 2× (Frame Suite) ·
  60 → 120 fps* within seconds, also mid-game. The plugin reads this from
  Frame Suite's own file (`~/.config/frame-suite/bridge.json`) and never
  writes to it. With lsfg-vk on for the same game, lsfg-vk's multiplier
  counts instead, so frames are never multiplied twice. **Battery playtime**
  asks Frame Suite for lsfg-vk through `~/.config/lgo-toolbox/framegen.json`
  (Frame Suite's switch *Let the Legion Go Toolbox use lsfg-vk*, on by default). Not verified on a
  device yet.
- **Decky-Framegen** (OptiScaler frame generation inside the game): the
  plugin sees its wrapper or its DLL override in the game's launch options
  and says so under **Frame generation**. Its frames are made inside the game, so the plugin
  cannot see whether frame generation is switched on there: when you turn it
  on in the game's settings, choose **2×** under Frame generation. The cap
  then counts the frames on screen (60 → 120) and Auto TDP aims at them. Not
  verified on a device yet.
- **External screens with variable refresh (VRR)**: the cap is held just
  below the screen's top rate (116 on 120 Hz, 138 on 144 Hz) so VRR stays
  active. The Legion Go's own screen has no VRR.

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
  slower. The game's real frame rate is what the Game tab shows.
- **Auto TDP stays at the maximum** – the target frame rate is not reachable
  within your maximum TDP; raise the maximum or lower the target.
- **Stick lights or remapping report "controllers not found"** – wake the
  controllers by pressing a button.
- **Menu buttons swap back** – InputPlumber restarted; the plugin re-applies
  the swap within a few seconds.
- Logs: `~/homebrew/logs/Legion Go Toolbox/`.

## Scope and limits

- Used on a Legion Go (83E1), and verified with simulated hardware (161
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
- [Doto](https://github.com/oliverlalan/Doto) – the dot-matrix font, by the
  Doto Project Authors (SIL Open Font License 1.1; a small Latin subset is
  embedded in `src/dot.ts`)

MIT licensed.
