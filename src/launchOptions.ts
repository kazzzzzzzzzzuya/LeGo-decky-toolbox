// Read and change a game's Steam launch options (the same Steam client API
// decky-lsfg-vk uses). Every write is read back to make sure Steam took it.

interface AppDetails {
  strLaunchOptions?: string;
  strShortcutLaunchOptions?: string;
}
interface Registration {
  unregister: () => void;
}
interface SteamApps {
  RegisterForAppDetails: (appId: number, cb: (d: AppDetails) => void) => Registration;
  SetAppLaunchOptions: (appId: number, options: string) => void | Promise<void>;
  SetShortcutLaunchOptions: (appId: number, options: string) => void | Promise<void>;
}

const COMMAND = "%command%";

function apps(): Partial<SteamApps> | undefined {
  return (window as unknown as { SteamClient?: { Apps?: Partial<SteamApps> } }).SteamClient?.Apps;
}

/** Non-Steam shortcuts have app ids with the top bit set. */
export const isShortcut = (appId: number) => appId >= 0x80000000;

export function readLaunchOptions(appId: number, timeoutMs = 4000): Promise<string> {
  return new Promise((resolve, reject) => {
    const register = apps()?.RegisterForAppDetails;
    if (!register) {
      reject(new Error("Steam's app details are not available"));
      return;
    }
    let reg: Registration | undefined;
    let done = false;
    const finish = (fn: () => void) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      setTimeout(() => {
        try {
          reg?.unregister();
        } catch {
          /* already gone */
        }
      }, 0);
      fn();
    };
    const timer = setTimeout(
      () => finish(() => reject(new Error("Steam did not report the launch options"))),
      timeoutMs,
    );
    reg = register.call(apps(), appId, (d: AppDetails) => {
      if (!d) return;
      const value = isShortcut(appId) ? d.strShortcutLaunchOptions : d.strLaunchOptions;
      finish(() => resolve(value ?? ""));
    });
  });
}

export async function writeLaunchOptions(appId: number, value: string): Promise<void> {
  const a = apps();
  const setter = isShortcut(appId) ? a?.SetShortcutLaunchOptions : a?.SetAppLaunchOptions;
  if (!setter) throw new Error("Steam's launch options API is not available");
  await Promise.resolve(setter.call(a, appId, value));
  for (let i = 0; i < 10; i++) {
    if ((await readLaunchOptions(appId)).trim() === value.trim()) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("Steam did not accept the new launch options");
}

const OWN_LIMITERS = /(^|\s)(MANGOHUD_CONFIG|DXVK_FRAME_RATE)=/;

/**
 * Add `prefix` (environment settings) at the very start of the options.
 * Settings have to come before any wrapper command - lsfg-vk's `~/lsfg`,
 * `gamemoderun`, `mangohud` and the like - or the shell passes them to the
 * wrapper as arguments. %command% is added when missing.
 */
export function addPrefix(options: string, prefix: string): { value: string; addedCommand: boolean } {
  const trimmed = options.trim();
  if (OWN_LIMITERS.test(trimmed)) {
    throw new Error(
      "This game's launch options already set a frame limiter (MANGOHUD_CONFIG or DXVK_FRAME_RATE, e.g. from lsfg-vk). Remove it there first.",
    );
  }
  if (trimmed.includes(COMMAND)) {
    return { value: `${prefix} ${trimmed}`, addedCommand: false };
  }
  // Without %command% the existing options are arguments for the game.
  return { value: `${prefix} ${COMMAND}${trimmed ? " " + trimmed : ""}`, addedCommand: true };
}

/**
 * Undo addPrefix: remove each setting it added (the first time it appears,
 * wherever another tool moved it), leaving everything else as it was.
 */
export function removePrefix(options: string, prefix: string, addedCommand: boolean): string {
  const words = options.trim().split(/\s+/).filter(Boolean);
  for (const token of prefix.split(/\s+/).filter(Boolean)) {
    const at = words.indexOf(token);
    if (at >= 0) words.splice(at, 1);
  }
  if (addedCommand && words[0] === COMMAND) words.shift();
  return words.join(" ");
}
