import { PanelSection } from "@decky/ui";
import { FC, useState } from "react";

import type { Updates } from "../backend";
import { useStore } from "../store";
import { Group, Info, modeLabel, NavRow, SubPage } from "../ui";
import { AboutSection, AcpiSection } from "./About";
import { CloudSavesPage } from "./CloudSaves";
import { FanTab } from "./Fan";
import { GyroTab } from "./Gyro";
import { hours, PlaytimeSection } from "./Playtime";
import { PowerTab } from "./Power";
import { SmoothSection } from "./Smooth";
import { SystemTab } from "./System";

type Page = "power" | "cap" | "playtime" | "fan" | "gyro" | "steam" | "saves" | "about";
const TITLES: Record<Page, string> = {
  power: "Power and TDP",
  cap: "Frame rate cap",
  playtime: "Battery goal",
  fan: "Fan curve",
  gyro: "Gyro for emulators",
  steam: "Steam mods and backups",
  saves: "Cloud saves",
  about: "Backup, updates, about",
};

/** Every detailed control, nothing removed. A change here overrides the game's mode. */
export const MoreTab: FC<{ updates: Updates | null; checking: boolean; check: (force: boolean) => Promise<void> }> = ({
  updates,
  checking,
  check,
}) => {
  const { state } = useStore();
  const [page, setPage] = useState<Page | null>(null);
  if (!state) return null;

  if (page) {
    return (
      <SubPage title={TITLES[page]} back={() => setPage(null)}>
        {page === "power" && <PowerTab bare />}
        {page === "cap" && <SmoothSection />}
        {page === "playtime" && <PlaytimeSection />}
        {page === "fan" && (
          <>
            <AcpiSection />
            <FanTab />
          </>
        )}
        {page === "gyro" && <GyroTab />}
        {page === "steam" && <SystemTab part="steam" />}
        {page === "saves" && <CloudSavesPage />}
        {page === "about" && <AboutSection updates={updates} checking={checking} check={check} />}
      </SubPage>
    );
  }

  const { settings, status, gyro } = state;
  const pw = status.power;
  const powerLine = !settings.power.enabled
    ? "Not managed"
    : [
        pw.mode ? modeLabel(pw.mode).replace(" (set the watts)", "") : null,
        pw.tdp != null ? `${pw.tdp} W` : null,
        pw.auto.active ? `automatic, target ${pw.auto.target ?? "?"} fps` : null,
      ]
        .filter(Boolean)
        .join(" · ");
  const sm = status.smooth;
  const goal = status.playtime?.goal;
  const acpiMissing = !!status.acpi && status.model === "83E1" && !status.acpi.available;

  return (
    <>
      <Info label="Everything from before">
        Nothing was removed. A change here overrides the mode for this game only.
      </Info>
      <Group>This game</Group>
      <PanelSection>
        <NavRow label="Power and TDP" sub={powerLine} warn={!!status.errors.power} onClick={() => setPage("power")} />
        <NavRow
          label="Frame rate cap"
          sub={sm?.fps ? `${sm.fps} fps${sm.refresh ? ` · screen ${sm.refresh} Hz` : ""}` : "Off"}
          warn={!!status.errors.smooth}
          onClick={() => setPage("cap")}
        />
        <NavRow
          label="Battery goal"
          sub={goal ? `${goal.hours >= 24 ? "As long as possible" : hours(goal.hours)}` : "Off"}
          onClick={() => setPage("playtime")}
        />
        <NavRow
          label="Fan curve"
          sub={acpiMissing ? "Needs acpi_call (install on the page)" : settings.fan.enabled ? "Custom curve" : "Firmware curve"}
          warn={!!status.errors.fan}
          onClick={() => setPage("fan")}
        />
        <Info label="Frame generation">
          Set in Frame Suite, in its own Quick Access panel. Smoothest on the Game tab turns it on there.
        </Info>
      </PanelSection>
      <Group>Device</Group>
      <PanelSection>
        <NavRow label="Gyro for emulators" sub={gyro.settings.enabled ? "On" : "Off"} onClick={() => setPage("gyro")} />
        <NavRow label="Steam mods and backups" sub="Check, settings backups, update hold" onClick={() => setPage("steam")} />
        <NavRow label="Cloud saves" sub="Per game: did the save reach the cloud" onClick={() => setPage("saves")} />
        <NavRow
          label="Backup, updates, about"
          sub={`Version ${state.version}${updates?.newer ? ` · ${updates.latest} available` : ""}`}
          onClick={() => setPage("about")}
        />
      </PanelSection>
    </>
  );
};
