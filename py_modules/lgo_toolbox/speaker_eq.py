"""Speaker EQ: a PipeWire filter-chain sink in front of the built-in speakers.

SteamOS plays the Legion Go's speakers without the sound processing Windows
gives them. This runs a separate PipeWire client (``pipewire -c <conf>``, as
the user) that adds a sink "Legion Go Speakers (EQ)" feeding the speaker
sink. Nothing is written to the user's PipeWire configuration: the conf file
lives in /run/user/<uid>, and stopping the process removes the sink.

While the speakers are what plays, the EQ sink is the default output. When
headphones or a Bluetooth / USB output take over, the default goes back to
that output (or to the bare speaker sink when its port switched to the
headphone jack), so the EQ is never applied to anything but the speakers.

Steam's volume controls the default sink. The EQ sink's volume is the one the
user hears, so the speaker sink is held at 100 % while the EQ plays and gets
the user's volume back whenever the default returns to it.
"""

import json
import os
import signal
import time

EQ_NODE = "lgo_speaker_eq"
EQ_DESCRIPTION = "Legion Go Speakers (EQ)"
FULL_VOLUME = 65536
RESTART_DELAY_S = 5.0
MAX_FAILURES = 5

# Starting points tuned by ear, not measured: (type, freq Hz, Q, gain dB).
# The high-pass keeps the small drivers out of the low bass they distort on.
PRESETS = {
    "balanced": {"label": "Balanced", "filters": [
        ("bq_highpass", 120, 0.7, 0.0),
        ("bq_peaking", 220, 1.0, 2.5),
        ("bq_peaking", 3200, 1.4, -3.0),
        ("bq_highshelf", 9000, 0.7, 2.0)]},
    "voice": {"label": "Voice and dialogue", "filters": [
        ("bq_highpass", 160, 0.7, 0.0),
        ("bq_peaking", 300, 1.0, -2.0),
        ("bq_peaking", 2400, 1.2, 2.5),
        ("bq_peaking", 6000, 1.5, -1.5)]},
    "bass": {"label": "More bass", "filters": [
        ("bq_highpass", 90, 0.7, 0.0),
        ("bq_lowshelf", 200, 0.7, 5.0),
        ("bq_peaking", 3200, 1.4, -2.0),
        ("bq_highshelf", 10000, 0.7, 1.5)]},
    "flat": {"label": "Flat (bass and treble only)", "filters": [
        ("bq_highpass", 100, 0.7, 0.0)]},
}
TONE_DB = 6          # bass / treble adjustment range: -6 .. +6 dB


def filters_for(preset, bass=0, treble=0):
    """The preset's filters plus the bass / treble adjustment."""
    out = list(PRESETS.get(preset, PRESETS["balanced"])["filters"])
    bass = max(-TONE_DB, min(TONE_DB, float(bass or 0)))
    treble = max(-TONE_DB, min(TONE_DB, float(treble or 0)))
    if bass:
        out.append(("bq_lowshelf", 250, 0.7, bass))
    if treble:
        out.append(("bq_highshelf", 6000, 0.7, treble))
    return out


def preamp_db(filters):
    """Headroom for the boosts, so they do not clip."""
    boost = sum(max(0.0, g) for t, _, _, g in filters if t != "bq_highpass")
    return -round(min(boost, 12.0), 1)


def build_conf(speaker_sink, filters):
    """The pipewire configuration of the filter chain (SPA JSON)."""
    nodes, chain = [], []
    # A high shelf at 0 Hz is a plain gain: the preamp.
    stages = [("bq_highshelf", 0, 1.0, preamp_db(filters))] + list(filters)
    for i, (kind, freq, q, gain) in enumerate(stages):
        name = "eq_%d" % i
        chain.append(name)
        nodes.append('      { type = builtin name = %s label = %s control = { "Freq" = %s "Q" = %s "Gain" = %s } }'
                     % (name, kind, float(freq), float(q), float(gain)))
    links = ['      { output = "%s:Out" input = "%s:In" }' % (a, b) for a, b in zip(chain, chain[1:])]
    target = json.dumps(str(speaker_sink))
    return """# Written by Legion Go Toolbox (Speaker EQ). Regenerated at every start.
context.properties = { log.level = 2 }
context.spa-libs = {
  audio.convert.* = audioconvert/libspa-audioconvert
  support.*       = support/libspa-support
}
context.modules = [
  { name = libpipewire-module-rt flags = [ ifexists nofail ] }
  { name = libpipewire-module-protocol-native }
  { name = libpipewire-module-client-node }
  { name = libpipewire-module-adapter }
  { name = libpipewire-module-filter-chain
    args = {
      node.description = "%(desc)s"
      media.name       = "%(desc)s"
      filter.graph = {
        nodes = [
%(nodes)s
        ]
        links = [
%(links)s
        ]
      }
      audio.channels = 2
      audio.position = [ FL FR ]
      capture.props = {
        node.name   = "%(node)s"
        media.class = Audio/Sink
      }
      playback.props = {
        node.name        = "%(node)s.out"
        node.passive     = true
        target.object    = %(target)s
        stream.dont-remix = true
      }
    }
  }
]
""" % {"desc": EQ_DESCRIPTION, "nodes": "\n".join(nodes), "links": "\n".join(links),
       "node": EQ_NODE, "target": target}


# ---- reading PipeWire's sinks (pactl -f json) ------------------------------

def _ports(sink):
    return [((p.get("name") or "") + " " + (p.get("description") or "")).lower()
            for p in sink.get("ports") or [] if isinstance(p, dict)]


def find_speaker(sinks):
    """The built-in speakers' sink, or None."""
    internal = []
    for s in sinks:
        name = (s.get("name") or "").lower()
        if not name.startswith("alsa_output.") or "hdmi" in name or ".usb-" in name:
            continue
        if "speaker" in name:
            return s                       # UCM: one sink per output
        if any("speaker" in p for p in _ports(s)):
            return s
        if name.startswith("alsa_output.pci"):
            internal.append(s)
    return internal[0] if len(internal) == 1 else None


def speakers_active(sink):
    name = (sink.get("name") or "").lower()
    if "speaker" in name:
        return True
    port = (sink.get("active_port") or "").lower()
    return "speaker" in port if port else True


def volume_of(sink):
    """The sink's first channel volume (65536 = 100 %), or None."""
    for ch in (sink.get("volume") or {}).values():
        if isinstance(ch, dict) and isinstance(ch.get("value"), int):
            return ch["value"]
    return None


def route(sinks, default):
    """Which sink should be the default now: a name, or None to leave it."""
    names = {s.get("name") for s in sinks}
    spk = find_speaker(sinks)
    if spk is None or EQ_NODE not in names:
        return None
    active = speakers_active(spk)
    if default == EQ_NODE and not active:
        return spk["name"]
    if default == spk.get("name") and active:
        return EQ_NODE
    return None


def other_processing(sinks):
    """Descriptions of other virtual sinks that look like speaker processing."""
    out = []
    for s in sinks:
        name = s.get("name") or ""
        if name == EQ_NODE or name.startswith("alsa_output.") or name.startswith("bluez_"):
            continue
        text = (name + " " + (s.get("description") or "")).lower()
        if any(w in text for w in ("eq", "filter", "dsp", "speaker", "easyeffects")):
            out.append(s.get("description") or name)
    return out


class SpeakerEq(object):
    def __init__(self, user, log_path, logger=None, clock=time.monotonic):
        self.user = user
        self.log_path = log_path
        self.log = logger
        self._clock = clock
        self._proc = None
        self._conf_key = None
        self._failures = 0
        self._retry_at = 0.0
        self._eq_volume = None        # the user's volume while the EQ plays
        self._spk_raised = False      # we set the speaker sink to 100 %
        self.error = None
        self.state = "off"            # off | starting | on | headphones | other | failed
        self.speaker = None
        self.others = []

    # -- environment ---------------------------------------------------------
    def capability(self):
        if self.user.uid is None:
            return False, "The Steam user's account was not found"
        if not self.user.which("pactl") or not self.user.which("pipewire"):
            return False, "PipeWire's tools (pipewire, pactl) are not installed"
        return True, None

    def _pactl(self, *args):
        return self.user.run([self.user.which("pactl") or "pactl"] + list(args), timeout=4.0)

    def sinks(self):
        rc, out, _ = self._pactl("-f", "json", "list", "sinks")
        if rc != 0:
            return None
        try:
            data = json.loads(out)
        except ValueError:
            return None
        return [s for s in data if isinstance(s, dict)] if isinstance(data, list) else None

    def default(self):
        rc, out, _ = self._pactl("get-default-sink")
        return out.strip() if rc == 0 else None

    def _set_volume(self, sink, value):
        if sink and value is not None:
            self._pactl("set-sink-volume", sink, str(int(value)))

    # -- process -------------------------------------------------------------
    @property
    def conf_path(self):
        return os.path.join(self.user.runtime_dir or "/tmp", "lgo-speaker-eq.conf")

    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def _kill_strays(self):
        """A process left from before a plugin reload still holds the sink."""
        needle = self.conf_path.encode()
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or (self._proc is not None and int(pid) == self._proc.pid):
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    if needle in f.read():
                        os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass

    def _start(self, conf):
        from .useros import write_atomic
        err = write_atomic(self.conf_path, conf, user=self.user)
        if err:
            self.error = err
            return False
        self._kill_strays()
        try:
            self._proc = self.user.spawn([self.user.which("pipewire") or "pipewire", "-c", self.conf_path],
                                         log_path=self.log_path)
            return True
        except (OSError, ValueError) as e:
            self.error = "Could not start PipeWire's filter chain: %s" % e
            return False

    def _stop_proc(self):
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def stop(self):
        """Back to the bare speakers, at the user's volume."""
        sinks = self.sinks() or []
        spk = find_speaker(sinks)
        if spk is not None and self.default() == EQ_NODE:
            self._pactl("set-default-sink", spk["name"])
        if spk is not None and self._spk_raised:
            self._set_volume(spk["name"], self._eq_volume)
        self._spk_raised = False
        self._stop_proc()
        self._conf_key = None
        self.state = "off"

    # -- the loop ------------------------------------------------------------
    def tick(self, conf):
        """conf: {"enabled", "preset", "bass", "treble"}. Called every few seconds."""
        if not conf.get("enabled"):
            if self._proc is not None or self._spk_raised:
                self.stop()
            self.state, self.error, self._failures = "off", None, 0
            return
        sinks = self.sinks()
        if sinks is None:
            self.state, self.error = "starting", "PipeWire is not answering (is the user session running?)"
            return
        spk = find_speaker(sinks)
        self.speaker = spk.get("description") if spk else None
        self.others = other_processing(sinks)
        if spk is None:
            self.state, self.error = "failed", "The built-in speakers were not found among PipeWire's outputs"
            return
        by_name = {s.get("name"): s for s in sinks}
        default = self.default()
        filters = filters_for(conf.get("preset"), conf.get("bass"), conf.get("treble"))
        key = (spk["name"], tuple(filters))

        if key != self._conf_key and self.running():
            # Changed settings: leave the speakers at the user's volume while the sink is rebuilt.
            if default == EQ_NODE:
                self._pactl("set-default-sink", spk["name"])
                default = spk["name"]
            if self._spk_raised:
                self._set_volume(spk["name"], self._eq_volume)
                self._spk_raised = False
            self._stop_proc()

        if not self.running():
            if self._spk_raised:     # the sink vanished: do not leave the speakers at 100 %
                self._set_volume(spk["name"], self._eq_volume)
                self._spk_raised = False
            if self._failures >= MAX_FAILURES:
                self.state = "failed"
                self.error = "PipeWire did not accept the EQ (log: %s)" % self.log_path
                return
            now = self._clock()
            if now < self._retry_at:
                return
            if self._conf_key == key:
                self._failures += 1      # it ran with this setup and stopped
            self._conf_key = key
            self._retry_at = now + RESTART_DELAY_S
            self.state = "starting"
            self._start(build_conf(spk["name"], filters))
            return

        if EQ_NODE not in by_name:
            self.state = "starting"
            return
        self._failures, self.error = 0, None

        target = route(sinks, default)
        if target == EQ_NODE:
            v = self._eq_volume if self._spk_raised else volume_of(spk)
            self._set_volume(EQ_NODE, v)
            self._pactl("set-default-sink", EQ_NODE)
            self._set_volume(spk["name"], FULL_VOLUME)
            self._eq_volume, self._spk_raised = v, True
            default = EQ_NODE
        elif target is not None:
            self._pactl("set-default-sink", target)
            if self._spk_raised:
                self._set_volume(target, self._eq_volume)
                self._spk_raised = False
            default = target
        if default == EQ_NODE:
            if target is None:   # the reading above is from before any change made here
                self._eq_volume = volume_of(by_name[EQ_NODE]) or self._eq_volume
            if not self._spk_raised:
                self._set_volume(spk["name"], FULL_VOLUME)
                self._spk_raised = True
            self.state = "on"
        else:
            self.state = "headphones" if default == spk["name"] else "other"

    def status(self):
        return {"state": self.state, "error": self.error, "speaker": self.speaker,
                "others": self.others}
