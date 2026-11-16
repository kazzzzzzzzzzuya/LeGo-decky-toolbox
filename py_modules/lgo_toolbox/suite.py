"""Read what the Frame Suite plugin set up for a game.

Frame Suite (decky-lsfg-vk, Decky-Framegen and HelixSR Manager in one plugin)
writes ``~/.config/frame-suite/bridge.json`` whenever it changes a game::

    {"version": 1,
     "games": {"1091500": {
         "route": "optiscaler",
         "frame_generation": {"source": "optiscaler", "multiplier": 2, "in_game": true},
         "optiscaler": {"patched": true}}}}

It also mirrors MAKO's per-game settings (Frame Suite bundles MAKO) under
"mako": with MAKO's adaptive frame generation the screen holds "target_fps"
and MAKO generates up to "max_multiplier" times the game's frames.

Smooth mode needs two things from it that it cannot see itself: that
OptiScaler is in the game (Frame Suite patches games directly, without
Decky-Framegen's ``fgmod`` wrapper in the launch options), and whether the
game's own frame generation is switched on, which Frame Suite's user tells it.
lsfg-vk's multiplier is still read from lsfg-vk's own settings (``lsfg.py``).

Battery playtime asks Frame Suite for frame generation through a file of
its own, ``~/.config/lgo-toolbox/framegen.json`` (see ``write_requests``):
"standby" has Frame Suite give a game an lsfg-vk profile at 1x (off), which
lsfg-vk only picks up when the game starts; "multiplier" then switches it on
while the game runs. Frame Suite reports back in its own file, per game under
"toolbox", and whether it may do this at all under "lsfg_ready".

Never writes Frame Suite's file. Both files belong to the user and this
plugin runs as root: links are not followed, the size is limited and every
value is checked.
"""

import json
import os
import stat
import tempfile
import time

from .lsfg import MAX_BYTES, homes

BRIDGE = os.path.join(".config", "frame-suite", "bridge.json")
REQUESTS = os.path.join(".config", "lgo-toolbox", "framegen.json")
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
        self._cache = None      # (path, (mtime_ns, size), games, error, top)
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
        games, err, top = None, None, {}
        try:
            text = _read(path)
            data = json.loads(text) if text else None
            if not isinstance(data, dict):
                err = "bridge.json: not readable"
            elif data.get("version") != VERSION:
                err = "bridge.json: version %r is not known to this plugin" % (data.get("version"),)
            else:
                games = data["games"] if isinstance(data.get("games"), dict) else {}
                top = {"lsfg_ready": data.get("lsfg_ready") is True,
                       "toolbox_fg": data.get("toolbox_fg") is True}
        except (ValueError, RecursionError) as e:  # malformed file: report, never crash
            err = "bridge.json: %s" % e
        self._cache = (path, key, games, err, top)
        return games, err

    def home(self):
        """The home folder Frame Suite writes to (else Decky's user's)."""
        path = self._path()
        if path:
            return path[:-len(BRIDGE) - 1]
        homes = self._homes()
        return homes[0] if homes else None

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
        out = {"present": False, "optiscaler": False, "multiplier": 1, "route": None, "error": None,
               "lsfg_ready": False, "standby_since": None, "fg_applied": None, "fg_refused": None,
               "mako": None}
        if app_id is None:
            return out
        games, err = self._games()
        out["present"] = games is not None or err is not None
        out["error"] = err
        top = self._cache[4] if self._cache else {}
        out["lsfg_ready"] = bool(top.get("lsfg_ready") and top.get("toolbox_fg"))
        try:
            game = (games or {}).get(str(int(app_id)))
        except (TypeError, ValueError):
            game = None
        if not isinstance(game, dict):
            return out
        route = game.get("route")
        out["route"] = route if route in ("optiscaler", "lsfg", "mako") else None
        out["mako"] = _mako(game.get("mako"))
        opti = game.get("optiscaler")
        out["optiscaler"] = isinstance(opti, dict) and opti.get("patched") is True
        fg = game.get("frame_generation")
        if out["optiscaler"] and isinstance(fg, dict) and fg.get("source") == "optiscaler" \
                and fg.get("in_game") is True:
            mult = fg.get("multiplier")
            if _int(mult) and 1 < mult <= MAX_MULT:
                out["multiplier"] = mult
        tb = game.get("toolbox")
        if isinstance(tb, dict):
            since = tb.get("since")
            if tb.get("standby") is True and isinstance(since, (int, float)) and \
                    not isinstance(since, bool) and 0 <= since < 4e9:
                out["standby_since"] = float(since)
            if _int(tb.get("multiplier")) and 1 < tb["multiplier"] <= MAX_MULT:
                out["fg_applied"] = tb["multiplier"]
            if isinstance(tb.get("refused"), str):
                out["fg_refused"] = tb["refused"][:200]
        return out


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _mako(m):
    """MAKO's frame generation for a game (from Frame Suite, which bundles MAKO), checked:
    {"enabled", "adaptive", "target_fps", "max_multiplier", "multiplier"} or None."""
    if not isinstance(m, dict) or m.get("enabled") is not True:
        return None
    adaptive = m.get("adaptive") is True
    target, top, mult = m.get("target_fps"), m.get("max_multiplier"), m.get("multiplier")
    if adaptive:
        if not (_int(target) and 15 <= target <= 360 and _int(top) and 1 <= top <= 8):
            return None
        return {"enabled": True, "adaptive": True, "target_fps": target, "max_multiplier": top,
                "multiplier": top}
    if not (_int(mult) and 1 <= mult <= 8):
        return None
    return {"enabled": True, "adaptive": False, "target_fps": 0, "max_multiplier": mult, "multiplier": mult}


def write_requests(home, games, clock=time.time):
    """Ask Frame Suite for frame generation: {appid: {"standby": bool,
    "multiplier": int or None}}. An empty dict removes the file. Written
    atomically, owned by the home's owner, only inside that home. Returns
    None or an error text."""
    if not home:
        return None if not games else "no home folder"
    path = os.path.join(home, REQUESTS)
    folder = os.path.dirname(path)
    try:
        real_home = os.path.realpath(home)
        for p in (os.path.dirname(folder), folder):
            if os.path.islink(p):
                return "%s is a link" % p
        if os.path.isdir(folder) and not os.path.realpath(folder).startswith(real_home + os.sep):
            return "%s is outside the home folder" % folder
        if not games:
            if os.path.lexists(path) and not os.path.isdir(path):
                os.unlink(path)
            return None
        home_st = os.stat(home)
        for p in (os.path.dirname(folder), folder):
            if not os.path.isdir(p):
                os.mkdir(p, 0o755)
                if os.geteuid() == 0:
                    os.chown(p, home_st.st_uid, home_st.st_gid)
        data = {"version": VERSION, "updated": int(clock()),
                "games": {str(k): {"standby": bool(v.get("standby")),
                                   "multiplier": v.get("multiplier") if _int(v.get("multiplier")) else None}
                          for k, v in sorted(games.items())}}
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".framegen-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=1, sort_keys=True)
            os.chmod(tmp, 0o644)
            if os.geteuid() == 0:
                os.chown(tmp, home_st.st_uid, home_st.st_gid)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return None
    except OSError as e:
        return "could not write %s: %s" % (path, e.strerror or e)
