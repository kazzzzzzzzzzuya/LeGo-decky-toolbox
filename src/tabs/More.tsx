import { PanelSection } from "@decky/ui";
import { FC, useEffect, useState } from "react";

import { SystemState, systemState, type Updates } from "../backend";
import { useStore } from "../store";
import { Group, Info, modeLabel, NavRow, SubPage } from "../ui";
import { AboutSection, AcpiSection } from "./About";
import { FanTab } from "./Fan";
import { hours, PlaytimeSection } from "./Playtime";
import { PowerTab } from "./Power";
import { SmoothSection } from "./Smooth";
import { SystemTab } from "./System";

type Page = "power" | "cap" | "playtime" | "fan" | "steam" | "about";
const TITLES: Record<Page, string> = {
  power: "Power and TDP",
  cap: "Frame rate cap",
  playtime: "Battery goal",
  fan: "Fan curve",
  steam: "Steam mods and backups",
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
  const [sys, setSys] = useState<SystemState | null>(null);
  useEffect(() => {
    if (!page) void systemState().then(setSys).catch(() => undefined);
  }, [page]);
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
        {page === "steam" && <SystemTab part="steam" />}
        {page === "about" && <AboutSection updates={updates} checking={checking} check={check} />}
      </SubPage>
    );
  }

  const { settings, status } = state;
  const failing = sys?.steam?.items.filter((i) => !i.ok && i.id !== "steam") ?? [];
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
      <Info label="Detailed controls">
        A change here overrides the mode for this game only. Gyro and cloud saves are in the Device tab.
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
        <NavRow
          label="Steam mods and backups"
          warn={failing.length > 0}
          sub={
            failing.length
              ? `${failing.map((i) => i.label).join(", ")} needs a look`
              : sys?.steam?.overall === "ok"
                ? "All working · check, settings backups, update hold"
                : "Check, settings backups, update hold"
          }
          onClick={() => setPage("steam")}
        />
        <NavRow
          label="Backup, updates, about"
          sub={`Version ${state.version}${updates?.newer ? ` · ${updates.latest} available` : ""}`}
          onClick={() => setPage("about")}
        />
      </PanelSection>
    </>
  );
};
