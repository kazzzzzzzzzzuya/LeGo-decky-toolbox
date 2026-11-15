"""Battery playtime: the planner on its own, and the hub driving a simulated
Legion Go whose battery drains by what it draws."""

import logging
import os
import unittest

import helpers  # noqa: F401  (sets up sys.path)

from lgo_toolbox import playtime as pt
from lgo_toolbox.hub import Hub
from test_toolbox import (FakeCharge, FakeFan, FakeGamescopeCtl, FakeLed, FakeLimits, FakeSteamPad,
                          FakeSwap, TempDirCase)
from lgo_toolbox import smooth as smoothmod

EVEN_144 = lambda c: any(r % c == 0 for r in (60, 144))


class Device(object):
    """A handheld running one game. The game makes `fps_per_w` frames per watt of
    power limit up to its cap; the battery feeds the screen and the rest (`base`)
    plus the chip; frame generation doubles the frames for `fg_cost` watts."""

    def __init__(self, energy=45.0, full=49.0, fps_per_w=8.0, base=5.5, k=1.1, fg_cost=0.8):
        self.energy, self.full = energy, full
        self.fps_per_w, self.base, self.k, self.fg_cost = fps_per_w, base, k, fg_cost
        self.watts = None
        self.game_fps = None
        self.shown = None

    def run(self, dt, tdp, cap, fg=1):
        self.game_fps = min(cap or 1e9, self.fps_per_w * tdp)
        soc = self.game_fps / self.fps_per_w
        self.watts = self.base + self.k * soc + (self.fg_cost if fg > 1 else 0.0)
        self.energy = max(0.0, self.energy - self.watts * dt / 3600.0)
        self.shown = self.game_fps * fg

    def info(self):
        return {"percent": int(100 * self.energy / self.full), "status": "Discharging",
                "watts": self.watts, "minutes": None, "energy_wh": self.energy, "full_wh": self.full}


class Steps(unittest.TestCase):
    def test_even_caps_without_frame_generation(self):
        self.assertEqual(pt.steps(60, 1, 30, smoothmod.CANDIDATES, EVEN_144),
                         [(60, None), (48, None), (36, None), (30, None)])
        self.assertEqual(pt.steps(60, 1, 45, smoothmod.CANDIDATES, EVEN_144),
                         [(60, None), (48, None)])
        self.assertEqual(pt.steps(30, 1, 30, smoothmod.CANDIDATES, EVEN_144), [(30, None)])

    def test_frame_generation_keeps_the_screen_at_the_cap(self):
        self.assertEqual(pt.steps(60, 1, 30, smoothmod.CANDIDATES, EVEN_144, fg_ready=True),
                         [(60, None), (30, 2), (30, None)])
        self.assertEqual(pt.steps(72, 1, 30, smoothmod.CANDIDATES, EVEN_144, fg_ready=True),
                         [(72, None), (36, 2), (30, 2), (30, None)])
        self.assertEqual(pt.steps(144, 1, 30, smoothmod.CANDIDATES, EVEN_144, fg_ready=True),
                         [(144, None), (72, 2), (36, 2), (30, 2), (30, None)])   # 48 x 2 = 96: uneven
        # Not when the user runs frame generation already, or half the cap is below the floor
        self.assertEqual(pt.steps(60, 2, 30, smoothmod.CANDIDATES, EVEN_144, fg_ready=True)[1], (48, None))
        self.assertEqual(pt.steps(45, 1, 30, smoothmod.CANDIDATES, EVEN_144, fg_ready=True),
                         [(45, None), (36, None), (30, None)])


class Model(unittest.TestCase):
    def test_learns_and_fits(self):
        m = pt.Model()
        for tdp in (6, 8, 10, 12, 14):
            m.learn(tdp, 5.0 + 1.2 * tdp, True)
        base, slope = m.fit()
        self.assertAlmostEqual(base, 5.0, 3)
        self.assertAlmostEqual(slope, 1.2, 3)
        self.assertEqual(pt.Model(m.to_json()).bins, m.bins)

    def test_minimum_keeps_the_floor(self):
        m = pt.Model({"6": [12.0, False], "10": [17.0, True], "15": [22.0, True]})
        # Seen: 10 W holds the floor, 6 W does not -> nothing below what 6 W drew
        low = m.min_draw(5, 15, 22.0, 60, 30)
        self.assertGreater(low, 12.0)
        self.assertLessEqual(low, 17.0)

    def test_bad_data_is_dropped(self):
        m = pt.Model({"x": [1, True], "8": ["a"], "9": [500, True], "10": [9.5, 1], "11": None})
        self.assertEqual(m.to_json(), {"10": [9.5, True]})


class PlannerSim(unittest.TestCase):
    def run_sim(self, hours, device, cap, floor=30, fg_ready=False, minutes=90, tdp_max=15):
        steps = pt.steps(cap, 1, floor, smoothmod.CANDIDATES, EVEN_144, fg_ready)
        p = pt.Planner(hours, floor, 5, tdp_max, tdp_max)
        played = 0.0
        tdp = tdp_max
        for s in range(minutes * 60):
            c, fg = steps[p.step]
            device.run(1.0, tdp, c, fg or 1)
            p.add(float(s), device.watts)
            usable = pt.usable_wh(device.energy, device.full)
            played += 1.0 / 3600.0
            tdp, _ = p.tick(float(s), usable, played, tdp, device.game_fps, c, len(steps))
        return p, steps

    def lasts(self, hours, device, cap, fg_ready=False):
        """Play until the goal or an empty battery: hours actually played."""
        steps = pt.steps(cap, 1, 30, smoothmod.CANDIDATES, EVEN_144, fg_ready)
        p = pt.Planner(hours, 30, 5, 15, 15)
        tdp, s, low_fps = 15, 0, 1e9
        while True:
            usable = pt.usable_wh(device.energy, device.full)
            played = s / 3600.0
            if usable <= 0 or played >= hours:
                return played, low_fps, p
            c, fg = steps[p.step]
            device.run(1.0, tdp, c, fg or 1)
            if s > 600:
                low_fps = min(low_fps, device.game_fps)
            p.add(float(s), device.watts)
            tdp, _ = p.tick(float(s), usable, played, tdp, device.game_fps, c, len(steps))
            s += 1

    def test_reachable_goals_are_met_over_the_whole_battery(self):
        # On this device 60 fps lasts about 3.1 h, 30 fps about 4.5 h.
        for hours, fg in ((3.0, False), (4.0, False), (4.0, True), (4.4, True)):
            played, low_fps, p = self.lasts(hours, Device(), 60, fg)
            self.assertGreaterEqual(played, hours * 0.98, (hours, fg, played))
            self.assertGreaterEqual(low_fps, 30 * 0.9, (hours, fg))     # never far below the floor

    def test_an_unreachable_goal_still_gets_the_most_out_of_the_battery(self):
        d = Device()
        best = pt.usable_wh(d.energy, d.full) / (5.5 + 1.1 * 30 / 8.0)
        played, low_fps, p = self.lasts(7.0, d, 60)
        self.assertGreaterEqual(played, best * 0.95)
        self.assertGreaterEqual(low_fps, 30 * 0.9)

    def test_reachable_goal_lands_on_budget_and_stays_smooth(self):
        d = Device()
        p, steps = self.run_sim(4.0, d, 60)
        usable = pt.usable_wh(d.energy, d.full)
        budget = usable / (4.0 - 1.5)
        self.assertLessEqual(d.watts, budget + 1.2)            # within one watt step of power limit
        self.assertGreaterEqual(d.game_fps, 30)
        self.assertIn(steps[p.step][0], (48, 36, 30))           # an even cap, the game keeps it
        self.assertGreaterEqual(d.game_fps, steps[p.step][0] * 0.93)
        est = p.estimate(usable, 1.5, p.ceiling, d.game_fps)
        self.assertTrue(est["reachable"])

    def test_frame_generation_is_used_first_when_ready(self):
        d = Device()
        p, steps = self.run_sim(4.0, d, 60, fg_ready=True)
        self.assertEqual(steps[p.step], (30, 2))         # 4 h fits with frame generation on
        self.assertEqual(d.shown, 60)

    def test_unreachable_goal_holds_the_floor_and_says_so(self):
        d = Device()
        p, steps = self.run_sim(7.0, d, 60, minutes=40)
        self.assertEqual(steps[p.step][0], 30)
        self.assertGreaterEqual(d.game_fps, 30 * 0.93)
        usable = pt.usable_wh(d.energy, d.full)
        est = p.estimate(usable, 40 / 60.0, p.ceiling, d.game_fps)
        self.assertFalse(est["reachable"])
        self.assertEqual(p.state, "short")
        # 30 fps costs 3.75 W of chip power: 5.5 + 4.1 W -> what is left lasts that long
        self.assertAlmostEqual(est["max_h"], usable / (5.5 + 1.1 * 3.75), delta=0.3)

    def test_plenty_of_battery_gives_settings_back(self):
        d = Device(energy=45.0)
        p, steps = self.run_sim(3.0, d, 60, minutes=10)
        cut = p.step
        p.hours = 1.0                  # far more than needed now
        tdp = p.ceiling
        for s in range(600, 1500):
            c, fg = steps[p.step]
            d.run(1.0, tdp, c, fg or 1)
            p.add(float(s), d.watts)
            tdp, _ = p.tick(float(s), pt.usable_wh(d.energy, d.full), 0.2, tdp, d.game_fps, c, len(steps))
        self.assertLess(p.step, max(cut, 1))
        self.assertEqual(steps[p.step][0], 60)

    def test_goal_reached_releases_everything(self):
        p = pt.Planner(2.0, 30, 5, 15, 8)
        p.step = 2
        p.add(0.0, 9.0)
        ceiling, step = p.tick(1.0, 20.0, 2.0, 8, 30, 30, 3)
        self.assertEqual((ceiling, step, p.state), (15, 0, "reached"))

    def test_a_suspend_gap_restarts_the_average(self):
        p = pt.Planner(2.0, 30, 5, 15, 15)
        p.add(0.0, 20.0)
        p.add(1.0, 20.0)
        p.add(500.0, 8.0)
        self.assertEqual(p.fast, 8.0)


class HubPlaytime(TempDirCase):
    """The hub with a simulated device, Smooth mode and Frame Suite."""

    def setUp(self):
        TempDirCase.setUp(self)
        self.dev = Device()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.requests = []
        dev = self.dev
        self.lsfg_mult = {}
        self.suite_info = {"lsfg_ready": True, "standby_since": 0.0, "fg_applied": None, "fg_refused": None}

        test = self

        class Fps(object):
            app = None
            error = None

            def set_app(self, app):
                self.app = app

            def get(self):
                return dev.shown

            def get_low(self):
                return None

            def stop(self):
                pass

        class Lsfg(object):
            def for_app(self, app):
                m = test.lsfg_mult.get(app, 1)
                return {"installed": True, "multiplier": m, "profile": "P" if m > 1 else None,
                        "base_cap": 0, "error": None}

        class Suite(object):
            def for_app(self, app):
                return dict({"present": True, "optiscaler": False, "multiplier": 1, "route": "lsfg",
                             "error": None}, **test.suite_info)

            def home(self):
                return test.home

        def write_requests(home, games):
            test.requests.append(games)
            # Frame Suite answers by switching lsfg-vk, and back for what is no longer asked
            test.lsfg_mult = {int(k): v["multiplier"] or 1 for k, v in games.items()}
            test.suite_info["fg_applied"] = (games.get("7") or {}).get("multiplier")
            return None

        self.limits = FakeLimits()
        self.mods = {
            "limits": self.limits, "fan": FakeFan(), "charge": FakeCharge(), "led": FakeLed(),
            "swap": FakeSwap(), "fps": Fps(), "steam_pad": FakeSteamPad(),
            "gamescope": FakeGamescopeCtl(), "mangohud_env": lambda: "MANGOHUD", "lsfg": Lsfg(),
            "suite": Suite(), "home": lambda: self.home, "limit_on_output": lambda home: True,
            "send": lambda cmds: None, "sensors": lambda: {"temp": 55, "rpm": None},
            "battery_info": dev.info, "on_ac": lambda: False, "set_boost": lambda v: True,
            "boost_state": lambda: None, "write_requests": write_requests, "wall": lambda: 1000.0,
        }
        log = logging.getLogger("pttest")
        log.addHandler(logging.NullHandler())
        log.propagate = False
        self.hub = Hub(os.path.join(self.tmp, "toolbox.json"), logger=log, product="83E1", modules=self.mods)
        self.hub.update({"power": {"profiles": {"default": {"mode": "custom", "tdp": 15}}}})
        self.hub.set_running_app(7, "Persona 5 Royal")
        plan = self.hub.smooth_plan(60, 7)
        self.hub.set_smooth_game(7, 60, "Persona 5 Royal", plan["prefix"], False)
        self.conf = os.path.join(self.home, ".config", "lgo-toolbox", "smooth", "7.conf")

    def drive(self, seconds, start=0.0):
        for s in range(int(seconds)):
            entry = self.hub.smooth_for()
            cap = entry["fps"] if entry else None
            self.dev.run(1.0, self.limits.value, cap, self.lsfg_mult.get(7, 1))
            self.hub._tick(start + s)
        return start + seconds

    def test_estimate_before_a_goal(self):
        self.drive(200)
        st = self.hub.status()["playtime"]
        self.assertIsNone(st["goal"])
        self.assertIsNone(self.hub._pt_ceiling)                 # nothing changed without a goal
        self.assertEqual(self.limits.value, 15)
        self.assertGreater(st["max_h"], st["now_h"])          # less power would last longer
        self.assertAlmostEqual(st["now_h"], pt.usable_wh(self.dev.energy, 49.0) / self.dev.watts, delta=0.2)

    def test_goal_with_frame_generation_end_to_end(self):
        self.drive(60)
        self.hub.set_playtime_goal(7, 4.0, 30, True, "Persona 5 Royal")
        t = self.drive(1800, 60)
        st = self.hub.status()["playtime"]
        self.assertEqual(st["goal"]["hours"], 4.0)
        self.assertGreater(st["goal"]["played_s"], 1700)
        self.assertEqual((self.hub._pt_cap, self.hub._pt_fg), (30, 2))   # 30 x 2 on screen
        self.assertEqual(self.lsfg_mult[7], 2)
        self.assertEqual(self.dev.shown, 60)
        self.assertIn("fps_limit=60\n", open(self.conf).read())          # the limiter sees 60 after lsfg-vk
        self.assertEqual(self.requests[-1]["7"], {"standby": True, "multiplier": 2})
        self.assertLessEqual(self.dev.watts, st["budget_w"] * 1.06)
        self.assertTrue(st["reachable"])
        self.assertEqual(self.hub.get_settings()["smooth"]["games"]["7"]["fps"], 60)   # the user's cap stays
        # Goal off: everything back, lsfg-vk off again before the cap goes up
        self.hub.set_playtime_goal(7, None)
        self.drive(10, t)
        self.assertIsNone(self.hub._pt_ceiling)
        self.assertEqual(self.requests[-1], {})
        self.assertEqual(self.lsfg_mult.get(7, 1), 1)
        self.assertEqual(self.hub.smooth_for()["fps"], 60)
        self.assertEqual(self.limits.value, 15)

    def test_a_goal_switches_power_management_on(self):
        self.assertFalse(self.hub.get_settings()["power"]["enabled"])
        out = self.hub.set_playtime_goal(7, 3.0, 30, True, "P5R")
        self.assertTrue(out["power"]["enabled"])
        self.assertEqual(self.limits.value, 15)
        self.hub.set_playtime_goal(7, None)
        self.assertTrue(self.hub.get_settings()["power"]["enabled"])     # left as it is

    def test_without_frame_generation_the_cap_steps_down_evenly(self):
        self.drive(60)
        self.hub.set_playtime_goal(7, 4.0, 30, False, "Persona 5 Royal")
        self.drive(1800, 60)
        self.assertIn(self.hub._pt_cap, (48, 36, 30))
        self.assertIsNone(self.hub._pt_fg)
        self.assertEqual(self.requests[-1], {})
        self.assertGreaterEqual(self.dev.game_fps, self.hub._pt_cap * 0.93)

    def test_frame_generation_waits_for_the_next_start(self):
        self.suite_info["standby_since"] = 2000.0          # made after the game started (wall 1000)
        self.drive(60)
        self.hub.set_playtime_goal(7, 4.0, 30, True, "P5R")
        self.drive(1200, 60)
        st = self.hub.status()["playtime"]
        self.assertEqual(st["fg_why"], "next_start")
        self.assertIsNone(self.hub._pt_fg)
        self.assertEqual(self.requests[-1]["7"], {"standby": True, "multiplier": None})

    def test_charger_pauses_and_hands_everything_back(self):
        self.drive(60)
        self.hub.set_playtime_goal(7, 4.0, 30, True, "P5R")
        t = self.drive(900, 60)
        self.assertIsNotNone(self.hub._pt_ceiling)
        played = self.hub.get_settings()["playtime"]["games"]["7"]["played_s"]
        self.mods["on_ac"] = lambda: True
        self.hub._read_on_ac = lambda: True
        self.dev.info = lambda: dict(Device.info(self.dev), status="Charging")
        self.hub._battery_info = self.dev.info
        self.drive(30, t)
        self.assertIsNone(self.hub._pt_ceiling)
        self.assertIsNone(self.hub._pt_cap)
        self.assertEqual(self.hub.get_settings()["playtime"]["games"]["7"]["played_s"], played)

    def test_learned_power_survives_a_restart(self):
        self.drive(400)
        self.hub.set_running_app(None)
        learned = self.hub.get_settings()["playtime"]["learned"]["7"]
        self.assertTrue(learned)
        again = Hub(os.path.join(self.tmp, "toolbox.json"), logger=self.hub._log, product="83E1",
                    modules=self.mods)
        self.assertEqual(again.get_settings()["playtime"]["learned"]["7"], learned)


if __name__ == "__main__":
    unittest.main()
