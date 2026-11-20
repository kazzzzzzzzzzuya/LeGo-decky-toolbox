import { ButtonItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, useEffect, useState } from "react";

import {
  acpiInstallStart,
  BackupInfo,
  backupInfo,
  backupSettings,
  resetSettings,
  restoreSettings,
} from "../backend";
import { replaceGyroSettings, replaceSettings, update, useStore } from "../store";
import { ErrorRow, Fold, Info, modeLabel, PLUGIN_NAME, Stat, Stats, Unavailable } from "../ui";
import { hours } from "./Playtime";
import { GuideSection, guideSeen } from "./Guide";
import { UpdateBanner, UpdateRows, useUpdates } from "./Updates";

const MODELS: Record<string, string> = {
  "83E1": "Legion Go",
  "83N0": "Legion Go 2",
  "83N1": "Legion Go 2",
  "83L3": "Legion Go S",
  "83N6": "Legion Go S",
};

const PADS: Record<string, string> = {
  "deck-uhid": "Steam Deck controller",
  xbox: "Xbox controller",
  "ds5-edge": "DualSense Edge",
  ds5: "DualSense",
};

function remembered(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(key);
    return v == null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

function duration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h} h ${m} min` : `${m} min`;
}

export const HomeTab: FC<{ go: (tab: string) => void }> = ({ go }) => {
  const { state, error } = useStore();
  const [guide, setGuide] = useState(() => !guideSeen());
  const [guideAgain, setGuideAgain] = useState(false);
  const [gameOpen, setGameOpen] = useState(() => remembered("lgo-home-game-open", true));
  const [backup, setBackup] = useState<BackupInfo | null>(null);
  const [backupNote, setBackupNote] = useState<string | null>(null);
  const [confirmRestore, setConfirmRestore] = useState(false);
  useEffect(() => {
    backupInfo().then(setBackup).catch(() => undefined);
  }, []);
  const [updates, checking, checkUpdates] = useUpdates();
  if (!state) return null;
  const { caps, settings, status, gyro } = state;
  const errors = status.errors;
  const batt = status.battery;

  const powerLine = () => {
    if (!caps.power.available) return "Not available on this system";
    if (!settings.power.enabled) return "Not managed";
    const st = status.power;
    const parts = [st.mode ? modeLabel(st.mode).replace(" (set the watts)", "") : "?"];
    if (st.mode === "custom" && st.tdp != null) parts.push(`${st.tdp} W`);
    if (st.auto.active) {
      parts.push(st.auto.fps != null ? `auto · ${Math.round(st.auto.fps)} fps` : "auto");
    }
    return parts.join(" · ");
  };

  const fanLine = () => {
    const temp = status.fan.temp != null ? `${status.fan.temp} °C` : null;
    const f = settings.fan;
    const key = status.fan.profile_key ?? "default";
    const p = f.profiles[key] ?? f.profiles.default;
    const mode = !caps.fan.available || !f.enabled
      ? "Firmware curve"
      : p.full_speed
        ? "Full speed"
        : "Custom curve";
    const which =
      f.enabled && key !== "default"
        ? key === "default:ac"
          ? "charger setting"
          : key.endsWith(":ac")
            ? "game's charger setting"
            : "game's setting"
        : null;
    return [mode, which, temp].filter(Boolean).join(" · ");
  };

  const lightsLine = () => {
    const s = settings.lighting.sticks;
    const sticks = !caps.sticks.available
      ? null
      : !s.managed
        ? "sticks unchanged"
        : s.on
          ? `sticks ${s.mode}`
          : "sticks off";
    const led =
      status.power_led == null ? null : status.power_led ? "power light on" : "power light off";
    return [sticks, led].filter(Boolean).join(" · ") || "Not available";
  };

  const controlsLine = () => {
    const c = settings.controls;
    const parts = [];
    if (c.swap_menu) {
      const what = c.swap_layout === "steam_view" ? "Steam/View swapped" : "Steam/Menu swapped";
      parts.push(status.swap_menu.active ? what : "swap pending");
    }
    if (c.remap_managed) parts.push("back buttons remapped");
    if (c.touchpad === false) parts.push("touchpad off");
    return parts.join(" · ") || "Default";
  };

  const gyroLine = () => {
    const g = gyro.status;
    if (!gyro.settings.enabled) return "Off";
    if (!g.device.found) return g.device.error ?? "Looking for the controllers…";
    const live = (["left", "right"] as const).filter((n) => g.slots[n].live).length;
    const who =
      g.server.clients === 1 ? "1 emulator connected" : `${g.server.clients} emulators connected`;
    const steam = settings.controls.steam_controller !== "xbox" ? " · Steam gyro on" : "";
    return `${live} of 2 controllers sending motion · ${who}${steam}`;
  };

  const toggleGame = () => {
    const next = !gameOpen;
    setGameOpen(next);
    try {
      window.localStorage.setItem("lgo-home-game-open", next ? "1" : "0");
    } catch {
      /* private storage is optional */
    }
  };

  // ---- what applies to the running game ----
  const app = status.app;
  const appKey = app.id != null ? String(app.id) : null;
  const gamePower = () => {
    if (!settings.power.enabled) return "Not managed";
    const own = status.power.profile_key !== "default";
    const key = status.power.profile_key;
    const p = settings.power.profiles[key] ?? settings.power.profiles.default;
    const parts = [own ? "Own profile" : "Default profile"];
    if (p.mode !== "custom") parts.push(modeLabel(p.mode));
    else if (p.auto) {
      const a = status.power.auto;
      parts.push(`Auto TDP to ${a.target ?? p.target_fps} fps`);
      if (status.power.tdp != null) parts.push(`now ${status.power.tdp} W`);
      if (a.learned != null) parts.push(`remembered ${a.learned} W`);
    } else parts.push(`${p.tdp} W`);
    return parts.join(" · ");
  };
  const gameSmooth = () => {
    const s = status.smooth;
    if (!s?.fps) return "Smooth frame rate off";
    const shown = s.shown ?? s.output ?? s.fps;
    const parts = [s.fg > 1 ? `${s.fps} fps × ${s.fg} = ${shown} fps` : `${shown} fps cap`];
    if (s.refresh) parts.push(`screen ${s.refresh} Hz`);
    else if (s.vrr) parts.push("VRR");
    if (s.lsfg?.installed && s.lsfg.multiplier > 1) parts.push(`lsfg-vk ${s.lsfg.multiplier}×`);
    if (s.fgmod) parts.push("Decky-Framegen");
    return parts.join(" · ");
  };
  const gameFan = () => {
    if (!caps.fan.available || !settings.fan.enabled) return "Firmware curve";
    const key = status.fan.profile_key ?? "default";
    const p = settings.fan.profiles[key] ?? settings.fan.profiles.default;
    const which = key.startsWith("default")
      ? key.endsWith(":ac") ? "Default (charger)" : "Default"
      : key.endsWith(":ac") ? "Own setting (charger)" : "Own setting";
    return `${which} · ${p.full_speed ? "full speed" : "custom curve"}`;
  };
  const gamePad = () => {
    const c = status.steam_controller;
    return `${PADS[c.type] ?? c.type} · ${c.source === "game" ? "chosen for this game" : "same as all games"}`;
  };

  // ---- acpi_call ----
  const acpi = status.acpi;
  // Only the Legion Go (83E1) has features that need the module.
  const showAcpi =
    !!acpi && status.model === "83E1" && (!acpi.available || acpi.running || !!acpi.error);
  const onInstallAcpi = async () => {
    try {
      await acpiInstallStart();
    } catch (e) {
      toaster.toast({ title: PLUGIN_NAME, body: `Could not start: ${e}` });
    }
  };

  // ---- backup ----
  const onBackup = async () => {
    try {
      const info = await backupSettings();
      setBackup(info);
      setBackupNote(info.error ?? `Saved to ${info.path}`);
    } catch (e) {
      setBackupNote(`Backup failed: ${e}`);
    }
  };
  const onRestore = async () => {
    setConfirmRestore(false);
    try {
      const out = await restoreSettings();
      if (!out.ok) {
        setBackupNote(out.error ?? "Restore failed");
        return;
      }
      if (out.settings) replaceSettings(out.settings);
      if (out.gyro) replaceGyroSettings(out.gyro);
      setBackupNote("Settings restored. Calibrate the gyro once (Gyro tab).");
    } catch (e) {
      setBackupNote(`Restore failed: ${e}`);
    }
  };

  const onReset = async () => {
    try {
      replaceSettings(await resetSettings());
      toaster.toast({ title: PLUGIN_NAME, body: "Power, fan, light and button settings were reset." });
    } catch (e) {
      toaster.toast({ title: PLUGIN_NAME, body: `Reset failed: ${e}` });
    }
  };

  const row = (tab: string, label: string, text: string, problem?: string) => (
    <PanelSectionRow>
      <ButtonItem
        layout="below"
        description={
          problem ? <span style={{ color: "#ff5a5f" }}>{problem}</span> : text
        }
        onClick={() => go(tab)}
      >
        {label}
      </ButtonItem>
    </PanelSectionRow>
  );

  return (
    <>
      {guide && <GuideSection go={go} close={() => setGuide(false)} reopened={guideAgain} />}
      <PanelSection title="Overview">
        {error && (
          <Info label="Backend not reachable" warn>
            {error}
          </Info>
        )}
        <UpdateBanner updates={updates} />
        {row("Power", "Power", powerLine(), errors.power)}
        {row("Fan", "Fan", fanLine(), errors.fan)}
        {row("Controls", "Buttons and lights", `${controlsLine()} · ${lightsLine()}`, errors.swap_menu ?? errors.remap ?? errors.sticks ?? errors.power_led)}
        {row("Gyro", "Gyro", gyroLine())}
        {row("System", "Sound, sleep and Steam", "Speaker EQ, battery while asleep, Steam update check")}
      </PanelSection>

      <PanelSection title="This game">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={
              appKey == null
                ? "No game is running. Start one to see what applies to it."
                : gameOpen
                  ? "Everything this plugin applies to the running game. Select a line to change it."
                  : `${gamePower()} · ${gameSmooth()}`
            }
            onClick={toggleGame}
          >
            {(app.name || (appKey ? `App ${appKey}` : "No game")) + (gameOpen ? "  ▴" : "  ▾")}
          </ButtonItem>
        </PanelSectionRow>
        {appKey != null && gameOpen && (
          <>
            {row("Power", "Power", gamePower(), errors.power)}
            {row("Power", "Smooth frame rate", gameSmooth(), errors.smooth)}
            {row("Fan", "Fan", gameFan(), errors.fan)}
            {row("Gyro", "Controller in Steam", gamePad())}
          </>
        )}
      </PanelSection>

      <PanelSection title="Battery">
        <Stats>
          <Stat
            label="Battery"
            value={batt.info ? batt.info.percent : "–"}
            unit="%"
            sub={batt.info
            ? [
                batt.info.status,
                batt.info.watts != null && batt.info.watts >= 0.5
                  ? `${batt.info.watts.toFixed(1)} W`
                  : null,
                batt.info.minutes != null
                  ? batt.info.status === "Charging"
                    ? `full in about ${duration(batt.info.minutes)}`
                    : `about ${duration(batt.info.minutes)} left`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")
            : "No reading"}
          />
        </Stats>
        {status.playtime?.app != null && status.playtime.on_battery && (status.playtime.goal || status.playtime.max_h != null) ? (
          <Info label="Playtime" warn={status.playtime.reachable === false}>
            {status.playtime.goal
              ? status.playtime.goal.hours >= 24
                ? `Goal: as long as possible · about ${hours(status.playtime.max_h)}`
                : `Goal ${hours(status.playtime.goal.hours)}: ${hours(status.playtime.left_h)} to go${status.playtime.reachable === false ? " · out of reach" : ""}`
              : `This game: up to about ${hours(status.playtime.max_h)} (set a goal in the Power tab)`}
          </Info>
        ) : null}
                {caps.charge_limit.available ? (
          <>
            <PanelSectionRow>
              <ToggleField
                label="Limit charge to 80%"
                description="Keeps the battery healthier when you mostly play plugged in."
                checked={settings.battery.charge_limit ?? batt.charge_limit ?? false}
                onChange={(v) => update({ battery: { charge_limit: v } })}
              />
            </PanelSectionRow>
            <ErrorRow message={errors.charge_limit} />
          </>
        ) : (
          <Unavailable cap={caps.charge_limit} what="The charge limit" />
        )}
      </PanelSection>

      {showAcpi && acpi && (
        <PanelSection title="Firmware access (acpi_call)">
          {acpi.running ? (
            <Info label={acpi.step ?? "Working"}>
              {acpi.log.length ? acpi.log[acpi.log.length - 1] : "Starting…"} Keep the device on
              and online; this takes several minutes.
            </Info>
          ) : (
            <>
              <Info label={acpi.kernel_changed ? "SteamOS was updated" : "Not installed"} warn>
                {acpi.kernel_changed
                  ? "The new SteamOS kernel needs acpi_call built again. Until then the custom fan curve and full fan speed are off."
                  : "The custom fan curve and full fan speed need the acpi_call kernel module, which SteamOS does not include."}
              </Info>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  description="Builds it on this device: needs internet, about 4 GB of free space during the build (freed afterwards) and several minutes. Nothing on the system partition is changed. After a SteamOS update with a new kernel, do this once more."
                  onClick={onInstallAcpi}
                >
                  {acpi.error ? "Try again" : "Install acpi_call"}
                </ButtonItem>
              </PanelSectionRow>
              {acpi.error && (
                <Info label="Last attempt failed" warn>
                  {acpi.error}
                </Info>
              )}
            </>
          )}
        </PanelSection>
      )}

      <Fold id="home-more" title="Backup, updates and about" summary={`Version ${state.version}${backup?.exists ? ` · last backup ${backup.saved_at ?? "?"}` : ""}`}>
        <PanelSection title="Backup">
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              description={
                backup?.exists
                  ? `Last backup: ${backup.saved_at ?? "unknown"} (version ${backup.version ?? "?"})`
                  : "Saves every setting and profile of this plugin to one file in your home folder."
              }
              onClick={onBackup}
            >
              Back up settings
            </ButtonItem>
          </PanelSectionRow>
          {backup?.exists && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                description={
                  confirmRestore
                    ? "Select again to replace the current settings with the backup."
                    : backup.path
                }
                onClick={() => (confirmRestore ? void onRestore() : setConfirmRestore(true))}
              >
                {confirmRestore ? "Yes, restore the backup" : "Restore from backup"}
              </ButtonItem>
            </PanelSectionRow>
          )}
          {backupNote && <Info label="Backup">{backupNote}</Info>}
        </PanelSection>

        <PanelSection title="About">
          <Info label="Device">
            {MODELS[status.model] ? `${MODELS[status.model]} (${status.model})` : status.model || "Unknown"}
          </Info>
          <Info label="Version">{state.version}</Info>
          {state.restored_backup && (
            <Info label="Settings">Brought back from your backup of {state.restored_backup}, since none were found at start.</Info>
          )}
          <UpdateRows updates={updates} checking={checking} check={checkUpdates} />
          {!guide && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() => {
                  setGuideAgain(true);
                  setGuide(true);
                }}
              >
                Getting started
              </ButtonItem>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={onReset}>
              Reset hardware settings
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      </Fold>
    </>
  );
};
