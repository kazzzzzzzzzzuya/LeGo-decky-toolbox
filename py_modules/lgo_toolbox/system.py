"""The System tab: Speaker EQ, Sleep guard, the Steam update check and Cloud
saves, with their own settings file (system.json) and one background thread."""

import collections
import copy
import json
import os
import threading
import time

from . import speaker_eq, sleep_guard
from .battery import battery_info
from .cloud_saves import CloudSaves
from .steam_check import SteamCheck
from .useros import User, write_atomic

MODES = ("battery", "balanced", "smooth")   # Longest battery, Balanced, Smoothest
MODE_LEARN_KEEP = 60     # minutes of battery draw averaged per game and mode
TICK_S = 2.0
STEAM_CHECK_S = 60.0
WATTS_EVERY_S = 60.0
FPS_KEPT_S = 30.0         # frame-rate readings kept for "before the menu opened"
FPS_BEFORE = (12.0, 1.5)  # ... averaged from this many seconds before opening up to this many
WATTS_KEPT = 10          # the Power tab's "last 10 min"


def defaults():
    return {
        "eq": {"enabled": False, "preset": "balanced", "bass": 0, "treble": 0},
        "sleep": {"poweroff": False, "hours": 6, "battery_only": True},
        # The Game tab's choice per game: {"<appid>": {"mode": "balanced", "name": "..."}}
        "modes": {},
    }


def sanitize(data):
    out = defaults()
    if not isinstance(data, dict):
        return out
    eq, sl = data.get("eq") or {}, data.get("sleep") or {}
    if isinstance(eq, dict):
        out["eq"]["enabled"] = bool(eq.get("enabled", False))
        if eq.get("preset") in speaker_eq.PRESETS:
            out["eq"]["preset"] = eq["preset"]
        for k in ("bass", "treble"):
            try:
                out["eq"][k] = max(-speaker_eq.TONE_DB, min(speaker_eq.TONE_DB, int(round(float(eq.get(k, 0))))))
            except (TypeError, ValueError):
                pass
    modes = data.get("modes")
    if isinstance(modes, dict):
        for key, v in list(modes.items())[:500]:
            if isinstance(key, str) and key.isdigit() and len(key) <= 10 and isinstance(v, dict) \
                    and v.get("mode") in MODES:
                out["modes"][key] = {"mode": v["mode"], "name": str(v.get("name") or "")[:120]}
    if isinstance(sl, dict):
        out["sleep"]["poweroff"] = bool(sl.get("poweroff", False))
        out["sleep"]["battery_only"] = bool(sl.get("battery_only", True))
        if sl.get("hours") in sleep_guard.HOURS_CHOICES:
            out["sleep"]["hours"] = sl["hours"]
    return out


def _merge(base, patch):
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class System(object):
    def __init__(self, state_dir, logger=None, user=None):
        self.log = logger
        self.state_dir = state_dir
        self.path = os.path.join(state_dir, "system.json")
        self.user = user or User(home=os.environ.get("DECKY_USER_HOME"))
        self._lock = threading.RLock()
        self.settings = self._load()
        self.eq = speaker_eq.SpeakerEq(self.user, os.path.join(state_dir, "speaker-eq.log"), logger)
        self.sleep = sleep_guard.SleepGuard(os.path.join(state_dir, "sleep.json"), battery_info, logger=logger)
        self.steam = SteamCheck(self.user, state_dir, logger)
        self.cloud = CloudSaves(self.user, state_dir, self.steam, logger)
        self._steam_result = None
        self._steam_at = 0.0
        self._stop = threading.Event()
        self._thread = None
        self._watts = collections.deque(maxlen=WATTS_KEPT)
        self._watts_at = None
        self.running_app = lambda: None          # main.py hands in the hub's running game
        self.fps_now = lambda: None              # ... and its frame-rate reading
        self._fps = collections.deque()          # (monotonic time, fps)
        self._menu_open = False
        self._fps_before = None
        self._learn_path = os.path.join(state_dir, "mode-watts.json")
        self._learn = self._load_learn()

    def _load(self):
        try:
            with open(self.path) as f:
                return sanitize(json.load(f))
        except (OSError, ValueError):
            return defaults()

    def get_settings(self):
        with self._lock:
            return copy.deepcopy(self.settings)

    def update(self, patch):
        with self._lock:
            self.settings = sanitize(_merge(self.settings, patch))
            write_atomic(self.path, json.dumps(self.settings, indent=1))
        return self.state()

    def restore(self, data):
        return self.update(sanitize(data))

    # -- thread ----------------------------------------------------------------
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="lgo-system", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        try:
            self.eq.stop()
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            conf = self.get_settings()
            for name, fn in (("eq", lambda: self.eq.tick(conf["eq"])),
                             ("sleep", lambda: self.sleep.tick(conf["sleep"])),
                             ("cloud saves", self.cloud.tick)):
                try:
                    fn()
                except Exception:
                    if self.log:
                        self.log.exception("System %s step failed", name)
            self._sample_watts()
            self._sample_fps()
            if time.monotonic() - self._steam_at >= STEAM_CHECK_S:
                self.steam_check()
            self._stop.wait(TICK_S)

    def _sample_watts(self, now=None):
        """Battery draw once a minute (None while charging) for the Power tab's chart."""
        now = time.monotonic() if now is None else now
        if self._watts_at is not None and now - self._watts_at < WATTS_EVERY_S:
            return
        self._watts_at = now
        try:
            info = battery_info() or {}
        except Exception:
            info = {}
        w = info.get("watts")
        draining = w is not None and info.get("status") == "Discharging"
        self._watts.append(round(w, 1) if draining else None)
        if draining and info.get("minutes") and info.get("percent"):
            # Energy the battery holds when full, worked out from what it says now.
            full = w * info["minutes"] / 60.0 / (info["percent"] / 100.0)
            if 10 <= full <= 200:
                self._learn["full_wh"] = round(full, 1)
        app = self.running_app()
        mode = (self.get_settings()["modes"].get(str(app)) or {}).get("mode") if app is not None else None
        if draining and mode:
            key = "%s:%s" % (app, mode)
            avg, n = self._learn["watts"].get(key) or (w, 0)
            n = min(n + 1, MODE_LEARN_KEEP)
            self._learn["watts"][key] = (round(avg + (w - avg) / n, 2), n)
            write_atomic(self._learn_path, json.dumps(self._learn))

    # -- frame rate before the menu opened ------------------------------------------
    # MAKO (and the Steam overlay) slow a game down while the Quick Access menu is open, so the
    # Game tab shows the frame rate from just before it opened.
    def _sample_fps(self, now=None):
        now = time.monotonic() if now is None else now
        if self._menu_open:
            return
        try:
            fps = self.fps_now()
        except Exception:
            fps = None
        if fps:
            self._fps.append((now, float(fps)))
        while self._fps and now - self._fps[0][0] > FPS_KEPT_S:
            self._fps.popleft()

    def set_menu(self, open_, now=None):
        """The plugin's panel opened or closed."""
        now = time.monotonic() if now is None else now
        if open_ and not self._menu_open:
            lo, hi = now - FPS_BEFORE[0], now - FPS_BEFORE[1]
            vals = [f for t, f in self._fps if lo <= t <= hi]
            self._fps_before = round(sum(vals) / len(vals)) if vals else None
        elif not open_:
            self._fps_before = None
            self._fps.clear()           # what follows the menu is not "before" anything
        self._menu_open = bool(open_)

    def fps_before_menu(self):
        return self._fps_before if self._menu_open else None

    def _load_learn(self):
        try:
            with open(self._learn_path) as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("watts"), dict):
                data["watts"] = {k: tuple(v) for k, v in data["watts"].items()
                                 if isinstance(v, (list, tuple)) and len(v) == 2}
                return data
        except (OSError, ValueError, TypeError):
            pass
        return {"watts": {}, "full_wh": None}

    # -- modes -------------------------------------------------------------------
    def set_mode(self, app_id, name, mode):
        """Remember the Game tab's choice for a game (None forgets it)."""
        key = str(int(app_id))
        with self._lock:
            modes = dict(self.settings["modes"])
            if mode in MODES:
                modes[key] = {"mode": mode, "name": str(name or "")[:120]}
            else:
                modes.pop(key, None)
            self.settings["modes"] = modes
            write_atomic(self.path, json.dumps(self.settings, indent=1))
        return self.mode_info(app_id)

    def mode_info(self, app_id):
        """The game's mode and, per mode, the hours a full battery would last
        (learned from the battery draw while the game ran in that mode)."""
        if app_id is None:
            return {"mode": None, "hours": {}}
        key = str(int(app_id))
        full = self._learn.get("full_wh")
        try:
            pct = (battery_info() or {}).get("percent")
        except Exception:
            pct = None
        hours = {}
        for m in MODES:
            avg, n = self._learn["watts"].get("%s:%s" % (key, m)) or (None, 0)
            hours[m] = round(full * pct / 100.0 / avg, 2) if (full and pct and avg and n >= 3) else None
        return {"mode": (self.get_settings()["modes"].get(key) or {}).get("mode"), "hours": hours}

    def boost_requests(self):
        """Games set to Smoothest: Frame Suite is asked to boost them ({appid: name})."""
        return {k: v["name"] for k, v in self.get_settings()["modes"].items()
                if v["mode"] == "smooth" and int(k) < 0x80000000}

    def watts_history(self):
        return list(self._watts)

    # -- calls -------------------------------------------------------------------
    def before_sleep(self):
        try:
            self.sleep.before_sleep(self.get_settings()["sleep"])
        except Exception:
            if self.log:
                self.log.exception("Sleep alarm failed")

    def steam_check(self):
        try:
            self._steam_result = self.steam.check()
        except Exception as e:
            if self.log:
                self.log.exception("Steam check failed")
            self._steam_result = {"overall": "fail", "items": [], "error": str(e)}
        self._steam_at = time.monotonic()
        return self._steam_result

    def eq_capability(self):
        ok, reason = self.eq.capability()
        return {"available": ok, "reason": reason}

    def state(self):
        return {
            "settings": self.get_settings(),
            "eq": dict(self.eq.status(), **self.eq_capability(),
                       presets=[{"id": k, "label": v["label"]} for k, v in speaker_eq.PRESETS.items()]),
            "sleep": dict(self.sleep.status(), hours_choices=list(sleep_guard.HOURS_CHOICES)),
            "steam": self._steam_result,
        }
