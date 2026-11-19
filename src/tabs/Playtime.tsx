import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, useRef, useState } from "react";

import { PlaytimeStatus, restartPlaytime, setPlaytimeGoal } from "../backend";
import { replaceSettings, useStore } from "../store";
import { ErrorRow, Info, PLUGIN_NAME } from "../ui";

const GOALS = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8];
const LONGEST = 24;
const FLOORS = [30, 36, 40, 45, 48, 60];

export function hours(h: number | null | undefined): string {
  if (h == null) return "–";
  const total = Math.max(0, Math.round(h * 60));
  const hh = Math.floor(total / 60);
  const mm = total % 60;
  return hh ? (mm ? `${hh} h ${mm} min` : `${hh} h`) : `${mm} min`;
}

const STATES: Record<string, string> = {
  starting: "starting",
  measuring: "measuring what the game draws",
  settling: "checking the new setting",
  cutting: "over budget – lowering the power limit",
  stepping_down: "the game cannot keep its frames on this budget – fewer frames",
  stepping_up: "battery to spare – more frames again",
  adding: "battery to spare – more power",
  holding: "on track",
  on_track: "on track",
  short: "out of reach even at your lowest frame rate – making the battery last as long as it can",
  floor: "holding your lowest frame rate – it comes before the goal",
  reached: "goal reached – everything is back to your own settings",
};

const FG_WHY: Record<string, string> = {
  off: "Off: only the power limit and the frame cap are used.",
  no_cap: "Needs a Smooth frame rate for this game (above), which it then lowers with frame generation on top.",
  shortcut: "Not for games added to Steam by hand.",
  no_suite:
    "Needs the Frame Suite plugin with lsfg-vk set up (Lossless Scaling installed) and its \"Let the Legion Go Toolbox use lsfg-vk\" switch on.",
  fixed_off: "Smooth mode's Frame generation is fixed to Off for this game. Set it to Auto to allow this.",
  preparing: "Frame Suite is preparing lsfg-vk for this game…",
  refused: "Frame Suite did not allow it for this game (its page for the game says why).",
  mako:
    "MAKO's adaptive frame generation already trades real for generated frames as the power limit comes down, so only the power limit is used.",
  next_start:
    "Ready from the next start of this game: lsfg-vk only picks up a game when it starts. Until then the frame cap steps down on its own.",
};

/** What the plan is doing right now, in words. */
function doing(st: PlaytimeStatus, userCap: number | null): string {
  const parts: string[] = [];
  if (st.ceiling != null) parts.push(`power limit ${st.ceiling} W`);
  if (st.cap != null && st.fg && st.fg > 1) parts.push(`${st.cap} fps × ${st.fg} frame generation = ${st.cap * st.fg} on screen`);
  else if (st.cap != null) parts.push(`frame cap ${st.cap} fps${userCap ? ` (yours: ${userCap})` : ""}`);
  else if (userCap) parts.push(`your ${userCap} fps cap`);
  return parts.join(" · ") || "your own settings";
}

/** Battery playtime: a goal of hours per game on battery. */
export const PlaytimeSection: FC = () => {
  const { state } = useStore();
  const working = useRef(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (!state) return null;
  const { caps, settings, status } = state;
  const st = status.playtime;
  const app = status.app;
  const batt = status.battery.info;
  if (!st || !batt) return null;
  const key = app.id != null ? String(app.id) : null;
  const goal = key ? settings.playtime?.games?.[key] : undefined;
  const name = app.name || "this game";
  const userCap = key ? settings.smooth?.games?.[key]?.fps ?? null : null;

  const apply = async (hoursWanted: number | null, floor: number, allowFg: boolean) => {
    if (app.id == null || working.current) return;
    working.current = true;
    setProblem(null);
    try {
      const powerWasOff = !settings.power.enabled;
      // The backend switches power management on with a goal: the goal works through the power limit.
      replaceSettings(await setPlaytimeGoal(app.id, hoursWanted, floor, allowFg, app.name || ""));
      if (hoursWanted != null && powerWasOff)
        toaster.toast({ title: PLUGIN_NAME, body: "Power management is on now: the battery goal sets the power limit." });
      if (hoursWanted != null && goal?.hours !== hoursWanted)
        toaster.toast({
          title: PLUGIN_NAME,
          body:
            hoursWanted >= LONGEST
              ? `${name}: making the battery last as long as possible, from now.`
              : `${name}: ${hours(hoursWanted)} on battery, counted from now.`,
        });
    } catch (e) {
      setProblem(`${e instanceof Error ? e.message : e}`);
    } finally {
      working.current = false;
    }
  };

  const goalLabel = (h: number) => {
    if (h >= LONGEST) return st.max_h != null ? `As long as possible · about ${hours(st.max_h)}` : "As long as possible";
    if (st.max_h == null) return hours(h);
    return st.max_h >= h * 0.97 ? `${hours(h)} · within reach` : `${hours(h)} · beyond this battery`;
  };
  const goalChoices = goal && !GOALS.includes(goal.hours) && goal.hours < LONGEST ? [...GOALS, goal.hours].sort((a, b) => a - b) : GOALS;

  const nowLine = !st.on_battery
    ? `${batt.percent}% · on the charger: the goal waits until you unplug`
    : [
        `${batt.percent}%`,
        st.draw_w != null ? `${st.draw_w.toFixed(1)} W` : batt.watts != null ? `${batt.watts.toFixed(1)} W` : null,
        st.now_h != null ? `about ${hours(st.now_h)} at this rate` : null,
      ]
        .filter(Boolean)
        .join(" · ");

  const goalLine = () => {
    if (!goal || !st.goal) return null;
    if (goal.hours >= LONGEST) return `Using as little as your lowest frame rate allows · ${STATES[st.state ?? ""] ?? "waiting for battery"}`;
    const left = st.left_h != null ? `${hours(st.left_h)} to go` : null;
    const budget = st.budget_w != null && st.draw_w != null ? `budget ${st.budget_w.toFixed(1)} W, drawing ${st.draw_w.toFixed(1)} W` : null;
    return [left, budget, st.state ? STATES[st.state] ?? st.state : !st.on_battery ? "paused on the charger" : null]
      .filter(Boolean)
      .join(" · ");
  };

  const fgReady = st.fg_why == null && st.steps.some(([, fg]) => fg != null && fg > 1);
  const fgDescription = goal
    ? fgReady
      ? `Ready: when the budget needs it, the game makes half the frames and lsfg-vk doubles them, so the screen still shows ${userCap ?? "the cap"}. Switched on and off by Frame Suite while you play.`
      : FG_WHY[st.fg_why ?? ""] ?? "Not needed: frame generation is already on for this game."
    : "";

  return (
    <PanelSection>
      <Info label="Now">{nowLine}</Info>
      {app.id == null ? (
        <Info label="Start a game">The goal is set per game while it runs. The longest this battery lasts is shown then.</Info>
      ) : (
        <>
          <Info label={`Longest for ${name}`}>
            {st.max_h != null
              ? `about ${hours(st.max_h)} from ${batt.percent}% at ${goal?.floor ?? 30} fps – an estimate that gets better the more you play on battery`
              : st.on_battery
                ? "measuring – play a minute on battery"
                : "shown on battery"}
          </Info>
          <PanelSectionRow>
            <DropdownItem
              label="Goal"
              description={
                goal
                  ? "Counted while this game runs on battery, from when you chose it. Charging in between starts the count again."
                  : `How long ${name} should last on battery from now. The power limit, then the frame rate, are lowered just as far as needed – never below your lowest frame rate.`
              }
              rgOptions={[
                { data: 0, label: "Off" },
                ...goalChoices.map((h) => ({ data: h, label: goalLabel(h) })),
                { data: LONGEST, label: goalLabel(LONGEST) },
              ]}
              selectedOption={goal ? goal.hours : 0}
              onChange={(o) =>
                void apply((o.data as number) || null, goal?.floor ?? 30, goal?.allow_fg ?? true)
              }
            />
          </PanelSectionRow>
          {goal && (
            <>
              <Info label="Goal" warn={goal.hours < LONGEST && (st.reachable === false || st.state === "short")}>
                {goalLine()}
              </Info>
              {st.ceiling != null && <Info label="Doing">{doing(st, userCap)}</Info>}
              {st.reachable === false && goal.hours < LONGEST && (
                <Info label="Out of reach" warn>
                  At {goal.floor} fps this battery lasts about {hours(st.max_h)}. A lower frame rate, a lower screen
                  brightness or switching off Wi-Fi and the controllers' lights stretch it further.
                </Info>
              )}
              {!st.power_enabled && <Info label="Power" warn>Turn on Manage power above: the goal works through the power limit.</Info>}
              {st.fg_why === "no_cap" && (
                <Info label="Tip">
                  Choose a Smooth frame rate for this game above. Without one only the power limit is lowered, and the
                  game's frame rate falls unevenly instead of stepping to an even cap.
                </Info>
              )}
              <PanelSectionRow>
                <DropdownItem
                  label="Lowest frame rate"
                  description="The game never makes fewer frames than this. Frame generation can double them on screen."
                  rgOptions={FLOORS.map((f) => ({ data: f, label: `${f} fps` }))}
                  selectedOption={goal.floor}
                  onChange={(o) => void apply(goal.hours, o.data as number, goal.allow_fg)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField
                  label="Frame generation for battery time"
                  description={fgDescription}
                  checked={goal.allow_fg}
                  onChange={(v) => void apply(goal.hours, goal.floor, v)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  description={`Played ${hours(goal.played_s / 3600)} of ${goal.hours >= LONGEST ? "the battery" : hours(goal.hours)} so far.`}
                  onClick={async () => replaceSettings(await restartPlaytime(app.id as number))}
                >
                  Count from now again
                </ButtonItem>
              </PanelSectionRow>
              <Info label="Screen">The screen alone draws several watts: lower brightness gives the game more of the budget.</Info>
            </>
          )}
          {!caps.power.available && <Info label="Power" warn>This system offers no power limit, so the goal cannot be kept.</Info>}
        </>
      )}
      <ErrorRow message={problem ?? st.error ?? undefined} />
    </PanelSection>
  );
};
