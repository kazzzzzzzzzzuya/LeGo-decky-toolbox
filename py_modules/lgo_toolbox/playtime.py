"""Battery playtime: make a game last a chosen number of hours on battery.

The idea is a power budget. With E watt-hours left and H hours still to
play, the whole device may draw E / H watts on average. The battery reports
what the device draws right now, so this is a feedback loop:

* Too much drawn -> lower the power limit (TDP) the game gets.
* The power limit at its lowest and still too much, or the game no longer
  keeping its frame cap at the lower limit -> step the frame cap down to the
  next even one (60 -> 30 ...), never below the user's lowest frame rate.
  Where Frame Suite has lsfg-vk ready for the game, the first step down is
  "half the frames, doubled by frame generation" (60 -> 30 x 2), which looks
  the same on screen and costs far less.
* Plenty left over for a few minutes -> undo the last step, then add power.

What each power limit costs in this game is remembered, so the longest
possible playtime can be estimated before a goal is chosen and gets more
exact the more the game is played on battery.

Pure logic: the hub feeds it readings and applies what it returns.
"""

import math

RESERVE = 0.04            # share of a full battery kept back: SteamOS shuts down before empty
BASE_W = 5.5              # screen, memory, controllers: drawn whatever the power limit
W_PER_TDP = 1.15          # battery watts per watt of power limit (conversion losses)
FAST_TAU_S = 20.0         # averaging of the draw the controller acts on
SLOW_TAU_S = 120.0        # averaging of the draw the estimates use
CONTROL_S = 15.0          # how often the budget is checked
SETTLE_S = 8.0            # readings right after a change are not used
OVER = 1.03               # above budget x this: cut
UNDER = 0.85              # below budget x this (for UNDER_S): give back
UNDER_S = 120.0
SLOW_FPS = 0.93           # frames below cap x this ...
SLOW_S = 30.0             # ... this long while the power limit is ours: cap down
AT_MIN_S = 45.0           # over budget this long at the lowest power limit: cap down
MAX_HOURS = 24.0          # "as long as possible"
MAX_BINS = 48


def ewma(old, value, dt, tau):
    if old is None:
        return value
    a = 1.0 - math.exp(-max(0.0, dt) / tau)
    return old + a * (value - old)


def usable_wh(energy_wh, full_wh):
    """Energy that can still be used before SteamOS powers off."""
    if energy_wh is None:
        return None
    reserve = RESERVE * full_wh if full_wh else 2.0
    return max(0.0, energy_wh - reserve)


def steps(user_cap, user_fg, floor, choices, even=None, fg_ready=False):
    """The settings Battery playtime may use, from the user's own to the most
    frugal: [(cap, frame-generation multiplier or None to leave it)].

    With frame generation ready (and the user not running it already) the
    first steps keep the frames on screen at most the user's cap: half the
    frames, doubled. Without, the cap steps down through the even caps (the
    screen divides them evenly); any cap when none is even."""
    out = [(user_cap, None)]
    lower = sorted({c for c in choices if floor <= c < user_cap}, reverse=True)
    if even is not None:
        smooth = [c for c in lower if even(c)]
        lower = smooth or lower
    if fg_ready and (user_fg or 1) <= 1:
        doubled = [c for c in sorted({c for c in choices if floor <= c < user_cap}, reverse=True)
                   if c * 2 <= user_cap and (even is None or even(c * 2))]
        if doubled:
            # Last: the same frames without frame generation, which costs power too.
            return out + [(c, 2) for c in doubled] + [(doubled[-1], None)]
    return out + [(c, None) for c in lower]


def fmt_hours(h):
    if h is None:
        return None
    return round(max(0.0, min(h, 99.0)), 2)


class Model(object):
    """What the battery draws at each power limit in one game:
    {tdp: [watts, fps_ok]}, learned while it runs on battery."""

    def __init__(self, data=None):
        self.bins = {}
        for k, v in (data or {}).items():
            try:
                tdp = int(k)
                watts, ok = float(v[0]), bool(v[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if 1 <= tdp <= 60 and 0.5 < watts < 100:
                self.bins[tdp] = [watts, ok]

    def to_json(self):
        return {str(k): [round(v[0], 2), v[1]] for k, v in sorted(self.bins.items())}

    def learn(self, tdp, watts, fps_ok):
        old = self.bins.get(tdp)
        self.bins[tdp] = [watts if old is None else old[0] * 0.7 + watts * 0.3, bool(fps_ok)]
        while len(self.bins) > MAX_BINS:
            del self.bins[max(self.bins)]

    def fit(self):
        """(base watts, watts per watt of power limit) from what was seen."""
        pts = sorted(self.bins.items())
        if len(pts) >= 2 and pts[-1][0] - pts[0][0] >= 3:
            n = float(len(pts))
            mx = sum(t for t, _ in pts) / n
            my = sum(v[0] for _, v in pts) / n
            sxx = sum((t - mx) ** 2 for t, _ in pts)
            slope = sum((t - mx) * (v[0] - my) for t, v in pts) / sxx if sxx else 0.0
            if 0.3 <= slope <= 2.5:
                base = my - slope * mx
                if 1.5 <= base <= 12.0:
                    return base, slope
        return None

    def min_draw(self, tdp_min, now_tdp, now_w, now_fps, floor):
        """Lowest draw this game can run at while keeping `floor` fps."""
        held = [v[0] for v in self.bins.values() if v[1]]
        # A power limit seen dropping the game below `floor`: anything lower is out.
        too_low = max([v[0] for v in self.bins.values() if not v[1]] or [0.0])
        fit = self.fit()
        base, slope = fit if fit else (BASE_W, W_PER_TDP)
        guess = None
        if now_w is not None and now_tdp:
            # Frames cost power roughly in proportion: what keeps `floor` fps.
            need = float(tdp_min)
            if now_fps and now_fps > 0:
                need = max(tdp_min, min(now_tdp, now_tdp * floor / now_fps))
            guess = now_w - slope * max(0.0, now_tdp - need)
        elif fit:
            guess = base + slope * tdp_min
        if guess is not None:
            guess = max(guess, base + 0.5, too_low + 0.1 if too_low else 0.0)
        candidates = [x for x in (min(held) if held else None, guess) if x is not None]
        return min(candidates) if candidates else None


class Planner(object):
    """One game's battery goal while it runs."""

    def __init__(self, hours, floor, tdp_min, tdp_max, start_tdp, model=None):
        self.hours = float(hours)
        self.floor = int(floor)
        self.tdp_min = int(tdp_min)
        self.tdp_max = int(max(tdp_max, tdp_min))
        self.ceiling = int(min(self.tdp_max, max(self.tdp_min, start_tdp)))
        self.model = model or Model()
        self.step = 0                 # index into the steps list
        self.floor_tdp = None         # lowest power limit that keeps `floor` fps at this step
        self.fast = None
        self.slow = None
        self._last = None
        self._changed_at = None
        self._checked_at = None
        self._under_since = None
        self._slow_since = None
        self._at_min_since = None
        self.state = "starting"

    # -- readings ---------------------------------------------------------
    def add(self, now, watts):
        if watts is None or watts < 0.5 or watts > 100:
            self._last = now
            return
        dt = now - self._last if self._last is not None else 0.0
        if dt > 30:                        # suspended or paused: start over
            self.fast = self.slow = None
        self._last = now
        self.fast = ewma(self.fast, watts, dt, FAST_TAU_S)
        self.slow = ewma(self.slow, watts, dt, SLOW_TAU_S)

    def _set_step(self, step):
        if step != self.step:
            self.step = step
            self.floor_tdp = None

    def changed(self, now):
        self._changed_at = now
        self._under_since = None
        self._slow_since = None

    def _learn(self, applied_tdp, fps):
        if applied_tdp and self.fast is not None and fps is not None:
            self.model.learn(int(applied_tdp), self.fast, fps >= self.floor * 0.95)

    def observe(self, now, applied_tdp, fps):
        """Without a goal: only learn what this game draws (for the estimate)."""
        if self.fast is None or (self._changed_at is not None and now - self._changed_at < SETTLE_S):
            return
        if self._checked_at is not None and now - self._checked_at < CONTROL_S:
            return
        self._checked_at = now
        self._learn(applied_tdp, fps)

    # -- the budget -------------------------------------------------------
    def budget(self, usable, played_h):
        left = self.hours - played_h
        if usable is None:
            return None
        if left <= 0.02:
            return float("inf")
        return usable / left

    def tick(self, now, usable, played_h, applied_tdp, fps, cap, n_steps, step_ok=True):
        """Decide. Returns (ceiling, step) for the hub to apply.

        cap      the frame cap in effect (None: no Smooth cap for the game)
        n_steps  how many settings steps exist (1: only the user's own)
        step_ok  the next step down is usable right now
        """
        budget = self.budget(usable, played_h)
        if budget is None or self.fast is None:
            self.state = "measuring"
            return self.ceiling, self.step
        if budget == float("inf"):
            self.state = "reached"
            if self.ceiling != self.tdp_max or self.step:
                self.ceiling = self.tdp_max
                self._set_step(0)
                self.changed(now)
            return self.ceiling, self.step
        if self._changed_at is not None and now - self._changed_at < SETTLE_S:
            self.state = "settling"
            return self.ceiling, self.step
        if self._checked_at is not None and now - self._checked_at < CONTROL_S:
            return self.ceiling, self.step
        self._checked_at = now
        self._learn(applied_tdp, fps)

        limited = applied_tdp is not None and applied_tdp >= self.ceiling
        slow = cap and fps is not None and fps < cap * SLOW_FPS and limited
        self._slow_since = (self._slow_since or now) if slow else None
        over = self.fast > budget * OVER
        under = self.fast < budget * UNDER
        self._under_since = (self._under_since or now) if under else None
        at_min = over and self.ceiling <= max(self.tdp_min, self.floor_tdp or self.tdp_min)
        self._at_min_since = (self._at_min_since or now) if at_min else None
        can_down = self.step + 1 < n_steps and step_ok
        lowest = max(self.tdp_min, self.floor_tdp or self.tdp_min)

        if not can_down and limited and fps is not None and fps < self.floor * 0.97:
            # Below the lowest frame rate the user accepts, with no step left: that wins
            # over the goal. Remember it, so the budget does not cut below it again.
            if self.ceiling < self.tdp_max:
                self.ceiling += 1
                self.floor_tdp = self.ceiling
                self.changed(now)
            self.state = "floor"
            return self.ceiling, self.step
        if (self._at_min_since and now - self._at_min_since >= AT_MIN_S) or \
                (self._slow_since and now - self._slow_since >= SLOW_S):
            if can_down:
                # Fewer frames: their power returns as headroom for the rest.
                self._set_step(self.step + 1)
                self.ceiling = min(self.tdp_max, self.ceiling + 2)
                self._at_min_since = None
                self.changed(now)
                self.state = "stepping_down"
                return self.ceiling, self.step
        if over and self.ceiling > lowest:
            base = applied_tdp if applied_tdp is not None else self.ceiling
            cut = max(1, min(4, int(math.ceil((self.fast - budget) / W_PER_TDP))))
            self.ceiling = max(lowest, min(self.ceiling, base) - cut)
            self.changed(now)
            self.state = "cutting"
            return self.ceiling, self.step
        if self._under_since and now - self._under_since >= UNDER_S:
            if self.step > 0:
                self._set_step(self.step - 1)
                self.changed(now)
                self.state = "stepping_up"
            elif self.ceiling < self.tdp_max and limited:
                self.ceiling += 1
                self.changed(now)
                self.state = "adding"
            else:
                self.state = "on_track"
            self._under_since = None
            return self.ceiling, self.step
        if over:
            self.state = "short"              # nothing left to give up
        elif self._slow_since:
            self.state = "short" if not can_down else "holding"
        else:
            self.state = "on_track"
        return self.ceiling, self.step

    # -- estimates --------------------------------------------------------
    def estimate(self, usable, played_h, applied_tdp, fps):
        draw = self.slow if self.slow is not None else self.fast
        now_h = usable / draw if usable is not None and draw else None
        low = self.model.min_draw(self.tdp_min, applied_tdp, draw, fps, self.floor)
        max_h = usable / low if usable is not None and low else None
        if max_h is not None and now_h is not None:
            max_h = max(max_h, now_h)
        left = max(0.0, self.hours - played_h)
        budget = self.budget(usable, played_h)
        return {
            "draw_w": round(draw, 1) if draw is not None else None,
            "budget_w": round(budget, 1) if budget not in (None, float("inf")) else None,
            "now_h": fmt_hours(now_h),
            "max_h": fmt_hours(max_h),
            "left_h": fmt_hours(left),
            "reachable": None if max_h is None else max_h >= left * 0.97,
        }
