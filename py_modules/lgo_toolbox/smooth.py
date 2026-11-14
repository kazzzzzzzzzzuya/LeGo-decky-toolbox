"""Smooth mode: an even frame cap plus the matching screen refresh rate.

* The cap comes from MangoHud's limiter with ``fps_limit_method=early``
  (the Linux counterpart of RTSS's front-edge / async limiter), switched
  on per game through the game's launch options. Games without MangoHud's
  Vulkan layer fall back to DXVK's own limiter (DirectX 9-11 under Proton).
* The refresh rate comes from gamescope: the screen switches to the highest
  rate that is an exact multiple of the cap (60 -> 60 Hz, 72 -> 144 Hz), so
  every frame is shown for the same number of refreshes. gamescope's own
  limiter stays off, so two limiters never stack.
"""

import glob
import json
import os

from . import fps_probe

CANDIDATES = (30, 36, 40, 45, 48, 60, 72, 90, 120, 144)
LAYER_DIRS = ("/usr/share/vulkan/implicit_layer.d", "/etc/vulkan/implicit_layer.d")


def mangohud_env(dirs=LAYER_DIRS):
    """Environment variable that switches MangoHud's Vulkan layer on, or
    None if the layer is not installed."""
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "*.json"))):
            if "mangohud" not in os.path.basename(path).lower():
                continue
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            layers = data.get("layers") or [data.get("layer") or {}]
            for layer in layers:
                env = layer.get("enable_environment") if isinstance(layer, dict) else None
                if isinstance(env, dict) and env:
                    return sorted(env)[0]
    return None


def launch_prefix(fps, env=None, conf=None):
    """Launch-option text that caps a game at `fps` (exact, removable).
    With `conf` MangoHud takes the cap from that file instead, which the
    plugin can change while the game runs (MangoHud reloads it)."""
    fps = int(fps)
    if env and conf and " " not in conf and "'" not in conf and '"' not in conf:
        return "%s=1 MANGOHUD_CONFIGFILE=%s" % (env, conf)
    if env:
        return "%s=1 MANGOHUD_CONFIG=fps_limit=%d,fps_limit_method=early,no_display" % (env, fps)
    return "DXVK_FRAME_RATE=%d" % fps


# ---- live cap file ---------------------------------------------------------
CONF_DIR = os.path.join(".config", "lgo-toolbox", "smooth")
CONF_TEXT = ("# Legion Go Toolbox, Smooth mode. Rewritten by the plugin; MangoHud\n"
             "# applies changes while the game runs.\n"
             "fps_limit=%d\nfps_limit_method=early\nno_display\n")


def conf_path(home, app_id):
    return os.path.join(home, CONF_DIR, "%d.conf" % int(app_id))


def conf_from_prefix(prefix):
    for word in (prefix or "").split():
        if word.startswith("MANGOHUD_CONFIGFILE="):
            return word.partition("=")[2] or None
    return None


def write_conf(path, limit):
    """Write the cap in place (MangoHud watches the file itself, so it is
    not replaced), owned by the user whose home it is in."""
    text = CONF_TEXT % int(limit)
    try:
        with open(path, "r") as f:
            if f.read() == text:
                return True
    except (OSError, IOError):
        pass
    folder = os.path.dirname(path)
    try:
        home_st = None
        parts = folder.split(os.sep)
        for i in range(len(parts), 0, -1):
            base = os.sep.join(parts[:i]) or os.sep
            if os.path.isdir(base):
                home_st = os.stat(base)
                break
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "w") as f:
            f.write(text)
        if home_st is not None and os.geteuid() == 0:
            # The game runs as the user: it must be able to read (and the
            # user to edit) what root wrote.
            p = folder
            while p and p != os.sep and os.stat(p).st_uid != home_st.st_uid:
                os.chown(p, home_st.st_uid, home_st.st_gid)
                p = os.path.dirname(p)
            os.chown(path, home_st.st_uid, home_st.st_gid)
        os.chmod(path, 0o644)
        return True
    except (OSError, IOError):
        return False


# ---- where MangoHud's limiter sits relative to lsfg-vk ------------------------
def loader_dirs(home):
    """Implicit-layer folders in the Vulkan loader's search order. A layer
    found earlier sits closer to the game."""
    sub = os.path.join("vulkan", "implicit_layer.d")
    return [os.path.join(home, ".config", sub), os.path.join("/etc/xdg", sub),
            os.path.join("/etc", sub), os.path.join(home, ".local", "share", sub),
            os.path.join("/usr/local/share", sub), os.path.join("/usr/share", sub)]


def _layer_dir(dirs, word):
    for i, d in enumerate(dirs):
        if any(word in os.path.basename(p).lower() for p in glob.glob(os.path.join(d, "*.json"))):
            return i
    return None


def limit_on_output(home):
    """True when MangoHud's limiter comes after lsfg-vk (it then sees the
    generated frames too, so its cap is the frame rate on screen). This is
    the usual setup: decky-lsfg-vk installs lsfg-vk in the user's folder,
    which the loader searches before the system one with MangoHud. In one
    folder the order is not defined; the plugin then also assumes this and
    corrects itself from the measured frame rate."""
    if not home:
        return True
    dirs = loader_dirs(home)
    mh, lsfg = _layer_dir(dirs, "mangohud"), _layer_dir(dirs, "lsfgvk")
    if mh is None or lsfg is None:
        return True
    return lsfg <= mh


def fps_choices(rates):
    """Caps that divide one of the screen's refresh rates evenly."""
    if not rates:
        return [c for c in CANDIDATES if c in (30, 60)]
    top = max(rates)
    return [c for c in CANDIDATES if c <= top and any(r % c == 0 for r in rates)]


def refresh_for(fps, rates):
    """The refresh rate gamescope will pick for `fps` (None: no match)."""
    for r in sorted(rates or (), reverse=True):
        if r % fps == 0:
            return r
    return None


def screen_rate(fps, rates, vrr=False):
    """The refresh rate Smooth mode puts the screen at for `fps` frames on
    screen: the highest rate `fps` divides; without one (90 or 120 fps on a
    60/144 Hz screen), the highest rate, so frames are held as evenly as the
    screen allows; None with variable refresh (the screen follows the game)
    or when the rates are unknown."""
    exact = refresh_for(fps, rates)
    if exact or vrr or not rates:
        return exact
    return max(rates)


def vrr_cap(rates):
    """Highest frame rate that keeps variable refresh active: a little below
    the screen's top rate (120 Hz: 116, 144 Hz: 138), the usual rule."""
    top = max(rates) if rates else 0
    return int(top - top * top / 3600.0) if top else 0


def refresh_request(fps, rates, vrr=False):
    """What to ask gamescope for. gamescope picks the highest rate that is a
    multiple of the request; a request no rate is a multiple of is left to
    gamescope's own fallback, which may pick a rate below the frame rate and
    hold back frame generation. So ask for a rate the screen has."""
    return screen_rate(fps, rates, vrr) or fps


class Gamescope(object):
    """Short connections to gamescope's control interface."""

    def __init__(self, sockets=fps_probe.find_sockets, connect=fps_probe.Connection):
        self._sockets = sockets
        self._connect = connect
        self.error = None

    def _with(self, fn):
        for path in self._sockets():
            try:
                conn = self._connect(path)
            except (OSError, fps_probe.ProbeError) as e:
                self.error = str(e)
                continue
            try:
                out = fn(conn)
                self.error = None
                return out, True
            except (OSError, fps_probe.ProbeError) as e:
                self.error = str(e)
            finally:
                conn.close()
        if self.error is None:
            self.error = "gamescope is not running (Gaming Mode only)"
        return None, False

    def display(self):
        info, _ = self._with(lambda c: c.display_info())
        return info

    def set_refresh(self, fps, internal=True):
        """Ask every gamescope: with a streaming host running its own
        headless gamescope, the game may be on either."""
        ok = False
        errors = []
        for path in self._sockets():
            try:
                conn = self._connect(path)
            except (OSError, fps_probe.ProbeError) as e:
                errors.append(str(e))
                continue
            try:
                conn.set_refresh_cycle(fps, internal)
                ok = True
            except (OSError, fps_probe.ProbeError) as e:
                errors.append(str(e))
            finally:
                conn.close()
        self.error = None if ok else (
            errors[0] if errors else "gamescope is not running (Gaming Mode only)")
        return ok
