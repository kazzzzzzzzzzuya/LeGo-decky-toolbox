"""Sleep guard: how much battery each sleep costs, and an optional power-off
after a number of hours asleep.

Sleeps are noticed by the gap between CLOCK_BOOTTIME (counts suspend) and
CLOCK_MONOTONIC (does not), so they are measured even when Steam's suspend
notice never reaches the plugin. The battery level is read some seconds after
waking, when the firmware has updated it.

Power-off: before the device sleeps, the RTC wake alarm is set to the chosen
number of hours. If the device is still asleep then, it wakes, sees that it
slept that long and shuts down. Waking it earlier clears the alarm. Nothing
about hibernation, swap or the boot configuration is touched.
"""

import json
import os
import time

from . import sysio

WAKEALARM = "/sys/class/rtc/rtc0/wakealarm"
MIN_SLEEP_S = 60.0           # shorter gaps are not counted
SETTLE_S = 8.0               # battery level is read this long after waking
HISTORY = 20
ALARM_MARGIN_S = 600.0       # the sleep must have lasted the hours minus this
HOURS_CHOICES = (1, 2, 3, 4, 6, 8, 12, 24)


def _boottime():
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def drain_per_hour(entry):
    """Percent per hour of one sleep, or None for short or charging sleeps."""
    h = entry.get("hours") or 0
    a, b = entry.get("pct_before"), entry.get("pct_after")
    if h < 0.25 or a is None or b is None or b > a:
        return None
    return round((a - b) / h, 2)


def summary(history):
    rates = [r for r in (drain_per_hour(e) for e in history) if r is not None]
    return {"average_ph": round(sum(rates) / len(rates), 2) if rates else None,
            "counted": len(rates)}


class SleepGuard(object):
    def __init__(self, state_path, battery, poweroff=None, logger=None,
                 wakealarm=WAKEALARM, wall=time.time, mono=time.monotonic, boot=_boottime):
        self.state_path = state_path
        self.battery = battery              # () -> {"percent", "status"} or None
        self.log = logger
        self.wakealarm = wakealarm
        self._poweroff = poweroff or (lambda: sysio.run(["systemctl", "poweroff"], timeout=15))
        self._wall, self._mono, self._boot = wall, mono, boot
        self._gap = None                     # boottime - monotonic at the last tick
        self._last_pct = None
        self._last_ac = None
        self._pending = None                 # a sleep waiting for its battery level
        self.history = self._load()
        self.alarm_at = None

    def _load(self):
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            return [e for e in data.get("history", []) if isinstance(e, dict)][-HISTORY:]
        except (OSError, ValueError, AttributeError):
            return []

    def _save(self):
        try:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"history": self.history[-HISTORY:]}, f)
            os.replace(tmp, self.state_path)
        except OSError:
            pass

    def available(self):
        return os.path.exists(self.wakealarm)

    # -- alarm -----------------------------------------------------------------
    def _write_alarm(self, value):
        err = sysio.write_text(self.wakealarm, "0")
        if value and not err:
            err = sysio.write_text(self.wakealarm, str(int(value)))
        return err

    def before_sleep(self, conf):
        """Steam is about to suspend: arm the power-off alarm if wanted."""
        self.alarm_at = None
        if not conf.get("poweroff") or not self.available():
            return
        info = self.battery() or {}
        if conf.get("battery_only", True) and info.get("status") not in ("Discharging", None, ""):
            self._write_alarm(None)
            return
        at = self._wall() + float(conf.get("hours", 6)) * 3600.0
        if self._write_alarm(at) is None:
            self.alarm_at = at

    # -- the loop --------------------------------------------------------------
    def tick(self, conf):
        """Returns "poweroff" when the device just woke from the alarm."""
        gap = self._boot() - self._mono()
        slept = 0.0 if self._gap is None else gap - self._gap
        self._gap = gap
        info = self.battery() or {}
        now = self._wall()

        if slept >= MIN_SLEEP_S:
            alarm = self.alarm_at
            self.alarm_at = None
            self._pending = {"end": now, "start": now - slept, "hours": round(slept / 3600.0, 3),
                             "pct_before": self._last_pct, "ac": self._last_ac,
                             "settle_at": self._mono() + SETTLE_S}
            if (alarm is not None and conf.get("poweroff") and now >= alarm - 120
                    and slept >= float(conf.get("hours", 6)) * 3600.0 - ALARM_MARGIN_S):
                self._pending["powered_off"] = True
                self._finish(info)
                if self.log:
                    self.log.info("Slept %.1f h: powering off as set", slept / 3600.0)
                self._poweroff()
                return "poweroff"
            if alarm is not None:
                self._write_alarm(None)      # woken earlier: no alarm later

        if self._pending is not None and self._mono() >= self._pending["settle_at"]:
            self._finish(info)

        if info.get("percent") is not None and self._pending is None:
            self._last_pct = info["percent"]
            self._last_ac = info.get("status") not in ("Discharging",)
        return None

    def _finish(self, info):
        e = self._pending
        self._pending = None
        if e is None:
            return
        e.pop("settle_at", None)
        e["pct_after"] = info.get("percent")
        e["drain_ph"] = drain_per_hour(e)
        self.history = (self.history + [e])[-HISTORY:]
        self._save()

    def clear(self):
        self.history = []
        self._save()

    def status(self):
        last = self.history[-1] if self.history else None
        return {"available": self.available(), "alarm_at": self.alarm_at, "last": last,
                "history": list(reversed(self.history[-8:])), **summary(self.history)}
