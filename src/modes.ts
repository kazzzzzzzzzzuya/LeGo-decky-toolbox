import { toaster } from "@decky/api";

import { ModeId, ModeInfo, setMode, State } from "./backend";
import { OFF, setCap } from "./cap";
import { currentState, flushWrites, replaceSettings, update } from "./store";
import { PRESETS as FAN_PRESETS } from "./tabs/Fan";
import { PLUGIN_NAME } from "./ui";

/** The Game tab's three ways to run a game. Each sets the game's own power profile
 *  (Auto TDP between min and max watts for a target), its frame cap, its fan curve (only
 *  while the custom fan curve is on) and, for Smoothest, asks Frame Suite to Boost it. */
export interface Mode {
  id: ModeId;
  label: string;
  line: string;
  cap: number | null;      // frame cap; null: none (frame generation sets the rate)
  target: number;          // Auto TDP's frame-rate target
  minW: number;
  maxW: number;
  fan: "silent" | "balanced" | "performance";
  boost: boolean;
}

// 36 instead of 40: it divides the 144 Hz screen evenly (as the Smooth list does).
export const MODES: Mode[] = [
  { id: "battery", label: "Longest battery", line: "36 fps, low power, silent", cap: 36, target: 36, minW: 5, maxW: 12, fan: "silent", boost: false },
  { id: "balanced", label: "Balanced", line: "Steady 60 fps, quiet", cap: 60, target: 60, minW: 8, maxW: 20, fan: "balanced", boost: false },
  { id: "smooth", label: "Smoothest", line: "More frames with frame generation", cap: null, target: 60, minW: 10, maxW: 25, fan: "performance", boost: true },
];
export const modeById = (id: ModeId | null | undefined) => MODES.find((m) => m.id === id) ?? null;

const FAN_WORD = { silent: "silent fan", balanced: "quiet fan", performance: "cooler fan" };

/** What a mode sets, in words, for this device. */
export function modeSets(m: Mode, st: State): string[] {
  const [lo, hi] = clampW(m, st);
  const out = [
    m.cap ? `${m.cap} fps cap` : "no cap",
    `power ${lo}–${hi} W, automatic`,
    st.settings.fan.enabled && st.caps.fan.available ? FAN_WORD[m.fan] : "fan by the firmware",
  ];
  if (m.boost) out.push(st.status.smooth?.suite?.present ? "frame generation by Frame Suite" : "frame generation needs Frame Suite");
  else out.push("frame generation off");
  return out;
}

function clampW(m: Mode, st: State): [number, number] {
  const r = st.status.power.range;
  if (!r) return [m.minW, m.maxW];
  const hi = Math.max(r[0], Math.min(r[1], m.maxW));
  return [Math.max(r[0], Math.min(hi, m.minW)), hi];
}

/** Apply a mode to a game. Power and fan first (they take effect at once), then the frame cap
 *  (launch options), then the record that asks Frame Suite for Boost. */
export async function applyMode(appId: number, name: string, m: Mode): Promise<ModeInfo | null> {
  const st = currentState();
  if (!st) return null;
  const key = String(appId);
  const notes: string[] = [];
  if (st.caps.power.available) {
    const [lo, hi] = clampW(m, st);
    update({
      power: {
        enabled: true,
        per_game: true,
        profiles: { [key]: { mode: "custom", tdp: hi, auto: true, target_fps: m.target, min_tdp: lo } },
      },
    });
  }
  if (st.settings.fan.enabled && st.caps.fan.available) {
    const fan = { full_speed: false, curve: FAN_PRESETS[m.fan].slice(), name };
    update({ fan: { per_game: true, profiles: st.settings.fan.per_power ? { [key]: fan, [`${key}:ac`]: fan } : { [key]: fan } } });
  }
  flushWrites();
  const games = st.settings.smooth?.games ?? {};
  const want = m.cap ?? OFF;
  const have = games[key]?.fps ?? OFF;
  if (want !== have) {
    try {
      const res = await setCap(games, appId, name, want);
      replaceSettings(res.settings);
      if (want !== OFF && !res.now) notes.push("Restart the game once for the frame cap.");
    } catch (e) {
      notes.push(`The frame cap could not be set: ${e instanceof Error ? e.message : e}`);
    }
  }
  if (m.boost) {
    notes.push(
      st.status.smooth?.suite?.present
        ? "Frame Suite turns frame generation on in a few seconds; it starts with the game's next start."
        : "Install Frame Suite for frame generation.",
    );
  }
  let info: ModeInfo | null = null;
  try {
    info = await setMode(appId, name, m.id);
  } catch (e) {
    notes.push(`Not saved: ${e}`);
  }
  toaster.toast({ title: PLUGIN_NAME, body: `${name}: ${m.label}.${notes.length ? " " + notes.join(" ") : ""}` });
  return info;
}

/** "3:05" from hours. */
export function hm(h: number | null | undefined): string {
  if (h == null) return "–";
  const min = Math.round(h * 60);
  return `${Math.floor(min / 60)}:${String(min % 60).padStart(2, "0")}`;
}
