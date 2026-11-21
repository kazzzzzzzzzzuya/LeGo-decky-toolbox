import { Settings, setSmoothGame, smoothPlan } from "./backend";
import { addPrefix, hasPrefix, readLaunchOptions, removePrefix, writeLaunchOptions } from "./launchOptions";

export const OFF = 0;
export const FG_AUTO = 0;
// OptiScaler in the launch options: Decky-Framegen's wrapper, or the DLL
// override its direct patch (and Frame Suite) sets. Frame generation switched
// on in the game is then made inside the game.
export const FGMOD_RE =
  /(^|[\s/])fgmod(\s|$)|(^|\s)WINEDLLOVERRIDES=\S*\b(dxgi|winmm|version|dbghelp|winhttp|wininet|d3d12)=n,b/;

type Games = Settings["smooth"]["games"];

/** Set (or with OFF remove) one game's frame cap: launch options first, then the plugin's
 *  record. Returns the backend's settings and whether the new cap applies at once. */
export async function setCap(
  games: Games,
  appId: number,
  name: string,
  fps: number,
): Promise<{ settings: Settings; now: boolean }> {
  const entry = games[String(appId)];
  const fg = entry?.fg ?? FG_AUTO;
  const original = await readLaunchOptions(appId);
  const options = entry ? removePrefix(original, entry.prefix, entry.added_command) : original;
  const fgmod = FGMOD_RE.test(original);
  if (fps === OFF) {
    await writeLaunchOptions(appId, options);
    return { settings: await setSmoothGame(appId, null, name, "", false, FG_AUTO, false), now: false };
  }
  const plan = await smoothPlan(fps, appId);
  if (entry && plan.live && entry.prefix === plan.prefix && hasPrefix(original, plan.prefix)) {
    // Live cap file: the launch options stay as they are.
    return {
      settings: await setSmoothGame(appId, fps, name, plan.prefix, entry.added_command, fg, fgmod),
      now: true,
    };
  }
  const next = addPrefix(options, plan.prefix);
  await writeLaunchOptions(appId, next.value);
  return {
    settings: await setSmoothGame(appId, fps, name, plan.prefix, next.addedCommand, fg, fgmod),
    now: false,
  };
}
