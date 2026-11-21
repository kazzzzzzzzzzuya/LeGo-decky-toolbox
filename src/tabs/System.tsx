import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  SliderField } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, useEffect, useRef, useState } from "react";

import {
  sleepClear,
  SleepEntry,
  steamCheck,
  steamHold,
  steamRestore,
  SteamSnapshot,
  steamSnapshotNow,
  steamSnapshots,
  SystemSettings,
  SystemState,
  systemState,
  systemUpdate,
} from "../backend";
import { usePanelVisible } from "../panel";
import { Check, Fold, Info, Pills, PLUGIN_NAME, Stat, Stats, Toggle } from "../ui";

type Patch = { eq?: Partial<SystemSettings["eq"]>; sleep?: Partial<SystemSettings["sleep"]> };

const toast = (body: string) => toaster.toast({ title: PLUGIN_NAME, body });

const EQ_STATE: Record<string, string> = {
  off: "Off: the speakers play as SteamOS sends them.",
  starting: "Starting…",
  on: "On: the speakers play through the EQ.",
  headphones: "Headphones in use: they get no EQ. It comes back when they are unplugged.",
  other: "Another output plays (Bluetooth, USB or a screen): it gets no EQ.",
  other_effect: "Another sound effect is the output right now, so this EQ waits. Use one or the other.",
  failed: "Not running.",
};

const time = (t: number) =>
  new Date(t * 1000).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });

function sleepLine(e: SleepEntry): string {
  const h = e.hours >= 1 ? `${e.hours.toFixed(1)} h` : `${Math.round(e.hours * 60)} min`;
  const pct = e.pct_before != null && e.pct_after != null ? ` · ${e.pct_before} → ${e.pct_after} %` : "";
  const rate = e.drain_ph != null ? ` · ${e.drain_ph.toFixed(1)} %/h` : e.ac ? " · charging" : "";
  return `${time(e.end)}: ${h}${pct}${rate}${e.powered_off ? " · powered off" : ""}`;
}

const PRESET_SHORT: Record<string, string> = { balanced: "Balanced", voice: "Voice", bass: "Bass", flat: "Flat" };

/** Decoration while the EQ plays: a still sound wave. */
const WAVE = [10, 22, 30, 18, 26, 12, 20, 30, 16, 8, 18, 24, 14, 6, 12, 20];
const Wave: FC = () => (
  <PanelSectionRow>
    <div style={{ display: "flex", gap: 3, alignItems: "center", height: 34, padding: "2px 0" }}>
      {WAVE.map((h, i) => (
        <div key={i} style={{ width: 4, height: h, borderRadius: 2, background: "#f2f2f2" }} />
      ))}
    </div>
  </PanelSectionRow>
);

/** The System sections: all three, or one ("speakers", "sleep", "steam") for a page of its own. */
export const SystemTab: FC<{ part?: "speakers" | "sleep" | "steam" }> = ({ part }) => {
  const show = (p: string) => !part || part === p;
  const [st, setSt] = useState<SystemState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [snaps, setSnaps] = useState<SteamSnapshot[]>([]);
  const [busy, setBusy] = useState(false);
  // Sliders send while they move; the EQ restarts on each change, so wait for the thumb to rest.
  const [tone, setTone] = useState<{ bass: number; treble: number } | null>(null);
  const toneTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const refresh = () =>
    systemState()
      .then((s) => {
        setSt(s);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  const loadSnaps = () => steamSnapshots().then(setSnaps).catch(() => undefined);
  const visible = usePanelVisible();
  useEffect(() => {
    void refresh();                  // once on opening, even if visibility can't be told
    void loadSnaps();
    if (!visible) return;
    const id = setInterval(() => void refresh(), 2000);
    return () => {
      clearInterval(id);
      if (toneTimer.current) clearTimeout(toneTimer.current);
    };
  }, [visible]);

  if (!st) return <Info label={error ? "Backend not reachable" : "Loading…"}>{error}</Info>;
  const { settings, eq, sleep, steam } = st;
  const set = (patch: Patch) =>
    systemUpdate(patch)
      .then(setSt)
      .catch((e) => toast(`Could not save: ${e}`));
  const toneNow = tone ?? { bass: settings.eq.bass, treble: settings.eq.treble };
  const setToneSoon = (k: "bass" | "treble", v: number) => {
    const next = { ...toneNow, [k]: v };
    setTone(next);
    if (toneTimer.current) clearTimeout(toneTimer.current);
    toneTimer.current = setTimeout(() => {
      void set({ eq: next }).then(() => setTone(null));
    }, 700);
  };

  const onCheck = async () => {
    setBusy(true);
    try {
      setSt(await steamCheck());
      await loadSnaps();
    } catch (e) {
      toast(`Check failed: ${e}`);
    } finally {
      setBusy(false);
    }
  };
  const onHold = async (on: boolean) => {
    const out = await steamHold(on).catch((e) => ({ ok: false, error: String(e) }));
    if (!out.ok) toast(out.error ?? "Could not change steam.cfg");
    await refresh();
  };
  const onSnapshot = async () => {
    const out = await steamSnapshotNow().catch((e) => ({ ok: false, name: null, error: String(e) }));
    toast(out.ok ? "Backup saved" : (out.error ?? "Backup failed"));
    await loadSnaps();
  };
  const askRestore = (s: SteamSnapshot) =>
    showModal(
      <ConfirmModal
        strTitle={`Restore the backup of ${s.created}?`}
        strDescription={`Puts back: ${s.files.join(", ")}. Your current files are backed up first. Restart Steam afterwards.`}
        strOKButtonText="Restore"
        onOK={async () => {
          const out = await steamRestore(s.name).catch((e) => ({ ok: false, restored: [], error: String(e) }));
          toast(out.ok ? "Restored. Restart Steam (Power → Restart Steam)." : `Restore: ${out.error}`);
          await loadSnaps();
        }}
      />,
    );

  const failing = steam?.items.filter((i) => !i.ok && i.id !== "steam") ?? [];
  const hold = steam?.hold;

  return (
    <>
      {show("speakers") && (
      <PanelSection title="Speakers">
        {!eq.available ? (
          <Info label="Speaker EQ is not available" warn>
            {eq.reason}
          </Info>
        ) : (
          <>
            <PanelSectionRow>
              <Toggle
                label="Speaker EQ"
                description={EQ_STATE[eq.state] ?? eq.state}
                checked={settings.eq.enabled}
                onChange={(v) => void set({ eq: { enabled: v } })}
              />
            </PanelSectionRow>
            {eq.error && settings.eq.enabled && <Info label="EQ problem" warn>{eq.error}</Info>}
            {eq.others.length > 0 && settings.eq.enabled && (
              <Info label="Another sound effect is installed" warn>
                {eq.others.join(", ")}. Each is a separate output, so they do not stack: whichever is selected as the
                output plays. Pick one in Steam's sound settings, or remove the other.
              </Info>
            )}
            {settings.eq.enabled && (
              <>
                {eq.state === "on" && <Wave />}
                <Pills
                  options={eq.presets.map((p) => ({ id: p.id, label: PRESET_SHORT[p.id] ?? p.label }))}
                  value={settings.eq.preset}
                  onChange={(id) => void set({ eq: { preset: id } })}
                />
                <PanelSectionRow>
                  <SliderField
                    label="Bass"
                    value={toneNow.bass}
                    min={-6}
                    max={6}
                    step={1}
                    showValue
                    valueSuffix=" dB"
                    onChange={(v) => setToneSoon("bass", v)}
                  />
                </PanelSectionRow>
                <PanelSectionRow>
                  <SliderField
                    label="Treble"
                    value={toneNow.treble}
                    min={-6}
                    max={6}
                    step={1}
                    showValue
                    valueSuffix=" dB"
                    onChange={(v) => setToneSoon("treble", v)}
                  />
                </PanelSectionRow>
                <Info label="Speakers only">Headphones, Bluetooth and USB never get it. Off removes it completely.</Info>
              </>
            )}
          </>
        )}
      </PanelSection>
      )}

      {show("sleep") && (
      <PanelSection title="Sleep">
        {sleep.last ? (
          <Stats>
            <Stat
              label="Average"
              value={sleep.average_ph != null ? sleep.average_ph.toFixed(1) : "–"}
              unit="%/h"
              size={34}
              sub={`${sleep.counted} sleep${sleep.counted === 1 ? "" : "s"}`}
            />
            <Stat
              label="Last sleep"
              value={sleep.last.hours >= 1 ? sleep.last.hours.toFixed(1) : Math.round(sleep.last.hours * 60)}
              unit={sleep.last.hours >= 1 ? "h" : "min"}
              size={34}
              sub={sleep.last.pct_before != null && sleep.last.pct_after != null
                ? `${sleep.last.pct_before} → ${sleep.last.pct_after} %`
                : undefined}
            />
          </Stats>
        ) : (
          <Info label="Battery used while asleep">Measured from the next sleep longer than a minute.</Info>
        )}

        {!sleep.available ? (
          <Info label="Power-off after a long sleep is not available" warn>
            This system has no RTC wake alarm (/sys/class/rtc/rtc0/wakealarm).
          </Info>
        ) : (
          <>
            <PanelSectionRow>
              <Toggle
                label="Power off after a long sleep"
                description="Still asleep after the hours below: it shuts down. Unsaved games are lost."
                checked={settings.sleep.poweroff}
                onChange={(v) => void set({ sleep: { poweroff: v } })}
              />
            </PanelSectionRow>
            {settings.sleep.poweroff && (
              <>
                <PanelSectionRow>
                  <DropdownItem
                    label="After"
                    rgOptions={sleep.hours_choices.map((h) => ({ data: h, label: `${h} hours` }))}
                    selectedOption={settings.sleep.hours}
                    onChange={(o) => void set({ sleep: { hours: o.data as number } })}
                  />
                </PanelSectionRow>
                <PanelSectionRow>
                  <Toggle
                    label="Only on battery"
                    description="Sleeping on the charger never powers off."
                    checked={settings.sleep.battery_only}
                    onChange={(v) => void set({ sleep: { battery_only: v } })}
                  />
                </PanelSectionRow>
              </>
            )}
          </>
        )}
        {sleep.history.length > 1 && (
          <Fold id="sleep-history" inline title="Recent sleeps" summary={`${sleep.history.length} measured`}>
            <Info label="Recent sleeps" focusable>
              {sleep.history.slice(1, 6).map((e, i) => (
                <div key={i}>{sleepLine(e)}</div>
              ))}
            </Info>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => void sleepClear().then(setSt)}>
                Clear the sleep history
              </ButtonItem>
            </PanelSectionRow>
          </Fold>
        )}
      </PanelSection>
      )}

      {show("steam") && (<>
      <PanelSection title="Steam update check">
        {!steam ? (
          <Info label="Checking…" />
        ) : steam.overall === "ok" ? null : steam.overall === "idle" ? (
          <Info label="Steam is not running" />
        ) : (
          <Info label="Something stopped working" warn>
            {steam.updated_since_good && steam.last_good
              ? `Steam updated from build ${steam.last_good} to ${steam.version}. `
              : ""}
            {failing.map((i) => i.label).join(", ") || steam.error}. Settings files can be restored below; a mod
            that no longer loads needs its own update for this Steam build.
          </Info>
        )}
        {steam && steam.items.length > 0 && (
          <PanelSectionRow>
            <Field bottomSeparator="none" padding="none" childrenLayout="below" childrenContainerWidth="max">
              <div className="dot-card" style={{ width: "100%" }}>
                <div className="dot-label" style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>Build {steam.version ?? "?"}</span>
                  <span>{steam.checked_at}</span>
                </div>
                {steam.items.map((i) => (
                  <Check key={i.id} ok={i.ok} label={i.label} detail={i.ok ? i.detail.split(" · ")[0] : i.detail} />
                ))}
              </div>
            </Field>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={() => void onCheck()}>
            {busy ? "Checking…" : "Check now"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <Fold
        id="steam-more"
        title="Backups and update hold"
        summary={`${snaps[0] ? `Newest backup ${snaps[0].created}` : "No backup yet"}${hold?.held ? " · Steam updates held" : ""}`}
      >
        <PanelSection>
            <PanelSectionRow>
              <Toggle
                label="Hold Steam client updates"
                description={
                  hold?.foreign
                    ? "steam.cfg already exists with other settings, so this is left alone."
                    : "Valve's steam.cfg switch: the Steam client stays on this build. SteamOS updates are not affected. Turn it off to update, then check here."
                }
                checked={!!hold?.held}
                disabled={!!hold?.foreign}
                onChange={(v) => void onHold(v)}
              />
            </PanelSectionRow>
            <Info label="Settings backups">
              Saved by themselves whenever everything works. The last 8 are kept.
            </Info>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => void onSnapshot()}>
                Back up now
              </ButtonItem>
            </PanelSectionRow>
            {snaps.length > 0 && (
              <PanelSectionRow>
                <DropdownItem
                  label="Restore a backup"
                  strDefaultLabel="Choose one"
                  rgOptions={snaps.map((s) => ({
                    data: s.name,
                    label: `${s.created}${s.steam ? ` · build ${s.steam}` : ""} · ${s.reason}`,
                  }))}
                  selectedOption={null}
                  onChange={(o) => {
                    const s = snaps.find((x) => x.name === o.data);
                    if (s) askRestore(s);
                  }}
                />
              </PanelSectionRow>
            )}
        </PanelSection>
      </Fold>
      </>)}
    </>
  );
};

/** A minute after Steam starts (after an update it restarts): say so if a mod stopped working. */
export function watchSteamMods(): () => void {
  const timer = setTimeout(() => {
    void steamCheck()
      .then((s) => {
        const r = s.steam;
        if (r?.overall !== "fail") return;
        const names = r.items.filter((i) => !i.ok && i.id !== "steam").map((i) => i.label).join(", ");
        toast(
          `${r.updated_since_good ? "Steam updated: " : ""}${names || "a Steam mod"} is not working. See Device → Steam mods.`,
        );
      })
      .catch(() => undefined);
  }, 60000);
  return () => clearTimeout(timer);
}
