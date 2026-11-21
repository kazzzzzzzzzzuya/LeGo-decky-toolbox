import { DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, useEffect, useState } from "react";

import { cloudSavesSummary, SystemState, systemState, systemUpdate } from "../backend";
import { usePanelVisible } from "../panel";
import { update, useStore } from "../store";
import { ErrorRow, Group, NavRow, PLUGIN_NAME, SubPage, Toggle } from "../ui";
import { CloudSavesPage } from "./CloudSaves";
import { ControlsTab, LAYOUTS } from "./Controls";
import { LightsTab } from "./Lights";
import { SteamGyroSection } from "./SteamGyro";
import { SystemTab } from "./System";

type Page = "buttons" | "lights" | "gyro" | "sound" | "sleep" | "steam" | "saves";
const TITLES: Record<Page, string> = {
  buttons: "Buttons",
  lights: "Lights",
  gyro: "Gyro in Steam games",
  sound: "Sound",
  sleep: "Sleep",
  steam: "Steam mods",
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
        {page === "gyro" && <SteamGyroSection />}
        {page === "sound" && <SystemTab part="speakers" />}
        {page === "sleep" && <SystemTab part="sleep" />}
        {page === "steam" && <SystemTab part="steam" />}
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
  const steam = sys?.steam;
  const failing = steam?.items.filter((i) => !i.ok && i.id !== "steam") ?? [];
  const mods = steam?.items.filter((i) => i.id !== "steam") ?? [];
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
          sub={c.steam_controller !== "xbox" ? "On in Steam games" : "Off in Steam games"}
          onClick={() => setPage("gyro")}
        />
      </PanelSection>

      <Group>Steam mods</Group>
      <PanelSection>
        <NavRow
          warn={failing.length > 0}
          label={
            !steam || steam.overall === "idle" || mods.length === 0
              ? "Steam mods"
              : failing.length
                ? `${mods.length - failing.length} of ${mods.length} working`
                : "All working"
          }
          sub={
            failing.length
              ? `${failing.map((i) => i.label).join(", ")} needs a look`
              : mods.length
                ? mods.map((i) => i.label).join(" · ")
                : "SLSsteam, CloudRedirect, ASSella / Uran"
          }
          onClick={() => setPage("steam")}
        />
      </PanelSection>

      <Group>Cloud saves</Group>
      <PanelSection>
        <NavRow
          warn={!!saves?.problems}
          label={
            !saves || !saves.installed
              ? "Cloud saves"
              : saves.problems
                ? `${saves.problems} ${saves.problems === 1 ? "thing needs" : "things need"} a look`
                : `${saves.games} ${saves.games === 1 ? "game" : "games"} synced`
          }
          sub={
            saves?.installed
              ? `Steam games to ${saves.provider_label ?? "no cloud yet"} · other games with OpenSave`
              : "Steam games (CloudRedirect) and other games (OpenSave)"
          }
          onClick={() => setPage("saves")}
        />
      </PanelSection>
    </>
  );
};
