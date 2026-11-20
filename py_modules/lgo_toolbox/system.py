"""The System tab: Speaker EQ, Sleep guard and the Steam update check, with
their own settings file (system.json) and one background thread."""

import collections
import copy
import json
import os
import threading
import time

from . import speaker_eq, sleep_guard
from .battery import battery_info
from .steam_check import SteamCheck
from .useros import User, write_atomic

TICK_S = 2.0
STEAM_CHECK_S = 60.0
WATTS_EVERY_S = 60.0
WATTS_KEPT = 10          # the Power tab's "last 10 min"


def defaults():
    return {
        "eq": {"enabled": False, "preset": "balanced", "bass": 0, "treble": 0},
        "sleep": {"poweroff": False, "hours": 6, "battery_only": True},
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
        self._steam_result = None
        self._steam_at = 0.0
        self._stop = threading.Event()
        self._thread = None
        self._watts = collections.deque(maxlen=WATTS_KEPT)
        self._watts_at = None

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
                             ("sleep", lambda: self.sleep.tick(conf["sleep"]))):
                try:
                    fn()
                except Exception:
                    if self.log:
                        self.log.exception("System %s step failed", name)
            self._sample_watts()
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
        self._watts.append(round(w, 1) if w is not None and info.get("status") == "Discharging" else None)

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
