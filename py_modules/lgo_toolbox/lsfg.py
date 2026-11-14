"""Read lsfg-vk's own settings, so Smooth mode knows a game's frame-generation
multiplier without the user entering it twice.

lsfg-vk 2.x (as set up by decky-lsfg-vk) keeps everything in
``~/.config/lsfg-vk/conf.toml``::

    version = 2
    [[profile]]
    name = "Forza Horizon 4"
    active_in = [ "1293830" ]      # Steam app id (signed for shortcuts)
    multiplier = 2

decky-lsfg-vk's "Base FPS cap" lives next to it in ``workarounds.json``
(``apps.<appid>.state.dxvkFrameRate``) and would be a second limiter next
to Smooth mode's.

Only reads; never writes lsfg-vk's files.
"""

import glob
import json
import os
import re
import time

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

CONF = os.path.join(".config", "lsfg-vk", "conf.toml")
WORKAROUNDS = os.path.join(".config", "lsfg-vk", "workarounds.json")
LAYER_GLOBS = (
    os.path.join(".local", "share", "vulkan", "implicit_layer.d", "VkLayer_LSFGVK*.json"),
)
SYSTEM_LAYER_GLOBS = (
    "/usr/share/vulkan/implicit_layer.d/VkLayer_LSFGVK*.json",
    "/etc/vulkan/implicit_layer.d/VkLayer_LSFGVK*.json",
)
MAX_MULT = 20
MAX_BYTES = 1 << 20


def homes():
    """Home folders to look in: Decky's user first, then everyone in /home."""
    out = []
    first = os.environ.get("DECKY_USER_HOME")
    if first:
        out.append(first)
    for h in sorted(glob.glob("/home/*")):
        if h not in out:
            out.append(h)
    return out


def app_keys(app_id):
    """How lsfg-vk names a game in ``active_in``: the Steam app id, and for
    non-Steam shortcuts also its signed 32-bit form."""
    app = int(app_id)
    keys = [str(app)]
    low = app & 0xFFFFFFFF
    if low >= 0x80000000:
        keys.append(str(low - 0x100000000))
        if low != app:
            keys.append(str(low))
    return keys


# ---- a small reader for the subset of TOML lsfg-vk writes ---------------------
_KEY = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$')
_STR = re.compile(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'')


def _value(text):
    text = text.split(" #")[0].strip()
    if text.startswith("["):
        return [m.group(1) if m.group(1) is not None else m.group(2)
                for m in _STR.finditer(text)]
    m = _STR.fullmatch(text)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def parse_toml(content):
    """``tomllib`` when available; otherwise enough TOML for lsfg-vk's file
    (top-level keys, [tables], [[arrays of tables]], one-line values)."""
    if tomllib is not None:
        return tomllib.loads(content)
    root, cur = {}, None
    cur = root
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[["):
            cur = {}
            root.setdefault(s.strip("[] "), []).append(cur)
        elif s.startswith("["):
            cur = root.setdefault(s.strip("[] "), {})
        else:
            m = _KEY.match(s)
            if m:
                cur[m.group(1)] = _value(m.group(2))
    return root


def _read(path):
    if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > MAX_BYTES:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class Lsfg(object):
    """lsfg-vk's settings for a game, re-read only when its files change."""

    RECHECK_S = 2.0

    def __init__(self, homes_fn=homes, system_layers=SYSTEM_LAYER_GLOBS, clock=time.monotonic):
        self._homes = homes_fn
        self._system_layers = system_layers
        self._clock = clock
        self._cache = {}
        self._last = None   # (app_id, checked_at, result)

    def _home(self):
        for h in self._homes():
            if os.path.isfile(os.path.join(h, CONF)) or any(
                    glob.glob(os.path.join(h, g)) for g in LAYER_GLOBS):
                return h
        return None

    def _cached(self, path, loader):
        try:
            st = os.stat(path)
        except OSError:
            self._cache.pop(path, None)
            return None, None
        key = (st.st_mtime_ns, st.st_size)
        hit = self._cache.get(path)
        if hit and hit[0] == key:
            return hit[1], hit[2]
        try:
            data, err = loader(_read(path)), None
        except Exception as e:  # malformed file: report, never crash
            data, err = None, "%s: %s" % (os.path.basename(path), e)
        self._cache[path] = (key, data, err)
        return data, err

    def installed(self, home=None):
        home = home or self._home()
        pats = list(self._system_layers)
        if home:
            pats += [os.path.join(home, g) for g in LAYER_GLOBS]
        return any(glob.glob(p) for p in pats)

    def for_app(self, app_id):
        """{"installed", "multiplier", "profile", "base_cap", "error"} for a
        game. multiplier is 1 when lsfg-vk has no profile for it. Looked up
        at most every RECHECK_S per game (it is asked every second)."""
        now = self._clock()
        last = self._last
        if last and last[0] == app_id and now - last[1] < self.RECHECK_S:
            return dict(last[2])
        out = self._lookup(app_id)
        self._last = (app_id, now, out)
        return dict(out)

    def _lookup(self, app_id):
        out = {"installed": False, "multiplier": 1, "profile": None,
               "base_cap": 0, "error": None}
        if app_id is None:
            return out
        home = self._home()
        out["installed"] = self.installed(home)
        if not home:
            return out
        keys = app_keys(app_id)
        conf, err = self._cached(os.path.join(home, CONF), lambda t: parse_toml(t or ""))
        if err:
            out["error"] = err
        elif conf:
            version = conf.get("version")
            if version != 2:
                out["error"] = ("lsfg-vk settings version %r: set the multiplier by hand"
                                % (version,))
            else:
                for prof in conf.get("profile") or []:
                    if not isinstance(prof, dict):
                        continue
                    active = prof.get("active_in")
                    active = [active] if isinstance(active, str) else (active or [])
                    if not any(str(a) in keys for a in active):
                        continue
                    mult = prof.get("multiplier", 2)
                    if isinstance(mult, bool) or not isinstance(mult, int) or mult < 1:
                        mult = 1
                    out["multiplier"] = min(mult, MAX_MULT)
                    out["profile"] = str(prof.get("name", ""))[:120]
                    break
        work, _ = self._cached(os.path.join(home, WORKAROUNDS),
                               lambda t: json.loads(t) if t else None)
        if isinstance(work, dict) and isinstance(work.get("apps"), dict):
            for k in keys:
                state = (work["apps"].get(k) or {}).get("state") if isinstance(
                    work["apps"].get(k), dict) else None
                cap = state.get("dxvkFrameRate") if isinstance(state, dict) else None
                if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0:
                    out["base_cap"] = cap
                    break
        if not out["installed"] and out["profile"] is not None:
            out["multiplier"] = 1  # a profile without the layer generates nothing
        return out
