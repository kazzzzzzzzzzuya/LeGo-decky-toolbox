import json
import os
import shutil
import tempfile
import unittest

import helpers  # noqa: F401  (sets up sys.path)

from lgo_toolbox import backup, sleep_guard, speaker_eq as eq, steam_check, system

SPK = "alsa_output.pci-0000_c2_00.6.analog-stereo"


def sink(name, port=None, vol=30000, ports=("analog-output-speaker", "analog-output-headphones")):
    return {"name": name, "description": name, "active_port": port,
            "ports": [{"name": p, "description": p} for p in ports],
            "volume": {"front-left": {"value": vol}}}


class FakeUser(object):
    uid, gid, name = 1000, 1000, "deck"

    def __init__(self, home):
        self.home = home
        self.runtime_dir = home

    def path(self, *p):
        return os.path.join(self.home, *p)

    def which(self, prog):
        return "/usr/bin/" + prog

    def give(self, path):
        pass


class FakePactl(FakeUser):
    """Answers pactl like PipeWire would; records what was set."""

    def __init__(self, home, sinks, default):
        FakeUser.__init__(self, home)
        self.sinks, self.default, self.calls, self.spawned = sinks, default, [], []

    def run(self, cmd, timeout=5.0):
        args = cmd[1:]
        self.calls.append(args)
        if args[:3] == ["-f", "json", "list"]:
            return 0, json.dumps(self.sinks), ""
        if args == ["get-default-sink"]:
            return 0, self.default + "\n", ""
        if args[0] == "set-default-sink":
            self.default = args[1]
        if args[0] == "set-sink-volume":
            for s in self.sinks:
                if s["name"] == args[1]:
                    s["volume"] = {"front-left": {"value": int(args[2])}}
        return 0, "", ""

    def spawn(self, cmd, log_path=None):
        self.spawned.append(cmd)
        self.sinks.append(sink(eq.EQ_NODE, vol=65536, ports=()))

        class P(object):
            pid = 999999

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                pass
        return P()


class SpeakerEq(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_finds_the_speakers(self):
        hdmi = sink("alsa_output.pci-0000_c2_00.1.hdmi-stereo", ports=("hdmi-output-0",))
        bt = sink("bluez_output.AA_BB.1", ports=())
        self.assertEqual(eq.find_speaker([hdmi, bt, sink(SPK, "analog-output-speaker")])["name"], SPK)
        ucm = sink("alsa_output.pci-0000_c2_00.6.HiFi__Speaker__sink", ports=("[Out] Speaker",))
        self.assertEqual(eq.find_speaker([hdmi, ucm])["name"], ucm["name"])
        self.assertIsNone(eq.find_speaker([hdmi, bt]))
        tricks = {"name": "Legion GO", "description": "Legion GO"}
        self.assertEqual(eq.other_processing([hdmi, bt, tricks, sink(eq.EQ_NODE)]), ["Legion GO"])
        self.assertIsNone(eq.route([sink(SPK, "analog-output-speaker"), sink(eq.EQ_NODE), tricks], "Legion GO"))

    def test_route_follows_the_output(self):
        e = sink(eq.EQ_NODE, ports=())
        self.assertEqual(eq.route([sink(SPK, "analog-output-speaker"), e], SPK), eq.EQ_NODE)
        self.assertEqual(eq.route([sink(SPK, "analog-output-headphones"), e], eq.EQ_NODE), SPK)
        self.assertIsNone(eq.route([sink(SPK, "analog-output-speaker"), e], "bluez_output.x"))
        self.assertIsNone(eq.route([sink(SPK, "analog-output-speaker")], SPK))   # no EQ sink yet

    def test_conf_and_headroom(self):
        f = eq.filters_for("bass", bass=3, treble=-2)
        self.assertEqual(eq.preamp_db(f), -(5.0 + 1.5 + 3))
        conf = eq.build_conf(SPK, f)
        self.assertEqual(conf.count("{"), conf.count("}"))
        self.assertEqual(conf.count("["), conf.count("]"))
        self.assertIn('target.object    = "%s"' % SPK, conf)
        self.assertEqual(conf.count("label = "), len(f) + 1)
        self.assertEqual(conf.count("output = "), len(f))
        self.assertEqual(eq.filters_for("nope"), eq.PRESETS["balanced"]["filters"])

    def test_volume_moves_with_the_eq(self):
        u = FakePactl(self.dir, [sink(SPK, "analog-output-speaker", vol=30000)], SPK)
        e = eq.SpeakerEq(u, os.path.join(self.dir, "log"), clock=lambda: 100.0)
        on = {"enabled": True, "preset": "balanced"}
        e.tick(on)                       # starts the filter chain
        self.assertEqual(len(u.spawned), 1)
        self.assertTrue(os.path.exists(e.conf_path))
        e.tick(on)                       # routes to it
        self.assertEqual((u.default, e.state), (eq.EQ_NODE, "on"))
        vols = {s["name"]: eq.volume_of(s) for s in u.sinks}
        self.assertEqual(vols, {SPK: eq.FULL_VOLUME, eq.EQ_NODE: 30000})
        u.sinks[0]["active_port"] = "analog-output-headphones"
        e.tick(on)                       # headphones: back to the bare sink at the user's volume
        self.assertEqual((u.default, e.state), (SPK, "headphones"))
        self.assertEqual(eq.volume_of(u.sinks[0]), 30000)
        u.sinks[0]["active_port"] = "analog-output-speaker"
        e.tick(on)
        self.assertEqual(u.default, eq.EQ_NODE)
        e.tick({"enabled": False})       # off: speakers default again, user's volume
        self.assertEqual((u.default, eq.volume_of(u.sinks[0]), e.state), (SPK, 30000, "off"))


class SleepGuard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.alarm = os.path.join(self.dir, "wakealarm")
        open(self.alarm, "w").close()
        self.t = {"wall": 1000000.0, "mono": 0.0, "boot": 0.0}
        self.batt = {"percent": 90, "status": "Discharging"}
        self.off = []
        self.g = sleep_guard.SleepGuard(
            os.path.join(self.dir, "sleep.json"), lambda: dict(self.batt), poweroff=lambda: self.off.append(1),
            wakealarm=self.alarm, wall=lambda: self.t["wall"], mono=lambda: self.t["mono"],
            boot=lambda: self.t["boot"])

    def read(self, path):
        with open(path) as f:
            return f.read()

    def sleep(self, seconds, pct):
        self.t["wall"] += seconds
        self.t["boot"] += seconds
        self.batt["percent"] = pct

    def step(self, s=2.0):
        self.t["wall"] += s
        self.t["mono"] += s
        self.t["boot"] += s

    def test_measures_a_sleep(self):
        conf = {"poweroff": False}
        self.g.tick(conf)
        self.step()
        self.g.tick(conf)
        self.sleep(4 * 3600, 86)
        self.g.tick(conf)
        self.assertEqual(self.g.history, [])            # waits for the battery to settle
        for _ in range(5):
            self.step()
            self.g.tick(conf)
        last = self.g.status()["last"]
        self.assertEqual((last["pct_before"], last["pct_after"], last["drain_ph"]), (90, 86, 1.0))
        self.assertEqual(sleep_guard.SleepGuard(os.path.join(self.dir, "sleep.json"), dict).history[0]["pct_after"], 86)

    def test_powers_off_after_the_hours_only(self):
        conf = {"poweroff": True, "hours": 6, "battery_only": True}
        self.g.tick(conf)
        self.g.before_sleep(conf)
        self.assertEqual(self.read(self.alarm), str(int(self.t["wall"] + 6 * 3600)))
        self.sleep(1 * 3600, 89)                       # woken early by hand
        self.assertIsNone(self.g.tick(conf))
        self.assertEqual(self.read(self.alarm), "0")
        self.g.before_sleep(conf)
        self.sleep(6 * 3600, 80)                       # the alarm woke it
        self.assertEqual(self.g.tick(conf), "poweroff")
        self.assertEqual(self.off, [1])
        self.assertTrue(self.g.history[-1]["powered_off"])

    def test_no_alarm_on_the_charger(self):
        self.batt["status"] = "Charging"
        self.g.before_sleep({"poweroff": True, "hours": 6, "battery_only": True})
        self.assertIsNone(self.g.alarm_at)
        self.assertEqual(self.read(self.alarm), "0")


class SteamChecks(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.user = FakeUser(self.home)
        self.proc = os.path.join(self.home, "proc")
        self.state = os.path.join(self.home, "state")
        os.makedirs(self.state)
        self.put(".local/share/Steam/package/steam_client_steamdeck_stable.manifest",
                 '"version"\t\t"1794536281"')
        self.put(".local/share/SLSsteam/SLSsteam.so", "elf")
        self.put(".config/SLSsteam/config.yaml", "AdditionalApps:\n  - 10\nDecryptionKeys:\n  1: " + "a" * 64 + "\n")
        self.put(".local/share/CloudRedirect/cloud_redirect.so", "elf LeGo fork TLS")
        self.put(".config/CloudRedirect/settings.json", "{}")
        self.put(".config/CloudRedirect/cloud_redirect.log", "CloudRedirect build x\nHook ok\n")
        self.put(".local/share/ACCELA/db/plugin_library.json", '{"2552430": {}}')

    def put(self, rel, text):
        p = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def steam_runs(self, libs):
        d = os.path.join(self.proc, "4242")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "comm"), "w") as f:
            f.write("steam\n")
        with open(os.path.join(d, "maps"), "w") as f:
            for lib in ["/x/steamclient.so"] + libs:
                f.write("7f00-7f01 r-xp 00000000 00:00 1   %s\n" % lib)

    def test_all_working_then_an_update_breaks_it(self):
        c = steam_check.SteamCheck(self.user, self.state, proc=self.proc)
        self.steam_runs(["/h/SLSsteam.so", "/h/cloud_redirect.so"])
        r = c.check()
        self.assertEqual(r["overall"], "ok")
        self.assertEqual([i["id"] for i in r["items"]], ["steam", "slssteam", "cloudredirect", "accela"])
        self.assertEqual(r["last_good"], 1794536281)
        self.assertEqual(len(c.snapshots()), 1)
        c.check()
        self.assertEqual(len(c.snapshots()), 1)          # unchanged files: no new copy

        self.put(".local/share/Steam/package/steam_client_steamdeck_stable.manifest", '"version" "1799999999"')
        self.steam_runs(["/h/SLSsteam.so"])
        r = c.check()
        self.assertEqual(r["overall"], "fail")
        self.assertTrue(r["updated_since_good"])
        self.assertIn("NOT loaded", [i for i in r["items"] if i["id"] == "cloudredirect"][0]["detail"])

    def test_restore_puts_files_back(self):
        c = steam_check.SteamCheck(self.user, self.state, proc=self.proc)
        name = c.snapshot("test", force=True)
        self.put(".config/SLSsteam/config.yaml", "broken")
        out = c.restore(name)
        self.assertTrue(out["ok"], out)
        self.assertIn("DecryptionKeys", SleepGuard.read(None, os.path.join(self.home, ".config/SLSsteam/config.yaml")))
        self.assertFalse(c.restore("../../etc")["ok"])

    def test_problems_are_seen(self):
        self.assertTrue(steam_check.yaml_problems("A: 1\nA: 2\n"))
        self.assertTrue(steam_check.yaml_problems("A:\n\t- 1\n"))
        self.assertEqual(steam_check.yaml_problems("A: 1\nB:\n  - 2\n"), [])
        log = b"CloudRedirect build 1\nInit failed: x\nCloudRedirect build 2\nHook ok\n"
        self.assertEqual(steam_check.cr_log_problems(log), [])
        self.assertEqual(len(steam_check.cr_log_problems(log + b"signature not found for y\n")), 1)

    def test_hold_never_touches_a_foreign_cfg(self):
        c = steam_check.SteamCheck(self.user, self.state, proc=self.proc)
        self.assertTrue(c.set_hold(True)["ok"])
        self.assertTrue(c.hold_state()["held"])
        self.assertTrue(c.set_hold(False)["ok"])
        self.assertFalse(os.path.exists(c.cfg_path))
        self.put(".local/share/Steam/steam.cfg", "Mine=1\n")
        self.assertFalse(c.set_hold(False)["ok"])
        self.assertTrue(os.path.exists(c.cfg_path))


class WattsHistory(unittest.TestCase):
    def test_once_a_minute_and_none_while_charging(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        s = system.System(d, user=FakeUser(d))
        readings = iter([{"watts": 11.44, "status": "Discharging"}, {"watts": 30.0, "status": "Charging"}])
        system.battery_info = lambda: next(readings)
        try:
            s._sample_watts(0.0)
            s._sample_watts(30.0)        # too soon: skipped
            s._sample_watts(61.0)
        finally:
            import lgo_toolbox.battery as b
            system.battery_info = b.battery_info
        self.assertEqual(s.watts_history(), [11.4, None])


class Settings(unittest.TestCase):
    def test_sanitize(self):
        s = system.sanitize({"eq": {"enabled": 1, "preset": "x", "bass": 99}, "sleep": {"hours": 5}})
        self.assertEqual(s["eq"], {"enabled": True, "preset": "balanced", "bass": 6, "treble": 0})
        self.assertEqual(s["sleep"]["hours"], 6)

    def test_backup_carries_system(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        p = os.path.join(d, "b.json")
        backup.save(p, "2.12.0", {"a": 1}, {}, system.defaults())
        self.assertEqual(backup.load(p)["system"], system.defaults())
        backup.save(p, "2.12.0", {"a": 1}, {})
        self.assertNotIn("system", backup.load(p))


if __name__ == "__main__":
    unittest.main()
