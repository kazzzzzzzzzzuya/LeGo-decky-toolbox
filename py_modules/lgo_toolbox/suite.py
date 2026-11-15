"""Read what the Frame Suite plugin set up for a game.

Frame Suite (decky-lsfg-vk, Decky-Framegen and HelixSR Manager in one plugin)
writes ``~/.config/frame-suite/bridge.json`` whenever it changes a game::

    {"version": 1,
     "games": {"1091500": {
         "route": "optiscaler",
         "frame_generation": {"source": "optiscaler", "multiplier": 2, "in_game": true},
         "optiscaler": {"patched": true}}}}

Smooth mode needs two things from it that it cannot see itself: that
OptiScaler is in the game (Frame Suite patches games directly, without
Decky-Framegen's ``fgmod`` wrapper in the launch options), and whether the
game's own frame generation is switched on, which Frame Suite's user tells it.
lsfg-vk's multiplier is still read from lsfg-vk's own settings (``lsfg.py``).

Only reads; never writes Frame Suite's file. The file belongs to the user and
this plugin runs as root: links are not followed, the size is limited and
every value is checked.
"""

import json
import os
import stat
import time

from .lsfg import MAX_BYTES, homes

BRIDGE = os.path.join(".config", "frame-suite", "bridge.json")
VERSION = 1
MAX_MULT = 4          # what Smooth mode's own list offers


def _read(path):
    """The file's text, or None. Opened without following a link at the end."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            return None
        with os.fdopen(os.dup(fd), "r", encoding="utf-8") as f:
            return f.read(MAX_BYTES + 1)
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)


class Suite(object):
    """Frame Suite's record for a game, re-read only when its file changes."""

    RECHECK_S = 2.0

    def __init__(self, homes_fn=homes, clock=time.monotonic):
        self._homes = homes_fn
        self._clock = clock
        self._cache = None      # (path, (mtime_ns, size), games, error)
        self._last = None       # (app_id, checked_at, result)

    def _path(self):
        for h in self._homes():
            p = os.path.join(h, BRIDGE)
            if os.path.isfile(p) and not os.path.islink(p):
                return p
        return None

    def _games(self):
        path = self._path()
        if not path:
            self._cache = None
            return None, None
        try:
            st = os.stat(path)
        except OSError:
            self._cache = None
            return None, None
        key = (st.st_mtime_ns, st.st_size)
        hit = self._cache
        if hit and hit[0] == path and hit[1] == key:
            return hit[2], hit[3]
        games, err = None, None
        try:
            text = _read(path)
            data = json.loads(text) if text else None
            if not isinstance(data, dict):
                err = "bridge.json: not readable"
            elif data.get("version") != VERSION:
                err = "bridge.json: version %r is not known to this plugin" % (data.get("version"),)
            elif isinstance(data.get("games"), dict):
                games = data["games"]
            else:
                games = {}
        except (ValueError, RecursionError) as e:  # malformed file: report, never crash
            err = "bridge.json: %s" % e
        self._cache = (path, key, games, err)
        return games, err

    def for_app(self, app_id):
        """{"present", "optiscaler", "multiplier", "route", "error"} for a game.

        present     Frame Suite's file exists
        optiscaler  OptiScaler is in the game's files
        multiplier  frames on screen per game frame, made inside the game by
                    OptiScaler (1 when off, unknown, or lsfg-vk does it)
        Looked up at most every RECHECK_S per game (it is asked every second).
        """
        now = self._clock()
        last = self._last
        if last and last[0] == app_id and now - last[1] < self.RECHECK_S:
            return dict(last[2])
        out = self._lookup(app_id)
        self._last = (app_id, now, out)
        return dict(out)

    def _lookup(self, app_id):
        out = {"present": False, "optiscaler": False, "multiplier": 1, "route": None, "error": None}
        if app_id is None:
            return out
        games, err = self._games()
        out["present"] = games is not None or err is not None
        out["error"] = err
        try:
            game = (games or {}).get(str(int(app_id)))
        except (TypeError, ValueError):
            game = None
        if not isinstance(game, dict):
            return out
        route = game.get("route")
        out["route"] = route if route in ("optiscaler", "lsfg") else None
        opti = game.get("optiscaler")
        out["optiscaler"] = isinstance(opti, dict) and opti.get("patched") is True
        fg = game.get("frame_generation")
        if out["optiscaler"] and isinstance(fg, dict) and fg.get("source") == "optiscaler" \
                and fg.get("in_game") is True:
            mult = fg.get("multiplier")
            if isinstance(mult, int) and not isinstance(mult, bool) and 1 < mult <= MAX_MULT:
                out["multiplier"] = mult
        return out
