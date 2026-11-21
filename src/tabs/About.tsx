import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, useEffect, useState } from "react";

import { acpiInstallStart, BackupInfo, backupInfo, backupSettings, resetSettings, restoreSettings } from "../backend";
import { replaceGyroSettings, replaceSettings, useStore } from "../store";
import { Info, PLUGIN_NAME } from "../ui";
import type { Updates } from "../backend";
import { UpdateRows } from "./Updates";

const MODELS: Record<string, string> = {
  "83E1": "Legion Go",
  "83N0": "Legion Go 2",
  "83N1": "Legion Go 2",
  "83L3": "Legion Go S",
  "83N6": "Legion Go S",
};

const toast = (body: string) => toaster.toast({ title: PLUGIN_NAME, body });

/** Backup and restore, device and version, updates, reset. */
export const AboutSection: FC<{ updates: Updates | null; checking: boolean; check: (force: boolean) => Promise<void> }> = ({
  updates,
  checking,
  check,
}) => {
  const { state } = useStore();
  const [backup, setBackup] = useState<BackupInfo | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [confirmRestore, setConfirmRestore] = useState(false);
  useEffect(() => {
    backupInfo().then(setBackup).catch(() => undefined);
  }, []);
  if (!state) return null;
  const { status } = state;

  const onBackup = async () => {
    try {
      const info = await backupSettings();
      setBackup(info);
      setNote(info.error ?? `Saved to ${info.path}`);
    } catch (e) {
      setNote(`Backup failed: ${e}`);
    }
  };
  const onRestore = async () => {
    setConfirmRestore(false);
    try {
      const out = await restoreSettings();
      if (!out.ok) {
        setNote(out.error ?? "Restore failed");
        return;
      }
      if (out.settings) replaceSettings(out.settings);
      if (out.gyro) replaceGyroSettings(out.gyro);
      setNote("Settings restored. Calibrate the gyro once (More → Gyro for emulators).");
    } catch (e) {
      setNote(`Restore failed: ${e}`);
    }
  };
  const onReset = async () => {
    try {
      replaceSettings(await resetSettings());
      toast("Power, fan, light and button settings were reset.");
    } catch (e) {
      toast(`Reset failed: ${e}`);
    }
  };

  return (
    <>
      <PanelSection title="Backup">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={
              backup?.exists
                ? `Last backup: ${backup.saved_at ?? "unknown"} (version ${backup.version ?? "?"})`
                : "Saves every setting of this plugin to one file in your home folder."
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
              description={confirmRestore ? "Select again to replace the current settings with the backup." : backup.path}
              onClick={() => (confirmRestore ? void onRestore() : setConfirmRestore(true))}
            >
              {confirmRestore ? "Yes, restore the backup" : "Restore from backup"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {note && <Info label="Backup">{note}</Info>}
      </PanelSection>
      <PanelSection title="About">
        <Info label="Device">
          {MODELS[status.model] ? `${MODELS[status.model]} (${status.model})` : status.model || "Unknown"}
        </Info>
        <Info label="Version">{state.version}</Info>
        {state.restored_backup && (
          <Info label="Settings">Brought back from your backup of {state.restored_backup}, since none were found at start.</Info>
        )}
        <UpdateRows updates={updates} checking={checking} check={check} />
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onReset}>
            Reset hardware settings
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

/** acpi_call (needed for the custom fan curve on the Legion Go): install, progress, problems.
 *  Shows nothing while it is installed and fine. */
export const AcpiSection: FC = () => {
  const { state } = useStore();
  const acpi = state?.status.acpi;
  if (!state || !acpi || state.status.model !== "83E1" || (acpi.available && !acpi.running && !acpi.error)) return null;
  const onInstall = async () => {
    try {
      await acpiInstallStart();
    } catch (e) {
      toast(`Could not start: ${e}`);
    }
  };
  return (
    <PanelSection title="Firmware access (acpi_call)">
      {acpi.running ? (
        <Info label={acpi.step ?? "Working"}>
          {acpi.log.length ? acpi.log[acpi.log.length - 1] : "Starting…"} Keep the device on and online; this takes
          several minutes.
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
              onClick={onInstall}
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
  );
};
