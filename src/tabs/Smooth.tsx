import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, useEffect, useRef, useState } from "react";

import { setSmoothGame, smoothPlan } from "../backend";
import {
  addPrefix,
  hasPrefix,
  readLaunchOptions,
  removePrefix,
  writeLaunchOptions,
} from "../launchOptions";
import { replaceSettings, useStore } from "../store";
import { ErrorRow, Info, PLUGIN_NAME, Unavailable } from "../ui";

const OFF = 0;
const FG_AUTO = 0;
const FG_CHOICES = [FG_AUTO, 1, 2, 3, 4];
// The same caps as Auto TDP's target list.
const CAPS = [30, 40, 45, 50, 60, 72, 90, 100, 120, 144];

function refreshFor(fps: number, rates: number[]): number | null {
  const sorted = [...rates].sort((a, b) => b - a);
  return sorted.find((r) => r % fps === 0) ?? null;
}

/** Smooth frame rate per game: an even frame cap plus the matching refresh rate. */
export const SmoothSection: FC = () => {
  const { state } = useStore();
  // Not "disabled" while busy: disabling the focused control makes Steam
  // move focus (and the scroll position) back to the top of the tab.
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [wiped, setWiped] = useState(false);
  const app0 = state?.status.app.id ?? null;
  const entry0 = app0 != null ? state?.settings.smooth?.games?.[String(app0)] : undefined;
  // Another tool (Decky-Framegen, Steam ROM Manager, ...) may have replaced
  // the launch options since the cap was added: check when the game runs.
  useEffect(() => {
    let alive = true;
    setWiped(false);
    if (app0 == null || !entry0) return;
    readLaunchOptions(app0)
      .then((o) => alive && setWiped(!hasPrefix(o, entry0.prefix)))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [app0, entry0?.prefix, busy]);
  if (!state) return null;
  const { caps, settings, status } = state;
  const st = status.smooth;
  const games = settings.smooth?.games ?? {};
  const app = status.app;
  const appKey = app.id != null ? String(app.id) : null;
  const current = appKey ? games[appKey] : undefined;

  /** Change one game's cap: launch options first, then the plugin's record. */
  const apply = async (appId: number, name: string, fps: number) => {
    const fg = games[String(appId)]?.fg ?? FG_AUTO;
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setProblem(null);
    try {
      const entry = games[String(appId)];
      let options = await readLaunchOptions(appId);
      if (entry) options = removePrefix(options, entry.prefix, entry.added_command);
      if (fps === OFF) {
        await writeLaunchOptions(appId, options);
        replaceSettings(await setSmoothGame(appId, null, name, "", false, FG_AUTO));
      } else {
        const plan = await smoothPlan(fps);
        const next = addPrefix(options, plan.prefix);
        await writeLaunchOptions(appId, next.value);
        replaceSettings(
          await setSmoothGame(appId, fps, name, plan.prefix, next.addedCommand, fg),
        );
      }
      toaster.toast({
        title: PLUGIN_NAME,
        body:
          fps === OFF
            ? `Smooth mode off for ${name}. Restart the game to remove the cap.`
            : `${name}: ${fps} fps. Restart the game for the cap to apply.`,
      });
    } catch (e) {
      setProblem(`${e instanceof Error ? e.message : e}`);
    } finally {
      working.current = false;
      setBusy(false);
    }
  };

  /** Frame generation changes only the screen rate and Auto TDP's aim; the
   *  game's own cap (and so its launch options) stays as it is. */
  const applyFg = async (appId: number, name: string, fg: number) => {
    const entry = games[String(appId)];
    if (!entry || working.current) return;
    working.current = true;
    setBusy(true);
    setProblem(null);
    try {
      replaceSettings(
        await setSmoothGame(appId, entry.fps, name, entry.prefix, entry.added_command, fg),
      );
      toaster.toast({
        title: PLUGIN_NAME,
        body:
          fg === FG_AUTO
            ? `${name}: frame generation follows lsfg-vk's setting for this game.`
            : fg > 1
              ? `${name}: ${entry.fps} fps × ${fg} = ${entry.fps * fg} fps on screen. Set ${fg}× in lsfg-vk too.`
              : `${name}: no frame generation, ${entry.fps} fps on screen.`,
      });
    } catch (e) {
      setProblem(`${e instanceof Error ? e.message : e}`);
    } finally {
      working.current = false;
      setBusy(false);
    }
  };

  if (!caps.smooth?.available && Object.keys(games).length === 0) {
    return (
      <PanelSection title="Smooth frame rate">
        <Unavailable cap={caps.smooth} what="Smooth mode" />
      </PanelSection>
    );
  }

  const rates = st?.rates ?? [];
  const vrr = !!st?.vrr;
  const choices =
    current && !CAPS.includes(current.fps)
      ? [...CAPS, current.fps].sort((a, b) => a - b)
      : CAPS;
  // Even: a refresh rate the cap divides, so every frame stays on screen
  // equally long. Otherwise some frames stay longer (judder) unless the
  // screen has variable refresh (VRR).
  // With frame generation the screen shows f × fg frames, so evenness is
  // judged on that number.
  const label = (f: number, fg = 1) => {
    const out = f * fg;
    const name = fg > 1 ? `${f} → ${out} fps` : `${f} fps`;
    const r = refreshFor(out, rates);
    if (r) return `${name} · screen ${r} Hz`;
    if (vrr) return `${name} · VRR`;
    // Not divisible: the screen goes to its highest rate (as even as it gets).
    return rates.length ? `${name} · screen ${Math.max(...rates)} Hz, uneven` : name;
  };
  // Multiplier in effect (with Auto: what lsfg-vk is set to for this game).
  const fg = current ? (st?.fg ?? 1) : 1;
  const fgSetting = current?.fg ?? FG_AUTO;
  const out = current ? current.fps * fg : 0;
  const lsfg = st?.lsfg ?? null;
  const lsfgMult = lsfg?.installed ? lsfg.multiplier : 1;
  const autoLabel = (f: number) =>
    !lsfg?.installed
      ? "Auto · lsfg-vk not installed"
      : lsfgMult > 1
        ? `Auto · lsfg-vk ${lsfgMult}× · ${label(f, lsfgMult)}`
        : "Auto · lsfg-vk off for this game";
  const fgDescription = (): string => {
    if (!current) return "";
    if (lsfg?.error) return `Could not read lsfg-vk's settings (${lsfg.error}). Pick the multiplier by hand.`;
    if (fgSetting === FG_AUTO) {
      if (!lsfg?.installed) return "Follows lsfg-vk's setting for this game once lsfg-vk is installed. Nothing to do without frame generation.";
      if (lsfgMult > 1)
        return `Follows lsfg-vk (profile "${lsfg.profile}"): the game makes ${current.fps} fps, the screen shows ${out}. Auto TDP aims at ${out}. Changes in decky-lsfg-vk are picked up within seconds.`;
      return "Follows lsfg-vk: it has no profile for this game, so the screen shows the cap. Turn lsfg-vk on for the game in decky-lsfg-vk and this follows within seconds.";
    }
    if (lsfg?.installed && fgSetting !== lsfgMult)
      return `lsfg-vk is set to ${lsfgMult > 1 ? `${lsfgMult}×` : "off"} for this game, not ${fgSetting > 1 ? `${fgSetting}×` : "off"}. Choose Auto to follow it.`;
    return fgSetting > 1
      ? `Fixed: the game makes ${current.fps} fps, the screen shows ${out}. Auto TDP aims at ${out}.`
      : "Fixed off: the screen shows the cap, whatever lsfg-vk is set to.";
  };
  const measured = st?.measured;
  const saved = Object.entries(games).sort((a, b) => a[1].name.localeCompare(b[1].name));

  return (
    <PanelSection title="Smooth frame rate">
      {app.id != null ? (
        <PanelSectionRow>
          <DropdownItem
            label={app.name || "This game"}
            description={
              current && !refreshFor(out, rates) && !vrr && rates.length
                ? `${out} fps does not divide this screen's ${rates.join(" / ")} Hz, so some frames stay on screen longer. Caps marked with a screen rate are perfectly even.`
                : "Even frame pacing: an early frame limiter plus a screen refresh rate the cap divides evenly. Applies from the game's next start."
            }
                        rgOptions={[
              { data: OFF, label: "Off" },
              ...choices.map((f) => ({ data: f, label: label(f, fg) })),
            ]}
            selectedOption={current?.fps ?? OFF}
            onChange={(o) => void apply(app.id as number, app.name || "This game", o.data as number)}
          />
        </PanelSectionRow>
      ) : null}
      {app.id != null && current ? (
        <PanelSectionRow>
          <DropdownItem
            label="Frame generation"
            description={fgDescription()}
                        rgOptions={FG_CHOICES.map((m) => ({
              data: m,
              label:
                m === FG_AUTO
                  ? autoLabel(current.fps)
                  : m === 1
                    ? "Off"
                    : `${m}× · ${label(current.fps, m)}`,
            }))}
            selectedOption={fgSetting}
            onChange={(o) => void applyFg(app.id as number, app.name || "This game", o.data as number)}
          />
        </PanelSectionRow>
      ) : null}
      {current && lsfg?.base_cap ? (
        <Info label="Two frame limiters" warn>
          decky-lsfg-vk's Base FPS cap ({lsfg.base_cap}) is on for this game. Turn it off there:
          Smooth mode already caps the game at {current.fps}, and two limiters cause uneven frames.
        </Info>
      ) : null}
      {app.id == null && (
        <Info label="Start a game">Smooth mode is set per game while it runs.</Info>
      )}

      {current && wiped && (
        <>
          <Info label="Cap missing" warn>
            Another tool replaced this game's launch options (for example Decky-Framegen or Steam ROM
            Manager), so the {current.fps} fps cap is gone.
          </Info>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
                            onClick={() => void apply(app.id as number, app.name || "This game", current.fps)}
            >
              Add the cap again
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {current && (
        <>
          <Info label="Now">
            {measured?.fps != null
              ? `${measured.fps.toFixed(1)} fps · slowest frame ${measured.low != null ? measured.low.toFixed(0) : "–"} fps${
                  st?.refresh ? ` · screen ${st.refresh} Hz` : ""
                }`
              : status.power.auto.probe_error
                ? `No frame rate yet: ${status.power.auto.probe_error}`
                : "Waiting for the game to draw frames"}
          </Info>
          <Info label="For the smoothest result">
            Set Steam's Framerate limit (Performance menu) to off for this game, and turn off the
            game's own frame limiter and V-Sync. Two limiters at once cause uneven frames.
          </Info>
        </>
      )}
      <ErrorRow message={problem ?? status.errors.smooth} />

      {saved.length > 0 && (
        <>
          <PanelSectionRow>
            <Field
              label="Games with Smooth mode"
              description="Select one to turn it off for that game."
              padding="compact"
              bottomSeparator="none"
            />
          </PanelSectionRow>
          {saved.map(([key, g]) => (
            <PanelSectionRow key={key}>
              <ButtonItem
                layout="below"
                                description={label(g.fps, g.fg > 1 ? g.fg : 1)}
                onClick={() => void apply(Number(key), g.name || `App ${key}`, OFF)}
              >
                {g.name || `App ${key}`}
              </ButtonItem>
            </PanelSectionRow>
          ))}
        </>
      )}
    </PanelSection>
  );
};
