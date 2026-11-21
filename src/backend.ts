import { callable } from "@decky/api";

import type {
  CalibrationResult,
  GyroPatch,
  GyroSettings,
  GyroStatus,
  SlotName,
} from "./gyro_types";

export type StickMode = "solid" | "pulse" | "rainbow" | "spiral";
export type RemapButton = "Y1" | "Y2" | "Y3" | "M2" | "M3";

export interface PowerProfile {
  /** "custom" (TDP slider) or one of the device's own power modes. */
  mode: string;
  tdp: number;
  auto: boolean;
  target_fps: number;
  min_tdp: number;
}

export interface PlaytimeGoal {
  hours: number;
  /** Fewest frames the game itself may make. */
  floor: number;
  allow_fg: boolean;
  name: string;
  played_s: number;
  last_pct: number | null;
}

export interface PlaytimeStatus {
  app: number | null;
  goal: PlaytimeGoal | null;
  draw_w: number | null;
  budget_w: number | null;
  /** Hours left at the current draw, the longest this game can reach, and the goal's hours to go. */
  now_h: number | null;
  max_h: number | null;
  left_h: number | null;
  reachable: boolean | null;
  state: string | null;
  step: number | null;
  ceiling: number | null;
  cap: number | null;
  fg: number | null;
  /** Why frame generation is not among the steps (null: it is, or not needed). */
  fg_why: string | null;
  steps: [number | null, number | null][];
  on_battery: boolean;
  power_enabled: boolean;
  error: string | null;
}

export interface FanProfile {
  full_speed: boolean;
  curve: number[];
  name: string;
}

export interface Settings {
  lighting: {
    sticks: {
      managed: boolean;
      on: boolean;
      mode: StickMode;
      color: [number, number, number];
      brightness: number;
      speed: number;
    };
    power_led: { managed: boolean; on: boolean; off_in_sleep: boolean };
  };
  battery: { charge_limit: boolean | null };
  /** Battery playtime per game (see playtime.py). */
  playtime: {
    games: Record<string, PlaytimeGoal>;
    learned: Record<string, Record<string, [number, boolean]>>;
  };
  smooth: {
    /** fps: the game's own cap; fg: frame generation (0 = follow lsfg-vk, 1 = none, 2-4 fixed). */
    games: Record<
      string,
      {
        fps: number;
        fg: number;
        name: string;
        prefix: string;
        added_command: boolean;
        fgmod?: boolean;
      }
    >;
  };
  fan: {
    enabled: boolean;
    per_game: boolean;
    per_power: boolean;
    /** "default", "default:ac", "<appid>", "<appid>:ac" */
    profiles: Record<string, FanProfile>;
  };
  power: {
    enabled: boolean;
    per_game: boolean;
    cpu_boost: boolean | null;
    profiles: Record<string, PowerProfile>;
    learned?: Record<string, { tdp: number; target: number }>;
  };
  controls: {
    swap_menu: boolean;
    swap_layout: "steam_menu" | "steam_view" | "lview_steam_menu" | "lmenu_steam_view";
    /** "deck-uhid" (default), "xbox" (no gyro in Steam), "ds5-edge" or "ds5". */
    steam_controller: string;
    /** Games with their own controller type, by app id. */
    steam_controller_games: Record<string, { type: string; name: string }>;
    remap_managed: boolean;
    remap: Record<RemapButton, string>;
    touchpad: boolean | null;
  };
}

type DeepPartial<T> = T extends (infer U)[]
  ? U[]
  : T extends object
    ? { [K in keyof T]?: DeepPartial<T[K]> }
    : T;
export type SettingsPatch = DeepPartial<Settings>;

export interface Capability {
  available: boolean;
  reason: string | null;
}
export type CapName =
  | "power"
  | "fps"
  | "fan"
  | "charge_limit"
  | "power_led"
  | "sticks"
  | "remap"
  | "swap_menu"
  | "steam_gyro"
  | "smooth";
export type Caps = Record<CapName, Capability> & {
  steam_gyro: Capability & { types: string[] };
};

export interface HubStatus {
  /** Frame rate from just before the panel opened (the menu slows MAKO and the game down). */
  fps_before_menu?: number | null;
  /** Battery draw once a minute, oldest first (null while charging). */
  watts_history?: (number | null)[];
  model: string;
  errors: Record<string, string>;
  app: { id: number | null; name: string };
  /** The acpi_call kernel module and its on-device build (null: not a Legion Go). */
  acpi: {
    available: boolean;
    built: boolean;
    kernel_changed: boolean;
    running: boolean;
    done: boolean;
    step: string | null;
    error: string | null;
    log: string[];
  } | null;
  steam_controller: { type: string; source: "game" | "default" };
  smooth: {
    fps: number | null;
    /** Frame-generation multiplier in effect, the game's setting (0 =
     *  follow lsfg-vk), lsfg-vk's own settings, and the frames on screen. */
    fg: number;
    fg_setting: number;
    /** OptiScaler is set up for the game (Decky-Framegen or Frame Suite). */
    fgmod: boolean;
    /** What the Frame Suite plugin recorded for the game, if it is installed. */
    suite: SuiteInfo | null;
    mako: MakoInfo | null;
    /** MAKO holds this rate on screen by itself (adaptive, frame generation on Auto), else null. */
    mako_adaptive: number | null;
    /** Frames on screen after a variable-refresh screen's cap. */
    shown: number | null;
    lsfg: LsfgInfo | null;
    output: number | null;
    refresh: number | null;
    rates: number[];
    vrr: boolean;
    choices: number[];
    active: boolean;
    measured: { fps: number | null; low: number | null } | null;
  };
  power: {
    profile_key: string;
    mode: string | null;
    modes: string[];
    tdp: number | null;
    range: [number, number] | null;
    cpu_boost: boolean | null;
    auto: {
      active: boolean;
      state: string | null;
      fps: number | null;
      low: number | null;
      target: number | null;
      frame_gen?: boolean;
      /** Watts Auto TDP settled at for this game before (this power source). */
      learned: number | null;
      probe_error: string | null;
    };
  };
  fan: {
    temp: number | null;
    rpm: number | null;
    /** How often the plugin had to put the fan setting back. */
    restores: number;
    restored_ago: number | null;
    /** The fan profile in use and whether a charger is connected. */
    profile_key: string;
    on_ac: boolean;
  };
  battery: {
    info: {
      percent: number;
      status: string;
      watts: number | null;
      minutes: number | null;
      energy_wh?: number | null;
      full_wh?: number | null;
    } | null;
    charge_limit: boolean | null;
    backend: string | null;
  };
  power_led: boolean | null;
  swap_menu: { active: boolean };
  playtime: PlaytimeStatus;
}

export interface State {
  version: string;
  /** When settings were restored from the backup at start (none found), else null. */
  restored_backup?: string | null;
  caps: Caps;
  settings: Settings;
  status: HubStatus;
  gyro: { settings: GyroSettings; defaults: GyroSettings; status: GyroStatus };
}

export const getState = callable<[], State>("get_state");
export const getStatus = callable<[], { hub: HubStatus; gyro: GyroStatus }>("get_status");
export const updateSettings = callable<[patch: SettingsPatch], Settings>("update_settings");
export const resetSettings = callable<[], Settings>("reset_settings");
export const deletePowerProfile = callable<[key: string], Settings>("delete_power_profile");
export const setRunningApp = callable<[appId: number | null, name: string], void>(
  "set_running_app",
);
export interface SuiteInfo {
  /** Frame Suite's bridge file exists. */
  present: boolean;
  /** OptiScaler is in the game's files. */
  optiscaler: boolean;
  /** The game's own frame generation as Frame Suite was told (1 = off). */
  multiplier: number;
  route: "optiscaler" | "lsfg" | "mako" | null;
  error: string | null;
  /** MAKO's frame generation for the game (Frame Suite bundles MAKO), or null. */
  mako?: MakoInfo | null;
}

export interface MakoInfo {
  enabled: boolean;
  /** Adaptive: the screen holds target_fps, MAKO generating up to max_multiplier times. */
  adaptive: boolean;
  target_fps: number;
  max_multiplier: number;
  multiplier: number;
}

export interface LsfgInfo {
  installed: boolean;
  multiplier: number;
  profile: string | null;
  /** decky-lsfg-vk's "Base FPS cap" for the game (0 = off). */
  base_cap: number;
  error: string | null;
}

export const smoothPlan = callable<
  [fps: number, appId: number],
  { prefix: string; limiter: string; live: boolean }
>(
  "smooth_plan",
);
export const setSmoothGame = callable<
  [
    appId: number,
    fps: number | null,
    name: string,
    prefix: string,
    addedCommand: boolean,
    fg: number,
    fgmod: boolean,
  ],
  Settings
>("set_smooth_game");
export interface Release { version: string; url: string; sha256: string; published: string | null; notes: string }
export interface Updates {
  ok: boolean; error?: string; current: string; latest?: string; newer?: boolean; releases: Release[];
}
export const checkUpdates = callable<[force: boolean], Updates>("check_updates");
export const setPlaytimeGoal = callable<
  [appId: number, hours: number | null, floor: number, allowFg: boolean, name: string],
  Settings
>("set_playtime_goal");
export const restartPlaytime = callable<[appId: number], Settings>("restart_playtime");
export const acpiInstallStart = callable<[], boolean>("acpi_install_start");
export interface BackupInfo {
  path: string;
  exists: boolean;
  saved_at: string | null;
  version: string | null;
  error?: string | null;
}
export const backupInfo = callable<[], BackupInfo>("backup_info");
export const backupSettings = callable<[], BackupInfo>("backup_settings");
export const restoreSettings = callable<
  [],
  { ok: boolean; error: string | null; settings?: Settings; gyro?: GyroSettings }
>("restore_settings");
export const deleteFanProfile = callable<[key: string], Settings>("delete_fan_profile");
export const setGameController = callable<
  [appId: number, kind: string | null, name: string],
  Settings
>("set_game_controller");
export const onSuspend = callable<[], void>("on_suspend");
export const onResume = callable<[], void>("on_resume");

export const gyroSetSettings = callable<[patch: GyroPatch], GyroSettings>("gyro_set_settings");
export const gyroResetSettings = callable<[], GyroSettings>("gyro_reset_settings");
export const gyroCalibrate = callable<[target: SlotName], CalibrationResult>("gyro_calibrate");
export const gyroCalibrateAll = callable<[], Record<string, CalibrationResult>>(
  "gyro_calibrate_all",
);

// ---- System tab: speaker EQ, sleep guard, Steam update check ----
export interface SystemSettings {
  eq: { enabled: boolean; preset: string; bass: number; treble: number };
  sleep: { poweroff: boolean; hours: number; battery_only: boolean };
}
export interface SleepEntry {
  start: number;
  end: number;
  hours: number;
  pct_before: number | null;
  pct_after: number | null;
  drain_ph: number | null;
  ac: boolean | null;
  powered_off?: boolean;
}
export interface SteamItem { id: string; label: string; ok: boolean; detail: string; installed: boolean }
export interface SteamResult {
  overall: "ok" | "fail" | "idle";
  items: SteamItem[];
  version?: number | null;
  last_good?: number | null;
  good_at?: string | null;
  updated_since_good?: boolean;
  hold?: { held: boolean; foreign: boolean };
  checked_at?: string;
  error?: string;
}
export interface SystemState {
  settings: SystemSettings;
  eq: {
    available: boolean;
    reason: string | null;
    state: "off" | "starting" | "on" | "headphones" | "other" | "other_effect" | "failed";
    error: string | null;
    speaker: string | null;
    others: string[];
    presets: { id: string; label: string }[];
  };
  sleep: {
    available: boolean;
    alarm_at: number | null;
    last: SleepEntry | null;
    history: SleepEntry[];
    average_ph: number | null;
    counted: number;
    hours_choices: number[];
  };
  steam: SteamResult | null;
}
export interface SteamSnapshot { name: string; created: string; reason: string; steam: number | null; files: string[] }
export const systemState = callable<[], SystemState>("system_state");
export const systemUpdate = callable<[patch: DeepPartial<SystemSettings>], SystemState>("system_update");
export const steamCheck = callable<[], SystemState>("steam_check");
export const steamSnapshots = callable<[], SteamSnapshot[]>("steam_snapshots");
export const steamSnapshotNow = callable<[], { ok: boolean; name: string | null; error: string | null }>(
  "steam_snapshot_now",
);
export const steamRestore = callable<[name: string], { ok: boolean; restored: string[]; error: string | null }>(
  "steam_restore",
);
export const steamHold = callable<[on: boolean], { ok: boolean; error: string | null }>("steam_hold");
export const sleepClear = callable<[], SystemState>("sleep_clear");

// ---- Game tab: one mode per game ----
export type ModeId = "battery" | "balanced" | "smooth";
export interface ModeInfo {
  mode: ModeId | null;
  /** Hours a full battery lasts in each mode for this game, learned while it ran in it (null: not yet). */
  hours: Partial<Record<ModeId, number | null>>;
}
export const setMode = callable<[appId: number, name: string, mode: ModeId | null], ModeInfo>("set_mode");
export const modeInfo = callable<[appId: number | null], ModeInfo>("mode_info");
export const menuState = callable<[open: boolean], void>("menu");
