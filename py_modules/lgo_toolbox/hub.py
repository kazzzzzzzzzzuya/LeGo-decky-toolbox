"""Coordinator of the hardware modules.

Keeps the saved settings applied to the device: at start, after resume,
when a controller reconnects, and continuously for the things that need a
watchful eye (automatic TDP, the swapped menu buttons).
"""

import copy
import logging
import os
import threading
import time

from . import config as cfg
from . import acpi_install, controller, fan, fps_probe, sysio
from .battery import ChargeLimit, battery_info, on_external_power
from .plumber import MenuSwap, SteamController
from .power import CUSTOM, AutoTdp, FpsMonitor, PowerLimits, cpu_boost_state, set_cpu_boost
from .powerled import PowerLed
from . import smooth as smoothmod
from .lsfg import Lsfg, homes as user_homes
from .suite import Suite, write_requests
from . import playtime as ptmod

LEGION_GO = ("83E1",)
LEGION_GO_2 = ("83N0", "83N1")
LEGION_GO_S = ("83L3", "83N6", "83Q2", "83Q3")
CONTROLLER_MODELS = LEGION_GO + LEGION_GO_2

TICK_S = 1.0
REASSERT_S = 10.0
SWAP_CHECK_S = 5.0
FAN_CHECK_S = 5.0
POWER_SOURCE_CHECK_S = 2.0
SMOOTH_REASSERT_S = 10.0
RECONNECT_DELAY_S = 2.0
RESUME_DELAY_S = 3.0

SECTIONS = ("lighting", "battery", "fan", "power", "controls", "playtime")
PLAYTIME_SAVE_S = 60.0
REQUEST_REFRESH_S = 60.0     # a live frame-generation request is renewed this often (Frame Suite drops stale ones)


class Hub(object):
    def __init__(self, settings_path, logger=None, product=None, modules=None,
                 controller_status=None, state_dir=None):
        self._path = settings_path
        self._log = logger or logging.getLogger("lgo_toolbox")
        self.product = product if product is not None else sysio.dmi("product_name")
        self.vendor = sysio.dmi("sys_vendor")
        self._state_dir = state_dir
        m0 = modules or {}
        if state_dir and "acpi_installer" not in m0:
            try:
                acpi_install.load_stored(state_dir)   # the module built on this device
            except Exception:
                pass
        self.acpi_installer = m0.get("acpi_installer") or (
            acpi_install.Installer(state_dir, logger=self._log, on_done=self._acpi_installed)
            if state_dir else None)
        self._controller_status = controller_status

        m = modules or {}
        self.limits = m.get("limits") or PowerLimits()
        self.fan = m.get("fan") or fan.FanControl()
        self.charge = m.get("charge") or ChargeLimit()
        self.led = m.get("led") or PowerLed(self.product)
        self.swap = m.get("swap") or MenuSwap(
            state_file=(state_dir + "/inputplumber_base_profile") if state_dir else None)
        self.steam_pad = m.get("steam_pad") or SteamController()
        self.gamescope = m.get("gamescope") or smoothmod.Gamescope()
        self._mangohud_env = m.get("mangohud_env", smoothmod.mangohud_env)
        self.lsfg = m.get("lsfg") or Lsfg()
        self.suite = m.get("suite") or Suite()
        self._home = m.get("home") or (lambda: next(
            (h for h in user_homes() if os.path.isdir(h)), None))
        self._order = m.get("limit_on_output") or smoothmod.limit_on_output
        self._on_output = None      # where MangoHud sits, judged once from the layer folders
        self._conf_written = {}
        self._cap_error = None
        self.fps = m.get("fps") or FpsMonitor(logger=self._log)
        self._send = m.get("send") or controller.send
        self._sensors = m.get("sensors") or fan.read_sensors
        self._battery_info = m.get("battery_info") or battery_info
        self._read_on_ac = m.get("on_ac") or on_external_power
        self._set_boost = m.get("set_boost") or set_cpu_boost
        self._boost_state = m.get("boost_state") or cpu_boost_state
        self._write_requests = m.get("write_requests") or write_requests
        self._wall = m.get("wall") or time.time

        self._lock = threading.RLock()      # settings
        self._hw = threading.RLock()        # one hardware operation at a time
        self.settings = cfg.load(settings_path)
        self.errors = {}
        self._app = None
        self._app_name = ""

        self._thread = None
        self._stop = threading.Event()
        self._auto = None
        self._auto_applied = None
        self._power_applied_at = 0.0
        self._swap_checked = 0.0
        self._fan_checked = 0.0
        self._fan_unverifiable = False
        self._fan_restores = 0
        self._fan_restored_at = None
        self._fan_applied = None
        self._on_ac = None
        self._power_source_checked = 0.0
        self._smooth_applied = 0
        self._smooth_sent_at = 0.0
        self._frame_gen = False
        self._fg_run = 0
        self._display = None
        self._display_at = -1e9
        self._reapply_controller_at = None
        self._reapply_all_at = None
        self._controller_seen = None
        self._led_before_sleep = None
        self._caps = None
        self._caps_at = 0.0
        self._slow = {}
        # Battery playtime (see playtime.py)
        self._pt = None              # Planner for the running game
        self._pt_app = None
        self._pt_ceiling = None      # power limit it allows, None: not limiting
        self._pt_cap = None          # frame cap it uses instead of the Smooth one
        self._pt_fg = None           # frame generation it asked Frame Suite for
        self._pt_last = None
        self._pt_saved_at = 0.0
        self._pt_session = None      # wall-clock time the running game was first seen
        self._pt_sent = None         # last requests written
        self._pt_sent_at = 0.0
        self._pt_error = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lgo-hub", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(8.0)
        self._thread = None
        self.fps.stop()
        try:
            self.led.close()
        except Exception:
            pass

    def _run(self):
        try:
            self.apply_all("start")
        except Exception:
            self._log.exception("Applying the saved settings failed")
        while not self._stop.wait(TICK_S):
            try:
                self._tick(time.monotonic())
            except Exception:
                self._log.exception("Hub tick failed")

    # ------------------------------------------------------------------
    # capabilities
    # ------------------------------------------------------------------

    def capabilities(self, refresh=False):
        now = time.monotonic()
        if self._caps is not None and not refresh and now - self._caps_at < 30.0:
            return self._caps
        is_go = self.product in LEGION_GO
        known = self.product in LEGION_GO + LEGION_GO_2 + LEGION_GO_S
        not_legion = "This is not a supported Legion Go (%s)" % (self.product or "unknown model")

        def cap(ok, reason=None):
            return {"available": bool(ok), "reason": None if ok else reason}

        caps = {}
        caps["power"] = cap(known and self.limits.available(),
                            not_legion if not known else self.limits.unavailable_reason())
        caps["smooth"] = cap(bool(fps_probe.find_sockets()),
                             "Smooth mode only works in Gaming Mode")
        if caps["smooth"]["available"]:
            self.display_info(refresh=True)
        caps["fps"] = cap(bool(fps_probe.find_sockets()) and FpsMonitor.find_python() is not None,
                          "Frame rates can only be measured in Gaming Mode")
        if not is_go:
            caps["fan"] = cap(False, "Fan curves are only supported on the Legion Go (83E1)")
        else:
            caps["fan"] = cap(self.fan.available(),
                              "Needs the acpi_call kernel module: Home tab → Install acpi_call")
        charge = self.charge.status() if known else {"available": False, "error": not_legion}
        caps["charge_limit"] = cap(charge["available"], charge.get("error"))
        caps["power_led"] = cap(self.led.available, self.led.error)
        ctrl_ok = self.product in CONTROLLER_MODELS
        ctrl_reason = "Only for the detachable Legion Go controllers"
        caps["sticks"] = cap(ctrl_ok, ctrl_reason)
        caps["remap"] = cap(ctrl_ok, ctrl_reason)
        caps["swap_menu"] = cap(self.swap.available(), "InputPlumber is not running")
        pads = self.steam_pad.supported()
        caps["steam_gyro"] = cap(bool(pads), "InputPlumber is not running")
        caps["steam_gyro"]["types"] = pads
        self._caps = caps
        self._caps_at = now
        return caps

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------

    def get_settings(self):
        with self._lock:
            return copy.deepcopy(self.settings)

    def _save(self):
        if not cfg.save(self._path, self.settings):
            self._log.warning("Could not write %s", self._path)

    def update(self, patch):
        """Merge a partial settings dict, save it and apply what changed."""
        with self._lock:
            old = self.settings
            new = cfg.merge(old, patch)
            self.settings = new
            self._save()
            changed = [s for s in SECTIONS if old[s] != new[s]]
        for section in changed:
            self._apply_section(section, old)
        return self.get_settings()

    def delete_power_profile(self, key):
        with self._lock:
            if key != "default" and key in self.settings["power"]["profiles"]:
                del self.settings["power"]["profiles"][key]
                self._save()
        self._apply_power(force=True)
        return self.get_settings()

    def reset(self):
        with self._lock:
            old = self.settings
            self.settings = cfg.defaults()
            self._save()
        for section in SECTIONS:
            self._apply_section(section, old)
        return self.get_settings()

    def _acpi_installed(self, ok):
        """The module was just built and loaded: everything that waited for
        it gets applied."""
        if not ok:
            return
        self._caps = None
        self._reapply_all_at = time.monotonic() + 1.0

    def acpi_install_start(self):
        if self.acpi_installer is None:
            return False
        return self.acpi_installer.start()

    # ---- backup ----------------------------------------------------------------
    def restore(self, data):
        """Replace the settings with a backup's (sanitized) and apply them."""
        with self._lock:
            old = self.settings
            self.settings = cfg.sanitize(data)
            self._save()
        for section in SECTIONS:
            self._apply_section(section, old)
        self._apply_smooth(force=True)
        return self.get_settings()

    def set_running_app(self, app_id, name=""):
        try:
            app = int(app_id) if app_id not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            app = None
        if app == self._app:
            return
        self._pt_leave()
        self._app = app
        self._app_name = str(name or "")[:120]
        self._pt_session = self._wall() if app is not None else None
        self._frame_gen = False
        self._fg_run = 0
        self._auto = None
        self._apply_power(force=True)
        self._apply_smooth()
        self._refresh_fan()
        self._apply_steam_pad()

    def steam_controller_for(self, app=None):
        """(type, source) Steam should see: the game's own choice when it
        has one, else the default. source is "game" or "default"."""
        controls = self.settings["controls"]
        app = self._app if app is None else app
        entry = controls["steam_controller_games"].get(str(app)) if app is not None else None
        if entry:
            return entry["type"], "game"
        return controls["steam_controller"], "default"

    def set_game_controller(self, app_id, kind, name=""):
        """Give a game its own controller type (kind None removes it)."""
        key = str(int(app_id))
        if kind is None:
            patch_games = {k: v for k, v in self.settings["controls"]
                           ["steam_controller_games"].items() if k != key}
            with self._lock:
                self.settings["controls"]["steam_controller_games"] = patch_games
                self.settings = cfg.sanitize(self.settings)
                self._save()
        else:
            with self._lock:
                self.settings = cfg.merge(self.settings, {"controls": {
                    "steam_controller_games": {key: {"type": kind, "name": str(name or "")}}}})
                self._save()
        self._apply_steam_pad()
        return self.get_settings()

    # ------------------------------------------------------------------
    # applying
    # ------------------------------------------------------------------

    def _err(self, key, message):
        if message:
            self.errors[key] = str(message)
            self._log.warning("%s: %s", key, message)
        else:
            self.errors.pop(key, None)

    def apply_all(self, reason=""):
        self._log.info("Applying saved settings (%s)", reason)
        self.capabilities(refresh=True)
        self._apply_battery()
        self._apply_power_led()
        self._apply_power(force=True)
        self._apply_fan()
        self._apply_controller()
        self._apply_steam_pad()
        self._apply_swap()

    def _apply_section(self, section, old):
        if section == "lighting":
            new = self.settings["lighting"]
            if old["lighting"]["sticks"] != new["sticks"]:
                self._apply_sticks()
            if old["lighting"]["power_led"] != new["power_led"]:
                self._apply_power_led()
        elif section == "battery":
            self._apply_battery()
        elif section == "fan":
            self._apply_fan(was_enabled=old["fan"]["enabled"])
        elif section == "power":
            self._apply_power(force=True, was_enabled=old["power"]["enabled"])
        elif section == "playtime":
            self._pt_reset_if_changed(old["playtime"])
        elif section == "controls":
            o, n = old["controls"], self.settings["controls"]
            changed_pad = (o["steam_controller"], o["steam_controller_games"]) != (
                n["steam_controller"], n["steam_controller_games"])
            if not (changed_pad and self._apply_steam_pad()) and \
                    (o["swap_menu"], o["swap_layout"]) != (n["swap_menu"], n["swap_layout"]):
                self._apply_swap()
            if (o["remap"], o["remap_managed"], o["touchpad"]) != (
                    n["remap"], n["remap_managed"], n["touchpad"]):
                self._apply_remap(restore=o["remap_managed"] and not n["remap_managed"])

    # ---- battery -----------------------------------------------------------
    def _apply_battery(self):
        want = self.settings["battery"]["charge_limit"]
        if want is None:
            return
        with self._hw:
            status = self.charge.set(want)
        self._invalidate("charge")
        if not status["available"]:
            self._err("charge_limit", status.get("error") or "Not available")
        else:
            self._err("charge_limit", status.get("error"))

    # ---- lighting ----------------------------------------------------------
    def _apply_power_led(self):
        conf = self.settings["lighting"]["power_led"]
        if not conf["managed"]:
            return
        with self._hw:
            if not self.led.available:
                self._err("power_led", self.led.error)
                return
            ok = self.led.set(conf["on"])
        self._invalidate("led")
        self._err("power_led", None if ok else (self.led.error or "The light did not change"))

    def _apply_sticks(self):
        conf = self.settings["lighting"]["sticks"]
        if not conf["managed"] or self.product not in CONTROLLER_MODELS:
            return
        if conf["on"]:
            cmds = controller.rgb_commands(
                conf["mode"], conf["color"], conf["brightness"], conf["speed"])
        else:
            cmds = controller.rgb_off_commands()
        with self._hw:
            self._err("sticks", self._send(cmds))

    # ---- controls ----------------------------------------------------------
    def _apply_remap(self, restore=False):
        conf = self.settings["controls"]
        if self.product not in CONTROLLER_MODELS:
            return
        cmds = []
        if conf["remap_managed"]:
            cmds += [controller.remap_command(b, conf["remap"][b])
                     for b in controller.REMAP_BUTTONS]
        elif restore:
            cmds += [controller.remap_command(b, "none") for b in controller.REMAP_BUTTONS]
        if conf["touchpad"] is not None:
            cmds.append(controller.touchpad_command(conf["touchpad"]))
        if cmds:
            with self._hw:
                self._err("remap", self._send(cmds))

    def _apply_controller(self):
        self._apply_sticks()
        self._apply_remap()

    def _apply_steam_pad(self):
        """Make InputPlumber present the right controller type. Returns True
        if the controller was switched (it reconnects when that happens)."""
        want, _ = self.steam_controller_for()
        with self._hw:
            if not self.steam_pad.needs_apply(want):
                return False
            ok = self.steam_pad.apply(want)
        self._err("steam_gyro", None if ok else self.steam_pad.error)
        if ok:
            # A new virtual controller can start with the base profile:
            # put the menu-button swap back on top.
            time.sleep(1.0)
            self._apply_swap()
        return ok

    def _apply_swap(self):
        want = self.settings["controls"]["swap_menu"]
        layout = self.settings["controls"]["swap_layout"]
        with self._hw:
            if not want and not self.swap.available():
                self._err("swap_menu", None)
                return
            ok = self.swap.apply(want, layout)
        self._invalidate("swap")
        self._err("swap_menu", None if ok else self.swap.error)

    # ---- fan ---------------------------------------------------------------
    def on_ac(self):
        """True on the charger, False on battery (unknown counts as battery)."""
        if self._on_ac is None:
            try:
                self._on_ac = self._read_on_ac()
            except Exception:
                self._on_ac = None
        return bool(self._on_ac)

    def fan_profile_chain(self, app=None, ac=None):
        """Profile keys from most to least specific for a game and power
        source; the first one that exists is used."""
        f = self.settings["fan"]
        app = self._app if app is None else app
        ac = self.on_ac() if ac is None else ac
        game = str(app) if (f["per_game"] and app is not None) else None
        charger = bool(f["per_power"] and ac)
        chain = []
        if game and charger:
            chain.append(game + ":ac")
        if game:
            chain.append(game)
        if charger:
            chain.append("default:ac")
        chain.append("default")
        return chain

    def active_fan_profile(self):
        profiles = self.settings["fan"]["profiles"]
        for key in self.fan_profile_chain():
            if key in profiles:
                return key, profiles[key]
        return "default", profiles["default"]

    def fan_conf(self):
        """The fan settings in effect right now."""
        _, profile = self.active_fan_profile()
        return {"enabled": self.settings["fan"]["enabled"],
                "full_speed": profile["full_speed"], "curve": profile["curve"]}

    def _refresh_fan(self):
        """Apply the fan profile if the game or power source changed it."""
        conf = self.fan_conf()
        if not conf["enabled"] or self.product not in LEGION_GO:
            return
        if self._fan_applied != (conf["full_speed"], tuple(conf["curve"])):
            self._apply_fan()

    def delete_fan_profile(self, key):
        with self._lock:
            if key != "default" and key in self.settings["fan"]["profiles"]:
                del self.settings["fan"]["profiles"][key]
                self._save()
        self._refresh_fan()
        return self.get_settings()

    def _apply_fan(self, was_enabled=False):
        conf = self.fan_conf()
        if self.product not in LEGION_GO:
            return
        with self._hw:
            if not conf["enabled"]:
                self._fan_applied = None
                if was_enabled and self.fan.available():
                    self.fan.restore()
                self._err("fan", None)
                return
            if not self.fan.available():
                self._err("fan", "Needs the acpi_call kernel module")
                return
            power = self.settings["power"]
            managed_mode = self.active_profile()[1]["mode"] if power["enabled"] else None
            if managed_mode not in (None, CUSTOM) and not conf["full_speed"]:
                # The firmware only follows a custom table in its custom mode.
                self._err("fan", None)
                return
            ok = self.fan.apply(conf["curve"], conf["full_speed"],
                                ensure_custom=managed_mode is None)
            self._fan_unverifiable = False
            self._fan_applied = (conf["full_speed"], tuple(fan.sanitize_curve(conf["curve"]))) \
                if ok else None
        self._err("fan", None if ok else self.fan.error)

    def _fan_check_soon(self):
        """After a power-mode or TDP write: the firmware may have dropped the
        fan settings, so look again in a second instead of in five."""
        self._fan_checked = time.monotonic() - FAN_CHECK_S + 1.0

    def _check_fan(self, now):
        """Read the firmware's fan state back and restore what it dropped.

        The firmware resets "full speed" and the custom table whenever the
        power mode changes - whoever changes it. Without this check the fan
        would silently fall back to the stock curve.
        """
        conf = self.fan_conf()
        if not conf["enabled"] or self.product not in LEGION_GO:
            return
        if not self.fan.available():
            return
        power = self.settings["power"]
        managed_mode = self.active_profile()[1]["mode"] if power["enabled"] else None
        with self._hw:
            if conf["full_speed"]:
                if self._fan_unverifiable or self.fan.read_full_speed() is not False:
                    return
                self._log.info("Full fan speed was switched off by the firmware; turning it back on")
                ok = self.fan.apply(conf["curve"], True)
                if ok and self.fan.read_full_speed() is False:
                    # The firmware takes the command but does not report it
                    # as on: comparing would re-send it forever.
                    self._fan_unverifiable = True
                    self._log.warning("Full fan speed reads back as off right after "
                                      "turning it on; not checking it any more")
            else:
                if managed_mode not in (None, CUSTOM) or self._fan_unverifiable:
                    return
                current = self.fan.read_curve()
                want = fan.sanitize_curve(conf["curve"])
                if current is None or tuple(current) == want:
                    return
                self._log.info("The firmware is not using the custom fan curve; restoring it")
                ok = self.fan.apply(want, False, ensure_custom=managed_mode is None)
                after = self.fan.read_curve() if ok else None
                if after is not None and tuple(after) != want:
                    # The firmware reports the table differently from how it
                    # was written: stop comparing, keep re-applying on mode
                    # changes only.
                    self._fan_unverifiable = True
                    self._log.warning("Fan curve read-back %s does not match %s; "
                                      "not checking it any more", list(after), list(want))
        self._fan_restores += 1
        self._fan_restored_at = now
        self._err("fan", None if ok else self.fan.error)

    # ---- power ---------------------------------------------------------------
    def active_profile(self):
        """(key, profile) the power module uses right now."""
        key, profile = self._own_profile()
        if self._pt_ceiling is not None and self._app is not None:
            # Battery playtime: its power limit, set in watts whatever mode the profile uses.
            rng = self.limits.tdp_range() or (cfg.TDP_ABS_MIN, cfg.TDP_ABS_MAX)
            top = profile["tdp"] if profile["mode"] == CUSTOM else rng[1]
            ceiling = min(top, self._pt_ceiling)
            profile = dict(profile, mode=CUSTOM, tdp=ceiling,
                           min_tdp=min(profile["min_tdp"], ceiling))
        return key, profile

    def _own_profile(self):
        power = self.settings["power"]
        key = str(self._app) if self._app is not None else None
        if power["per_game"] and key and key in power["profiles"]:
            return key, power["profiles"][key]
        return "default", power["profiles"]["default"]

    def _tdp_bounds(self, profile):
        rng = self.limits.tdp_range() or (cfg.TDP_ABS_MIN, cfg.TDP_ABS_MAX)
        top = max(rng[0], min(rng[1], profile["tdp"]))
        low = max(rng[0], min(top, profile["min_tdp"]))
        return low, top

    def _apply_power(self, force=False, was_enabled=False):
        power = self.settings["power"]
        with self._hw:
            if not power["enabled"]:
                self._auto = None
                self.fps.set_app(self._measure_app())
                if was_enabled and self.limits.available():
                    # Hand the device back in a normal firmware mode.
                    choices = self.limits.profiles()
                    for name in ("balanced", "performance"):
                        if name in choices:
                            self.limits.set_profile(name)
                            break
                self._err("power", None)
                return
            if not self.limits.available():
                self._err("power", self.limits.unavailable_reason())
                return
            if power["cpu_boost"] is not None:
                self._set_boost(power["cpu_boost"])
            _, profile = self.active_profile()
            self._power_applied_at = time.monotonic()
            if profile["mode"] != CUSTOM:
                self._auto = None
                self.fps.set_app(self._measure_app())
                ok = self.limits.profile() == profile["mode"] or \
                    self.limits.set_profile(profile["mode"])
                self._fan_check_soon()
                self._err("power", None if ok else self.limits.error)
                return
            low, top = self._tdp_bounds(profile)
            if profile["auto"]:
                if self._auto is None or force:
                    start = self._auto.tdp if self._auto is not None else top
                    target = self._auto_target(profile)
                    known = self._learned(target)
                    if known is not None:
                        start = known      # where this game settled last time
                    self._auto = AutoTdp(low, top, target, start=start)
                    self._auto_applied = None
                else:
                    self._auto.retarget(low, top, self._auto_target(profile))
                self.fps.set_app(self._app)
                want = self._auto.tdp if self._app is not None else top
            else:
                self._auto = None
                self.fps.set_app(self._measure_app())
                want = top
            was_custom = self.limits.profile() == CUSTOM
            ok = self.limits.set_tdp(want)
            self._auto_applied = want if ok else None
            self._fan_check_soon()
            self._err("power", None if ok else self.limits.error)
        if ok and not was_custom and self.settings["fan"]["enabled"]:
            time.sleep(0.5)
            self._apply_fan()

    # ---- smooth mode ---------------------------------------------------------
    def smooth_for(self, app=None):
        """The game's Smooth entry as it applies now: with a lower cap while
        Battery playtime uses one."""
        app = self._app if app is None else app
        if app is None:
            return None
        entry = self.settings["smooth"]["games"].get(str(app))
        if entry and self._pt_cap is not None and app == self._app and self._pt_cap < entry["fps"]:
            entry = dict(entry, fps=self._pt_cap)
        return entry

    def _fg(self, entry, app=None):
        """The game's frame-generation multiplier: fixed in Smooth mode, or
        (setting 0, the default) read from lsfg-vk's own settings and, where
        lsfg-vk is off for the game, from what Frame Suite was told about
        the game's own frame generation."""
        fg = entry.get("fg", cfg.FG_AUTO)
        if fg == cfg.FG_AUTO:
            app = self._app if app is None else app
            if app is None:
                return 1
            mult = self.lsfg.for_app(app)["multiplier"]
            if mult > 1:
                return mult
            mako = self._mako(app)
            if mako:
                return mako["multiplier"]
            return self.suite.for_app(app)["multiplier"]
        return fg

    def _mako(self, app=None):
        """MAKO's frame generation for the game (via Frame Suite), or None."""
        app = self._app if app is None else app
        return self.suite.for_app(app).get("mako") if app is not None else None

    def _mako_adaptive(self, entry=None, app=None):
        """MAKO holds a frame rate on screen by itself (its adaptive mode, and Smooth's frame
        generation left on Auto): that rate, or None."""
        if entry is not None and entry.get("fg", cfg.FG_AUTO) != cfg.FG_AUTO:
            return None
        app = self._app if app is None else app
        if app is None or self.lsfg.for_app(app)["multiplier"] > 1:
            return None
        mako = self._mako(app)
        return mako["target_fps"] if mako and mako["adaptive"] else None

    def _in_game(self, entry, app=None):
        """Frame generation, if on, is made inside the game (OptiScaler, set
        up by Decky-Framegen or Frame Suite) and not by lsfg-vk: a limiter
        then sees the generated frames too, wherever it sits."""
        app = self._app if app is None else app
        if app is None:
            return bool(entry.get("fgmod"))
        if self.lsfg.for_app(app)["multiplier"] > 1:
            return False
        # MAKO's frames pass MangoHud too (MAKO counts them by default): the limiter sees the screen.
        return bool(entry.get("fgmod")) or self.suite.for_app(app)["optiscaler"] or bool(self._mako(app))

    def _smooth_output(self, entry):
        """Frames on screen: the game's cap times the frame-generation
        multiplier (lsfg-vk sits after MangoHud's limiter, so the cap holds
        the game's own frames and the generated ones come on top)."""
        return entry["fps"] * self._fg(entry)

    def _measure_app(self):
        """The game whose frame rate is measured: needed for Smooth mode's
        readout even when Auto TDP is off."""
        return self._app if self.smooth_for() or self._pt_goal() else None

    FG_RATIO = 1.5      # shown frames this far above the cap: frame generation
    FG_READINGS = 3

    def _auto_target(self, profile):
        """Auto TDP aims at what the screen should show for the game's Smooth
        setting: the cap, or cap x multiplier with frame generation set. With
        frame generation it was not told about (more frames shown than the
        cap allows), the profile's target (the final frame rate) is used."""
        entry = self.smooth_for()
        target = self._mako_adaptive(entry)
        if target:
            # MAKO generates whatever the game does not make: Auto TDP keeps its rate on screen, at the
            # least power, and so lets MAKO use its most generated frames before adding watts.
            return self._vrr_capped(target)
        if entry and (self._fg(entry) > 1 or not self._frame_gen):
            return self._shown(entry)
        return profile["target_fps"]

    def _watch_frame_gen(self, fps):
        entry = self.smooth_for()
        if not entry or fps is None or self._frame_gen or self._fg(entry) > 1:
            return False
        self._fg_run = self._fg_run + 1 if fps > entry["fps"] * self.FG_RATIO else 0
        if self._fg_run >= self.FG_READINGS:
            self._frame_gen = True
            self._log.info("Frame generation detected (%.0f fps shown, cap %d): "
                           "Auto TDP uses the target frame rate", fps, entry["fps"])
            return True
        return False

    def display_info(self, refresh=False):
        now = time.monotonic()
        if refresh or now - self._display_at > 30.0:
            self._display_at = now
            info = self.gamescope.display()
            if info is not None:
                self._display = info
        return self._display

    def smooth_plan(self, fps, app_id=None):
        """Launch-option text for a cap, and which limiter it uses. With
        MangoHud and a game, the cap lives in a file the plugin keeps up to
        date (cap changes and frame generation apply while the game runs)."""
        env = self._mangohud_env() if callable(self._mangohud_env) else self._mangohud_env
        conf = None
        home = self._home() if env and app_id is not None else None
        if home:
            conf = smoothmod.conf_path(home, app_id)
            entry = {"fps": int(fps), "fg": cfg.FG_AUTO}
            old = self.settings["smooth"]["games"].get(str(int(app_id)))
            if old:
                entry["fg"] = old.get("fg", cfg.FG_AUTO)
            if not self._write_limit(conf, self._mh_limit(entry, int(app_id))):
                conf = None
        prefix = smoothmod.launch_prefix(fps, env, conf)
        live = "MANGOHUD_CONFIGFILE=" in prefix
        return {"prefix": prefix, "live": live,
                "limiter": "mangohud" if env else "dxvk"}

    # ---- MangoHud's cap with frame generation ----------------------------------
    def limit_on_output(self):
        if self._on_output is None:
            try:
                self._on_output = bool(self._order(self._home()))
            except Exception:
                self._on_output = True
        return self._on_output

    def _shown(self, entry, app=None):
        """Frames on screen Smooth mode aims at: cap x multiplier, kept just
        below the top rate of a variable-refresh screen so VRR stays active."""
        target = self._mako_adaptive(entry, app)
        shown = target if target else entry["fps"] * self._fg(entry, app)
        return self._vrr_capped(shown)

    def _vrr_capped(self, shown):
        info = self._display
        if info and info["vrr"] and info["rates"]:
            shown = min(shown, smoothmod.vrr_cap(info["rates"]))
        return shown

    def _mh_limit(self, entry, app=None):
        """MangoHud's fps_limit for a Smooth entry. Where MangoHud sees the
        generated frames too (after lsfg-vk, or with frame generation made
        inside the game by OptiScaler / Decky-Framegen), its cap is the frame
        rate on screen. Otherwise it is the game's own share of it."""
        fg = self._fg(entry, app)
        shown = self._shown(entry, app)
        if fg <= 1:
            return shown
        if self._in_game(entry, app) or self.limit_on_output():
            return shown
        return min(entry["fps"], shown // fg)

    def _write_limit(self, path, limit):
        if self._conf_written.get(path) == limit:
            return True
        ok = smoothmod.write_conf(path, limit)
        if ok:
            self._conf_written[path] = limit
            self._cap_error = None
        else:
            self._conf_written.pop(path, None)
            self._cap_error = "Could not write the frame cap file %s" % path
        self._err("smooth", self._cap_error)
        return ok

    def _sync_limit(self):
        """Keep the running game's live cap file in step (cap, lsfg-vk's
        multiplier, where the limiter sits)."""
        entry = self.smooth_for()
        path = smoothmod.conf_from_prefix(entry["prefix"]) if entry else None
        if path:
            self._write_limit(path, self._mh_limit(entry))

    def set_smooth_game(self, app_id, fps, name="", prefix="", added_command=False,
                        fg=cfg.FG_AUTO, fgmod=False):
        """Store a game's Smooth cap (fps None removes it) and its frame-
        generation multiplier. The frontend has already changed the game's
        launch options accordingly."""
        key = str(int(app_id))
        with self._lock:
            games = dict(self.settings["smooth"]["games"])
            if fps is None:
                old = games.pop(key, None)
                path = smoothmod.conf_from_prefix(old["prefix"]) if old else None
                if path:
                    # A running game keeps reading the file: lift the cap now.
                    self._write_limit(path, 0)
            else:
                games[key] = {"fps": int(fps), "name": str(name or ""), "prefix": str(prefix),
                              "added_command": bool(added_command), "fg": fg,
                              "fgmod": bool(fgmod)}
            self.settings = cfg.sanitize(dict(self.settings, smooth={"games": games}))
            self._save()
        self._frame_gen = False
        self._fg_run = 0
        self._apply_smooth(force=True)
        if self._auto is not None:
            _, profile = self.active_profile()
            low, top = self._tdp_bounds(profile)
            self._auto.retarget(low, top, self._auto_target(profile))
        return self.get_settings()

    def _apply_smooth(self, force=False):
        """Switch the refresh rate for the running game's cap, or hand the
        refresh rate back when it has none."""
        self._sync_limit()
        entry = self.smooth_for()
        want = self._shown(entry) if entry else 0
        if want == self._smooth_applied and not force:
            return
        if want == 0 and self._smooth_applied == 0:
            return
        info = self.display_info()
        internal = True if info is None else info["internal"]
        if self._auto is None:
            self.fps.set_app(self._measure_app())
        request = smoothmod.refresh_request(
            want, info["rates"] if info else [], bool(info and info["vrr"])) if want else 0
        ok = self.gamescope.set_refresh(request, internal)
        self._smooth_sent_at = time.monotonic()
        if ok:
            self._smooth_applied = want
        self._err("smooth", self._cap_error if ok else self.gamescope.error)

    def _smooth_status(self):
        info = self._display
        rates = info["rates"] if info else []
        entry = self.smooth_for()
        fps = entry["fps"] if entry else None
        output = self._shown(entry) if entry else None
        lsfg = self.lsfg.for_app(self._app) if self._app is not None else None
        suite = self.suite.for_app(self._app) if self._app is not None else None
        return {
            "fps": fps,
            "fg": self._fg(entry) if entry else 1,           # in effect
            "fg_setting": entry.get("fg", cfg.FG_AUTO) if entry else cfg.FG_AUTO,
            "fgmod": bool(entry and (entry.get("fgmod") or (suite and suite["optiscaler"]))),
            "suite": suite,
            "mako": suite.get("mako") if suite else None,
            "mako_adaptive": self._mako_adaptive(entry) if self._app is not None else None,
            "shown": self._shown(entry) if entry else None,   # after the VRR cap
            "lsfg": lsfg,
            "output": output,
            "refresh": smoothmod.screen_rate(output, rates, bool(info and info["vrr"]))
            if output else None,
            "rates": rates,
            "vrr": bool(info and info["vrr"]),
            "choices": smoothmod.fps_choices(rates),
            "active": bool(self._smooth_applied),
            "measured": {"fps": self.fps.get(), "low": self.fps.get_low()} if entry else None,
        }

    # ---- battery playtime ---------------------------------------------------------
    def _pt_goal(self, app=None):
        app = self._app if app is None else app
        return self.settings["playtime"]["games"].get(str(app)) if app is not None else None

    def set_playtime_goal(self, app_id, hours, floor=30, allow_fg=True, name=""):
        """Set (hours None: remove) a game's battery goal. Counting starts again."""
        key = str(int(app_id))
        info = self._battery_info() or {}
        power_was = self.settings["power"]["enabled"]
        with self._lock:
            pt = copy.deepcopy(self.settings["playtime"])
            if hours is None:
                pt["games"].pop(key, None)
            else:
                old = pt["games"].get(key) or {}
                pt["games"][key] = {
                    "hours": float(hours), "floor": int(floor), "allow_fg": bool(allow_fg),
                    "name": str(name or old.get("name") or "")[:120],
                    "played_s": 0.0 if float(hours) != old.get("hours") else old.get("played_s", 0.0),
                    "last_pct": info.get("percent"),
                }
            new = dict(self.settings, playtime=pt)
            if hours is not None and not power_was:
                # The goal works through the power limit: power management comes on with it.
                new["power"] = dict(new["power"], enabled=True)
            self.settings = cfg.sanitize(new)
            self._save()
        self._pt_drop()
        if hours is not None and not power_was:
            self._apply_power(force=True)
        return self.get_settings()      # the next tick (within a second) takes it from here

    def restart_playtime(self, app_id):
        key = str(int(app_id))
        with self._lock:
            goal = self.settings["playtime"]["games"].get(key)
            if goal:
                goal["played_s"] = 0.0
                self._save()
        return self.get_settings()

    def _pt_reset_if_changed(self, old):
        new = self.settings["playtime"]
        key = str(self._app) if self._app is not None else None
        if key and (old["games"].get(key) or {}).get("hours") != (new["games"].get(key) or {}).get("hours"):
            self._pt_drop()

    def _pt_save(self, force=False):
        """Played time and what the game draws, kept across restarts."""
        pt, app = self._pt, self._pt_app
        if pt is None or app is None:
            return
        with self._lock:
            data = copy.deepcopy(self.settings["playtime"])
            data["learned"][str(app)] = pt.model.to_json()
            if data != self.settings["playtime"] or force:
                self.settings = dict(self.settings, playtime=data)
                self._save()

    def _pt_drop(self):
        """Forget the running game's planner (goal changed): start fresh."""
        had = self._pt_ceiling is not None or self._pt_cap is not None or self._pt_fg is not None
        if self._pt is not None:
            self._pt_save()
        self._pt = None
        self._pt_ceiling = self._pt_cap = self._pt_fg = None
        if had:
            self._apply_power()
            self._apply_smooth(force=True)

    def _pt_leave(self):
        self._pt_drop()
        self._pt_app = None

    def _even(self, fps):
        info = self._display
        if not info or info["vrr"] or not info["rates"]:
            return True
        return any(r % int(fps) == 0 for r in info["rates"])

    def _pt_steps(self, app, goal):
        """The settings the planner may step through for this game, and why
        frame generation is not among them (or None)."""
        entry = self.settings["smooth"]["games"].get(str(app))
        if self._mako_adaptive(entry, app):
            # MAKO already trades real for generated frames as power drops: only the power limit moves.
            return [(None, None)], "mako"
        if not entry or not smoothmod.conf_from_prefix(entry["prefix"]):
            return [(None, None)], "no_cap"
        suite = self.suite.for_app(app)
        lsfg = self.lsfg.for_app(app)
        own_fg = lsfg["multiplier"] if not suite["fg_applied"] else 1
        why = None
        if not goal["allow_fg"]:
            why = "off"
        elif app >= 0x80000000:
            why = "shortcut"
        elif not suite["lsfg_ready"]:
            why = "no_suite"
        elif suite["multiplier"] > 1 or entry["fg"] > 1 or own_fg > 1:
            why = "has_fg"
        elif entry["fg"] != cfg.FG_AUTO:
            why = "fixed_off"
        elif suite["standby_since"] is None:
            why = "preparing" if not suite["fg_refused"] else "refused"
        elif self._pt_session is not None and suite["standby_since"] > self._pt_session - 5:
            why = "next_start"     # lsfg-vk only looks at its settings when the game starts
        fg_ready = why is None
        return ptmod.steps(entry["fps"], own_fg, goal["floor"], smoothmod.CANDIDATES,
                           self._even, fg_ready), (why if why != "has_fg" else None)

    def _current_tdp(self):
        """The power limit in effect: the one this plugin set, else what the system
        reports (read at most every 10 s), so the estimate also works without
        power management."""
        if self.settings["power"]["enabled"] and self._auto_applied is not None:
            return self._auto_applied
        value = self._cached("tdp", self.limits.tdp, ttl=10.0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    def _game_fps(self):
        """Frames the game itself makes: the measured (shown) rate without
        what frame generation adds. With MAKO's adaptive mode that is not
        known: the fewest it can be (shown / its most generated frames)."""
        fps = self.fps.get()
        entry = self.smooth_for()
        mako = self._mako()
        if fps is not None and mako and self._mako_adaptive(entry):
            return fps / max(1, mako["max_multiplier"])
        fg = self._fg(entry) if entry else 1
        return fps / fg if fps is not None and fg > 1 else fps

    def _pt_requests(self):
        """What Frame Suite is asked for: lsfg-vk on standby for every game
        with a goal that may use frame generation, switched on for the
        running one while its step needs it."""
        out = {}
        for key, goal in self.settings["playtime"]["games"].items():
            if goal["allow_fg"] and int(key) < 0x80000000:
                out[key] = {"standby": True, "multiplier": None}
        if self._pt_fg and self._app is not None and str(self._app) in out:
            out[str(self._app)]["multiplier"] = int(self._pt_fg)
        return out

    def _pt_send(self, now):
        want = self._pt_requests()
        live = any(v["multiplier"] for v in want.values())
        if want == self._pt_sent and not (live and now - self._pt_sent_at >= REQUEST_REFRESH_S):
            return
        home = self.suite.home() if hasattr(self.suite, "home") else None
        err = self._write_requests(home, want)
        self._pt_error = err
        if err:
            self._log.warning("Frame generation request: %s", err)
            return
        self._pt_sent = want
        self._pt_sent_at = now

    def _playtime_step(self, now):
        dt = 0.0 if self._pt_last is None else min(5.0, max(0.0, now - self._pt_last))
        self._pt_last = now
        app = self._app
        goal = self._pt_goal()
        self._pt_send(now)
        if app is None:
            return
        info = self._battery_info() or {}
        on_battery = info.get("status") == "Discharging" or (
            info.get("status") not in ("Charging", "Full") and not self.on_ac())
        _, own = self._own_profile()
        rng = self.limits.tdp_range() or (cfg.TDP_ABS_MIN, cfg.TDP_ABS_MAX)
        tdp_max = self._tdp_bounds(own)[1] if own["mode"] == CUSTOM else rng[1]
        if self._pt is None or self._pt_app != app:
            learned = self.settings["playtime"]["learned"].get(str(app))
            start = self._auto_applied or tdp_max
            self._pt = ptmod.Planner(goal["hours"] if goal else ptmod.MAX_HOURS,
                                     goal["floor"] if goal else 30, rng[0], tdp_max,
                                     min(start, tdp_max), ptmod.Model(learned))
            self._pt_app = app
        pt = self._pt
        pt.tdp_max = int(tdp_max)
        pt.ceiling = min(pt.ceiling, pt.tdp_max)
        if on_battery:
            pt.add(now, info.get("watts"))
        applied = self._current_tdp()
        fps = self._game_fps()

        if goal and on_battery:
            pct = info.get("percent")
            with self._lock:
                g = self.settings["playtime"]["games"].get(str(app))
                if g is not None:
                    last = g.get("last_pct")
                    if isinstance(pct, int) and isinstance(last, int) and pct >= last + 10:
                        g["played_s"] = 0.0          # charged since: a new battery, a new count
                    g["played_s"] = min(g["played_s"] + dt, 7 * 86400.0)
                    if isinstance(pct, int):
                        g["last_pct"] = pct
        if now - self._pt_saved_at >= PLAYTIME_SAVE_S:
            self._pt_saved_at = now
            self._pt_save(force=bool(goal and on_battery))

        active = bool(goal) and on_battery and self.settings["power"]["enabled"] and \
            self.limits.available()
        if not active:
            if on_battery:
                pt.observe(now, applied, fps)
            if self._pt_ceiling is not None or self._pt_cap is not None or self._pt_fg is not None:
                self._pt_ceiling = self._pt_cap = self._pt_fg = None
                pt.step = 0
                pt.ceiling = pt.tdp_max
                self._apply_power()
                self._apply_smooth(force=True)
                self._pt_send(now)
            return

        steps, _ = self._pt_steps(app, goal)
        usable = ptmod.usable_wh(info.get("energy_wh"), info.get("full_wh"))
        played_h = goal["played_s"] / 3600.0
        entry = self.smooth_for()
        cap = entry["fps"] if entry else None
        mako = self._mako()
        if mako and self._mako_adaptive(entry):
            # MAKO holds its target while the game makes at least target / its most frames.
            cap = mako["target_fps"] / float(max(1, mako["max_multiplier"]))
        ceiling, step = pt.tick(now, usable, played_h, applied, fps, cap, len(steps))
        step = min(step, len(steps) - 1)
        pt.step = step
        want_cap, want_fg = steps[step]
        want_cap = want_cap if step > 0 else None
        changed = False
        if ceiling != self._pt_ceiling:
            self._pt_ceiling = ceiling
            self._apply_power()
        if want_fg != self._pt_fg:
            if want_fg or self.lsfg.for_app(app)["multiplier"] <= 1 or not self._pt_fg:
                self._pt_fg = want_fg
                changed = True
            else:
                # Switching frame generation off: keep the low cap until lsfg-vk is back
                # at 1x, or the game would briefly run at twice the frames.
                self._pt_fg = None
                want_cap = self._pt_cap
                changed = True
        elif self._pt_fg is None and self._pt_cap is not None and want_cap != self._pt_cap and \
                self.lsfg.for_app(app)["multiplier"] > 1 and self.suite.for_app(app)["fg_applied"]:
            want_cap = self._pt_cap        # still waiting for lsfg-vk to switch off
        if want_cap != self._pt_cap:
            self._pt_cap = want_cap
            changed = True
        if changed:
            self._pt_send(now)
            self._apply_smooth(force=True)
            if self._auto is not None:
                _, profile = self.active_profile()
                low, top = self._tdp_bounds(profile)
                self._auto.retarget(low, top, self._auto_target(profile))

    def _playtime_status(self):
        app = self._app
        info = self._battery_info() or {}
        goal = self._pt_goal()
        pt = self._pt if self._pt_app == app else None
        usable = ptmod.usable_wh(info.get("energy_wh"), info.get("full_wh"))
        out = {"app": app, "goal": None, "draw_w": None, "budget_w": None, "now_h": None,
               "max_h": None, "left_h": None, "reachable": None, "state": None,
               "step": None, "ceiling": self._pt_ceiling, "cap": self._pt_cap,
               "fg": self._pt_fg, "fg_why": None, "steps": [],
               "on_battery": info.get("status") == "Discharging",
               "power_enabled": self.settings["power"]["enabled"],
               "error": self._pt_error}
        if usable is not None and info.get("watts") and out["on_battery"]:
            out["now_h"] = ptmod.fmt_hours(usable / max(0.5, info["watts"]))
        if app is None or pt is None:
            return out
        played_h = goal["played_s"] / 3600.0 if goal else 0.0
        applied = self._current_tdp()
        est = pt.estimate(usable, played_h, applied, self._game_fps())
        out.update(est)
        if not goal:
            out["left_h"] = out["budget_w"] = out["reachable"] = None
        else:
            steps, why = self._pt_steps(app, goal)
            out.update(goal=dict(goal), state=pt.state if self._pt_ceiling is not None else None,
                       step=pt.step if self._pt_ceiling is not None else None,
                       steps=[[c, f] for c, f in steps], fg_why=why)
        return out

    # ---- Auto TDP memory -----------------------------------------------------------
    def _learn_key(self):
        if self._app is None:
            return None
        return "%d:ac" % self._app if self.on_ac() else str(self._app)

    def _learned(self, target):
        """Watts Auto TDP settled at for the running game on this power
        source and target, or None."""
        key = self._learn_key()
        entry = self.settings["power"].get("learned", {}).get(key) if key else None
        if entry and entry["target"] == int(round(target)):
            return entry["tdp"]
        return None

    def _remember(self, auto):
        if auto.state not in ("optimal", "at_min") or auto.target < 15:
            return
        key = self._learn_key()
        new = {"tdp": int(auto.tdp), "target": int(round(auto.target))}
        if key is None or self.settings["power"].get("learned", {}).get(key) == new:
            return
        with self._lock:
            power = dict(self.settings["power"])
            power["learned"] = dict(power.get("learned", {}), **{key: new})
            self.settings = dict(self.settings, power=power)
            self._save()

    def _smooth_floor(self, target):
        """Slowest-frame rate that is still even for `target` on this screen:
        a screen at a rate the target does not divide holds some frames one
        refresh longer (90 fps at 144 Hz: 72 fps frames)."""
        info = self._display
        if not self.smooth_for() or not info or info["vrr"] or not target:
            return None
        rate = smoothmod.screen_rate(int(round(target)), info["rates"])
        if not rate:
            return None
        return rate / float(-(-rate // int(round(target))))

    def _auto_step(self, now):
        auto = self._auto
        if auto is None or not self.settings["power"]["enabled"]:
            return
        if self._app is None:
            want = auto.tdp_max
            auto.state = "no_game"
        else:
            fps = self.fps.get()
            detected = self._watch_frame_gen(fps)
            _, profile = self.active_profile()
            target = self._auto_target(profile)
            # Also follows lsfg-vk's multiplier changing while the game runs.
            if detected or float(target) != auto.target:
                low, top = self._tdp_bounds(profile)
                auto.retarget(low, top, target)
            auto.smooth_floor = self._smooth_floor(auto.target)
            want = auto.step(fps, now, self.fps.get_low())
            self._remember(auto)
        if want != self._auto_applied:
            with self._hw:
                if self.limits.set_tdp(want):
                    self._auto_applied = want
                    self._fan_check_soon()
                    self._err("power", None)
                else:
                    self._err("power", self.limits.error)

    # ------------------------------------------------------------------
    # periodic
    # ------------------------------------------------------------------

    def _tick(self, now):
        self._auto_step(now)
        try:
            self._playtime_step(now)
        except Exception:
            self._log.exception("Battery playtime")

        power = self.settings["power"]
        if power["enabled"] and now - self._power_applied_at >= REASSERT_S:
            self._power_applied_at = now
            if self.limits.available():
                _, profile = self.active_profile()
                drifted = self.limits.profile() != profile["mode"]
                if not drifted and profile["mode"] == CUSTOM:
                    want = self._auto_applied if self._auto is not None else \
                        self._tdp_bounds(profile)[1]
                    drifted = want is not None and self.limits.tdp() != want
                if drifted:
                    self._log.info("Power settings were changed from outside, re-applying")
                    self._apply_power()

        if now - self._swap_checked >= SWAP_CHECK_S:
            self._swap_checked = now
            # InputPlumber forgets both when it restarts: put them back.
            controls = self.settings["controls"]
            self._apply_steam_pad()       # no-op unless something changed
            if controls["swap_menu"] and self.swap.is_active(controls["swap_layout"]) is False:
                self._apply_swap()

        if now - self._power_source_checked >= POWER_SOURCE_CHECK_S:
            self._power_source_checked = now
            try:
                ac = self._read_on_ac()
            except Exception:
                ac = None
            if ac is not None and ac != self._on_ac:
                self._log.info("Now %s", "on the charger" if ac else "on battery")
                self._on_ac = ac
                self._refresh_fan()
                if self._auto is not None and self._app is not None:
                    known = self._learned(self._auto.target)
                    if known is not None:      # this game's watts on the new power source
                        self._auto._set(known, now)

        if now - self._fan_checked >= FAN_CHECK_S:
            self._fan_checked = now
            self._check_fan(now)

        # Steam sends the same refresh request when it applies its own
        # settings: keep the game's Smooth refresh rate in place.
        if self._smooth_applied and now - self._smooth_sent_at >= SMOOTH_REASSERT_S:
            self._apply_smooth(force=True)
        elif self._smooth_applied:
            self._apply_smooth()   # follows lsfg-vk's multiplier changing mid-game

        # Controllers that (re)appear get their lights and mapping again
        if self._controller_status is not None:
            try:
                seen = bool(self._controller_status())
            except Exception:
                seen = False
            if seen and self._controller_seen is False:
                self._reapply_controller_at = now + RECONNECT_DELAY_S
            self._controller_seen = seen
        if self._reapply_controller_at is not None and now >= self._reapply_controller_at:
            self._reapply_controller_at = None
            self._apply_controller()
        if self._reapply_all_at is not None and now >= self._reapply_all_at:
            self._reapply_all_at = None
            self.apply_all("resume")

    # ------------------------------------------------------------------
    # suspend / resume
    # ------------------------------------------------------------------

    def on_suspend(self):
        conf = self.settings["lighting"]["power_led"]
        self._led_before_sleep = None
        if conf["off_in_sleep"] and self.led.available:
            with self._hw:
                state = self.led.get()
                if state:
                    self._led_before_sleep = True
                    self.led.set(False)
        self.fps.set_app(None)

    def on_resume(self):
        if self._led_before_sleep:
            with self._hw:
                self.led.set(True)
        self._led_before_sleep = None
        # Firmware and controllers need a moment after waking up.
        self._reapply_all_at = time.monotonic() + RESUME_DELAY_S

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def _cached(self, name, fn, ttl=5.0):
        """Slow readings (firmware calls, D-Bus) are refreshed at most every
        `ttl` seconds; ``_invalidate`` forces a fresh one."""
        now = time.monotonic()
        hit = self._slow.get(name)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
        try:
            value = fn()
        except Exception:
            value = None
        self._slow[name] = (now, value)
        return value

    def _invalidate(self, name):
        self._slow.pop(name, None)

    def status(self):
        s = self.settings
        key, profile = self.active_profile()
        rng = self.limits.tdp_range()
        auto = self._auto
        charge = self._cached("charge", self.charge.status) or {}
        return {
            "model": self.product,
            "errors": dict(self.errors),
            "app": {"id": self._app, "name": self._app_name},
            "acpi": self.acpi_installer.status() if self.acpi_installer is not None
            and self.product in LEGION_GO + LEGION_GO_2 + LEGION_GO_S else None,
            "smooth": self._smooth_status(),
            "playtime": self._playtime_status(),
            "steam_controller": dict(zip(("type", "source"), self.steam_controller_for())),
            "power": {
                "profile_key": key,
                "mode": self.limits.profile(),
                "modes": self.limits.profiles(),
                "tdp": self.limits.tdp(),
                "range": list(rng) if rng else None,
                "cpu_boost": self._boost_state(),
                "auto": {
                    "active": auto is not None and s["power"]["enabled"],
                    "state": auto.state if auto is not None else None,
                    "fps": self.fps.get() if auto is not None else None,
                    "low": self.fps.get_low() if auto is not None else None,
                    "target": self._auto_target(profile) if auto is not None else None,
                    "frame_gen": self._frame_gen,
                    "learned": self._learned(auto.target) if auto is not None else None,
                    "probe_error": self.fps.error,
                },
            },
            "fan": dict(self._sensors(), restores=self._fan_restores,
                        profile_key=self.active_fan_profile()[0], on_ac=self.on_ac(),
                        restored_ago=(round(time.monotonic() - self._fan_restored_at)
                                      if self._fan_restored_at is not None else None)),
            "battery": {
                "info": self._battery_info(),
                "charge_limit": charge.get("enabled"),
                "backend": charge.get("backend"),
            },
            "power_led": self._cached("led", self.led.get) if self.led.available else None,
            "swap_menu": {"active": bool(self._cached(
                "swap", lambda: self.swap.is_active(s["controls"]["swap_layout"])))
                          if s["controls"]["swap_menu"] else False},
        }
