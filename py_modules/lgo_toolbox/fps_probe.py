#!/usr/bin/env python3
"""Measure a game's real frame rate by asking gamescope.

gamescope (the SteamOS compositor) has a small Wayland interface,
``gamescope_control``. Its ``request_app_performance_stats`` request is
answered with the frame time of the next frame the given app presents -
the same number the performance overlay shows. Asking again after every
answer yields every frame.

This file is both a module and a stand-alone program. The plugin starts it
with the system Python as a separate process:

    python3 fps_probe.py <appid>

It then prints one line every half second: ``<fps> <frames>``. Running it
in its own process keeps the measurement accurate while the plugin's
interpreter is busy, and it needs nothing but the standard library.
"""

import glob
import os
import re
import stat
import socket
import struct
import sys
import time

WINDOW_S = 0.5
MIN_VERSION = 6

_DISPLAY = 1
_REGISTRY = 2
_SYNC = 3
_CONTROL = 4

_REQ_REFRESH = 1       # gamescope_control.set_app_target_refresh_cycle
_REQ_PERF = 6          # gamescope_control.request_app_performance_stats
_EVT_DISPLAY = 1       # gamescope_control.active_display_info

# set_app_target_refresh_cycle flags
FLAG_INTERNAL = 0x1
FLAG_ALLOW_REFRESH_SWITCHING = 0x2
FLAG_ONLY_CHANGE_REFRESH_RATE = 0x4
DISPLAY_INTERNAL = 0x1
DISPLAY_VRR = 0x4
_EVT_PERF = 3          # gamescope_control.app_performance_stats


class ProbeError(Exception):
    pass


def find_sockets(root="/run/user"):
    """gamescope's Wayland sockets, newest first."""
    # Only the Wayland sockets themselves: gamescope-0, gamescope-1, ...
    # Not gamescope-0.lock, nor gamescope-0-ei (its input-emulation socket,
    # which does not speak Wayland).
    paths = []
    for p in glob.glob(os.path.join(root, "*", "gamescope-*")):
        if not re.fullmatch(r"gamescope-\d+", os.path.basename(p)):
            continue
        try:
            if stat.S_ISSOCK(os.stat(p).st_mode):
                paths.append(p)
        except OSError:
            continue

    def mtime(p):
        try:
            return os.stat(p).st_mtime
        except OSError:
            return 0

    return sorted(paths, key=mtime, reverse=True)


def _msg(obj, opcode, payload=b""):
    return struct.pack("<IHH", obj, opcode, 8 + len(payload)) + payload


def _string(text):
    raw = text.encode() + b"\0"
    return struct.pack("<I", len(raw)) + raw + b"\0" * (-len(raw) % 4)


def _read_string(data, offset):
    (length,) = struct.unpack_from("<I", data, offset)
    text = data[offset + 4: offset + 4 + max(0, length - 1)].decode("utf-8", "replace")
    return text, offset + 4 + ((length + 3) & ~3)


class Connection(object):
    """Just enough of the Wayland wire protocol to use gamescope_control."""

    def __init__(self, path, timeout=2.0):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._buf = b""
        self._next_id = _CONTROL + 1
        try:
            self.sock.settimeout(timeout)
            self.sock.connect(path)
            self._bind_control(timeout)
        except Exception:
            self.close()
            raise

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _send(self, data):
        self.sock.sendall(data)

    def _recv(self, timeout):
        """Returns complete messages as (object, opcode, payload)."""
        self.sock.settimeout(max(timeout, 0.001))
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return []
        except InterruptedError:
            return []
        if not chunk:
            raise ProbeError("gamescope closed the connection")
        self._buf += chunk
        out = []
        while len(self._buf) >= 8:
            obj, opcode, size = struct.unpack_from("<IHH", self._buf)
            if size < 8:
                raise ProbeError("malformed message")
            if len(self._buf) < size:
                break
            out.append((obj, opcode, self._buf[8:size]))
            self._buf = self._buf[size:]
        return out

    def _bind_control(self, timeout):
        # wl_display.get_registry(new id), then wl_display.sync(new id)
        self._send(_msg(_DISPLAY, 1, struct.pack("<I", _REGISTRY))
                   + _msg(_DISPLAY, 0, struct.pack("<I", _SYNC)))
        name = version = None
        deadline = time.monotonic() + timeout
        done = False
        while not done:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ProbeError("gamescope did not answer")
            for obj, opcode, payload in self._recv(left):
                if obj == _REGISTRY and opcode == 0:      # wl_registry.global
                    (gname,) = struct.unpack_from("<I", payload)
                    iface, off = _read_string(payload, 4)
                    (gver,) = struct.unpack_from("<I", payload, off)
                    if iface == "gamescope_control":
                        name, version = gname, gver
                elif obj == _SYNC and opcode == 0:        # wl_callback.done
                    done = True
                elif obj == _DISPLAY and opcode == 0:     # wl_display.error
                    raise ProbeError("gamescope reported a protocol error")
        if name is None:
            raise ProbeError("this gamescope has no control interface")
        if version < MIN_VERSION:
            raise ProbeError("this gamescope is too old to report frame times")
        # wl_registry.bind(name, interface, version, new id)
        self._send(_msg(_REGISTRY, 0, struct.pack("<I", name)
                        + _string("gamescope_control")
                        + struct.pack("<II", min(version, 7), _CONTROL)))

    def request(self, app_id):
        self._send(_msg(_CONTROL, _REQ_PERF, struct.pack("<I", app_id)))

    def roundtrip(self, timeout=2.0):
        """Wait until gamescope has handled everything sent so far.
        Returns the control events that arrived meanwhile."""
        # New object ids must count up per connection (Wayland rule).
        cb = self._next_id
        self._next_id += 1
        self._send(_msg(_DISPLAY, 0, struct.pack("<I", cb)))
        events = []
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ProbeError("gamescope did not answer")
            for obj, opcode, payload in self._recv(left):
                if obj == cb and opcode == 0:
                    return events
                if obj == _CONTROL:
                    events.append((opcode, payload))
                elif obj == _DISPLAY and opcode == 0:
                    raise ProbeError("gamescope reported a protocol error")

    def display_info(self):
        """Active display: dict(name, internal, vrr, rates) or None.
        gamescope sends it right after the interface is bound."""
        info = None
        for opcode, payload in self.roundtrip():
            if opcode != _EVT_DISPLAY:
                continue
            name, off = _read_string(payload, 0)
            _, off = _read_string(payload, off)          # make
            _, off = _read_string(payload, off)          # model
            (flags,) = struct.unpack_from("<I", payload, off)
            (size,) = struct.unpack_from("<I", payload, off + 4)
            raw = payload[off + 8: off + 8 + size]
            rates = sorted({r for (r,) in struct.iter_unpack("<I", raw[: size - size % 4]) if r})
            info = {"name": name, "internal": bool(flags & DISPLAY_INTERNAL),
                    "vrr": bool(flags & DISPLAY_VRR), "rates": rates}
        return info

    def set_refresh_cycle(self, fps, internal=True):
        """Switch the screen to the highest refresh rate that is a multiple
        of `fps`, without gamescope's own frame limiter (0 clears)."""
        flags = FLAG_ALLOW_REFRESH_SWITCHING | FLAG_ONLY_CHANGE_REFRESH_RATE
        if internal:
            flags |= FLAG_INTERNAL
        self._send(_msg(_CONTROL, _REQ_REFRESH, struct.pack("<II", int(fps), flags)))
        self.roundtrip()

    def frames(self, timeout):
        """Frame times (seconds) of perf answers that arrived."""
        out = []
        for obj, opcode, payload in self._recv(timeout):
            if obj == _CONTROL and opcode == _EVT_PERF and len(payload) >= 12:
                app, lo, hi = struct.unpack_from("<III", payload)
                out.append((app, ((hi << 32) | lo) / 1e9))
            elif obj == _DISPLAY and opcode == 0:
                raise ProbeError("gamescope reported a protocol error")
        return out


ROTATE_S = 3.0   # no frame from one gamescope for this long: try the next one


def candidate_ids(app_id):
    """App ids gamescope may label the game's frames with.

    Steam's id first. A 64-bit game id (non-Steam shortcuts) carries the
    32-bit app id in its upper half. gamescope reports windows that carry
    no app id at all as 0.
    """
    out = []
    for c in (app_id & 0xFFFFFFFF, app_id >> 32 if app_id > 0xFFFFFFFF else None, 0):
        if c is not None and c not in out:
            out.append(c)
    return out


def measure(app_id, emit, stopped, socket_paths=None, window=WINDOW_S,
            clock=time.monotonic, note=None):
    """Follow one app until ``stopped()``; calls ``emit(fps, frames, low)``
    once per window (fps is None while no frame arrived).

    There can be more than one gamescope - streaming hosts such as
    Punktfunk run their own headless one next to SteamOS's. The game draws
    on only one of them, so a gamescope that sends no frames for the app is
    left for the next one. ``note(text)`` receives why nothing is measured.
    """
    note = note or (lambda text: None)
    turn = 0
    while not stopped():
        paths = socket_paths() if socket_paths else find_sockets()
        if not paths:
            note("gamescope is not running (frame rates are measured in Gaming Mode only)")
            emit(None, 0, None)
            _sleep(1.0, stopped)
            continue
        path = paths[turn % len(paths)]
        turn += 1
        try:
            conn = Connection(path)
        except (OSError, ProbeError) as e:
            note("%s: %s" % (os.path.basename(path), e))
            emit(None, 0, None)
            _sleep(0.5 if len(paths) > 1 else 1.0, stopped)
            continue
        try:
            ids = candidate_ids(app_id)
            locked = None
            for i in ids:
                conn.request(i)
            frames = 0
            total = 0.0
            worst = 0.0
            last_frame = clock()
            window_end = clock() + window
            while not stopped():
                for app, seconds in conn.frames(max(0.0, window_end - clock())):
                    if app not in ids:
                        continue
                    # One answer per request: ask for the next frame now.
                    conn.request(app)
                    if locked is None or (app != 0 and locked == 0):
                        locked = app     # prefer a real id over 0
                    if app != locked:
                        continue
                    last_frame = clock()
                    if 0.0 < seconds < 1.0:
                        frames += 1
                        total += seconds
                        worst = max(worst, seconds)
                if clock() >= window_end:
                    emit(frames / total if frames and total > 0 else None, frames,
                         1.0 / worst if frames and worst > 0 else None)
                    frames = 0
                    total = 0.0
                    worst = 0.0
                    window_end = clock() + window
                if clock() - last_frame >= ROTATE_S:
                    note("gamescope reports no frames for the game (ids %s) on %s%s" % (
                        "/".join(str(i) for i in ids), os.path.basename(path),
                        "; trying the next gamescope" if len(paths) > 1 else ""))
                    if len(paths) > 1:
                        break
                    last_frame = clock()
        except (OSError, ProbeError) as e:
            note("%s: %s" % (os.path.basename(path), e))
            emit(None, 0, None)
            _sleep(0.5, stopped)
        finally:
            conn.close()


def _sleep(seconds, stopped):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not stopped():
        time.sleep(0.05)


def main(argv):
    if len(argv) != 2 or not argv[1].isdigit():
        sys.stderr.write("usage: fps_probe.py <appid>\n")
        return 2
    app_id = int(argv[1])
    parent = os.getppid()

    def emit(fps, frames, low=None):
        sys.stdout.write("%s %d %s\n" % ("-" if fps is None else "%.2f" % fps, frames,
                                         "-" if low is None else "%.2f" % low))
        sys.stdout.flush()

    def stopped():
        # Stop when the plugin that started us is gone
        return os.getppid() != parent

    def note(text):
        sys.stdout.write("! %s\n" % text.replace("\n", " "))
        sys.stdout.flush()

    try:
        measure(app_id, emit, stopped, note=note)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
