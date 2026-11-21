import { DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, useEffect, useState } from "react";

import { cloudSavesSummary, SystemState, systemState, systemUpdate } from "../backend";
import { usePanelVisible } from "../panel";
import { update, useStore } from "../store";
import { ErrorRow, Group, NavRow, Pills, PLUGIN_NAME, SubPage, Toggle } from "../ui";
import { CloudSavesPage } from "./CloudSaves";
import { ControlsTab, LAYOUTS } from "./Controls";
import { LightsTab } from "./Lights";
import { GyroTab } from "./Gyro";
import { SteamGyroSection } from "./SteamGyro";
import { SystemTab } from "./System";

type Page = "buttons" | "lights" | "gyro" | "sound" | "sleep" | "saves";
const TITLES: Record<Page, string> = {
  buttons: "Buttons",
  lights: "Lights",
  gyro: "Gyro",
  sound: "Sound",
  sleep: "Sleep",
  saves: "Cloud saves",
};

/** Set-once settings of the device, grouped; each group's details on a page of its own. */
export const DeviceTab: FC = () => {
  const { state } = useStore();
  const [page, setPage] = useState<Page | null>(null);
  const [sys, setSys] = useState<SystemState | null>(null);
  const [saves, setSaves] = useState<Awaited<ReturnType<typeof cloudSavesSummary>> | null>(null);
  const visible = usePanelVisible();
  useEffect(() => {
    if (page) return;
    let alive = true;
    const load = () =>
      cloudSavesSummary()
        .then((s) => alive && setSaves(s))
        .catch(() => undefined);
    load();
    const id = visible ? setInterval(load, 15000) : undefined;
    return () => {
      alive = false;
      if (id) clearInterval(id);
    };
  }, [page, visible]);
  useEffect(() => {
    let alive = true;
    const load = () =>
      systemState()
        .then((s) => alive && setSys(s))
        .catch(() => undefined);
    load();                          // once on opening, even if visibility can't be told
    if (!visible) return () => {
      alive = false;
    };
    const id = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [page, visible]);
  if (!state) return null;

  if (page) {
    const back = () => setPage(null);
    return (
      <SubPage title={TITLES[page]} back={back}>
        {page === "buttons" && <ControlsTab />}
        {page === "lights" && <LightsTab />}
        {page === "gyro" && <GyroPage />}
        {page === "sound" && <SystemTab part="speakers" />}
        {page === "sleep" && <SystemTab part="sleep" />}
        {page === "saves" && <CloudSavesPage />}
      </SubPage>
    );
  }

  const { caps, settings, status } = state;
  const sysSet = (patch: Parameters<typeof systemUpdate>[0]) =>
    systemUpdate(patch)
      .then(setSys)
      .catch((e) => toaster.toast({ title: PLUGIN_NAME, body: `Could not save: ${e}` }));
  const c = settings.controls;
  const layout = LAYOUTS.find((l) => l.data === c.swap_layout);
  const sticks = settings.lighting.sticks;
  const sleep = sys?.sleep;

  return (
    <>
      <Group>Battery</Group>
      <PanelSection>
        {caps.charge_limit.available && (
          <>
            <PanelSectionRow>
              <Toggle
                label="Stop charging at 80 %"
                description="Healthier battery when you mostly play plugged in."
                checked={settings.battery.charge_limit ?? status.battery.charge_limit ?? false}
                onChange={(v) => update({ battery: { charge_limit: v } })}
              />
            </PanelSectionRow>
            <ErrorRow message={status.errors.charge_limit} />
          </>
        )}
        {sys && sleep?.available && (
          <>
            <PanelSectionRow>
              <Toggle
                label="Power off after a long sleep"
                description={`After ${sys.settings.sleep.hours} h asleep${
                  sleep.average_ph != null ? ` · asleep it uses ${sleep.average_ph.toFixed(1)} %/h` : ""
                }`}
                checked={sys.settings.sleep.poweroff}
                onChange={(v) => void sysSet({ sleep: { poweroff: v } })}
              />
            </PanelSectionRow>
            {sys.settings.sleep.poweroff && (
              <PanelSectionRow>
                <DropdownItem
                  label="After"
                  rgOptions={sleep.hours_choices.map((h) => ({ data: h, label: `${h} hours` }))}
                  selectedOption={sys.settings.sleep.hours}
                  onChange={(o) => void sysSet({ sleep: { hours: o.data as number } })}
                />
              </PanelSectionRow>
            )}
          </>
        )}
        <NavRow
          label="Sleep details"
          sub={sleep?.last ? `Last: ${sleep.last.hours.toFixed(1)} h asleep` : "Battery used while asleep"}
          onClick={() => setPage("sleep")}
        />
      </PanelSection>

      <Group>Sound</Group>
      <PanelSection>
        {sys && (sys.eq.available ? (
          <PanelSectionRow>
            <Toggle
              label="Better speakers"
              description={
                sys.settings.eq.enabled
                  ? `Speaker EQ · ${sys.eq.presets.find((p) => p.id === sys.settings.eq.preset)?.label ?? ""}`
                  : "An EQ for the built-in speakers only"
              }
              checked={sys.settings.eq.enabled}
              onChange={(v) => void sysSet({ eq: { enabled: v } })}
            />
          </PanelSectionRow>
        ) : null)}
        <NavRow label="Sound settings" sub="Sound, bass and treble" onClick={() => setPage("sound")} />
      </PanelSection>

      <Group>Controls</Group>
      <PanelSection>
        <NavRow
          label="Buttons"
          sub={[
            c.swap_menu && layout ? layout.label.replace(" (default)", "") : "Steam's layout",
            c.remap_managed ? "back buttons remapped" : null,
            c.touchpad === false ? "touchpad off" : null,
          ]
            .filter(Boolean)
            .join(" · ")}
          onClick={() => setPage("buttons")}
        />
        <NavRow
          label="Lights"
          sub={!sticks.managed ? "Unchanged" : sticks.on ? `Sticks ${sticks.mode}` : "Sticks off"}
          onClick={() => setPage("lights")}
        />
        <NavRow
          label="Gyro"
          sub={`Steam games: ${c.steam_controller !== "xbox" ? "on" : "off"} · emulators: ${state.gyro.settings.enabled ? "on" : "off"}`}
          onClick={() => setPage("gyro")}
        />
      </PanelSection>

      <Group>Saves</Group>
      <PanelSection>
        <NavRow
          warn={!!saves?.problems}
          label="Cloud saves"
          sub={
            saves?.installed
              ? saves.problems
                ? `${saves.problems} ${saves.problems === 1 ? "thing needs" : "things need"} a look`
                : `${saves.games} ${saves.games === 1 ? "game" : "games"} in ${saves.provider_label ?? "no cloud yet"} · other games with OpenSave`
              : "Steam games (CloudRedirect), other games (OpenSave)"
          }
          onClick={() => setPage("saves")}
        />
      </PanelSection>
    </>
  );
};

/** Device → Gyro: Steam games and emulators on one page, picked at the top. */
const GyroPage: FC = () => {
  const [which, setWhich] = useState<"steam" | "emu">("steam");
  return (
    <>
      <Pills
        options={[
          { id: "steam", label: "Steam games" },
          { id: "emu", label: "Emulators" },
        ]}
        value={which}
        onChange={setWhich}
      />
      {which === "steam" ? <SteamGyroSection /> : <GyroTab />}
    </>
  );
};
