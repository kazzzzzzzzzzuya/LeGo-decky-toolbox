import { ButtonItem, ConfirmModal, Field, PanelSection, PanelSectionRow, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, ReactNode, useEffect, useRef, useState } from "react";

import {
  CloudGame,
  cloudSaves,
  cloudSavesAlerts,
  cloudSavesCheck,
  CloudSavesState,
  OpenSaveGame,
  opensaveBackup,
  opensaveStart,
  opensaveSync,
  opensaveUntrack,
  OpenSaveState,
} from "../backend";
import { usePanelVisible } from "../panel";
import { Info, PLUGIN_NAME, Stat, Stats, useOnce } from "../ui";

const toast = (body: string) => toaster.toast({ title: PLUGIN_NAME, body });

/** "Sat 14:02", or "14:02" for today. */
export function when(t: number | null | undefined): string {
  if (!t) return "never";
  const d = new Date(t * 1000);
  const today = new Date().toDateString() === d.toDateString();
  return d.toLocaleString(undefined, today ? { hour: "2-digit", minute: "2-digit" } : { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

export function size(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1 << 20) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1 << 30) return `${(bytes / (1 << 20)).toFixed(1)} MB`;
  return `${(bytes / (1 << 30)).toFixed(2)} GB`;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** A Steam game's name from the Steam client, for one the backend could not name. */
export function steamName(appid: number | null): string | null {
  if (appid == null) return null;
  try {
    const store = (window as unknown as {
      appStore?: { GetAppOverviewByAppID?: (id: number) => { display_name?: string } | null };
    }).appStore;
    return store?.GetAppOverviewByAppID?.(appid)?.display_name ?? null;
  } catch {
    return null;
  }
}

const gameName = (g: { appid: number | null; name: string | null }) =>
  g.name ?? steamName(g.appid) ?? (g.appid != null ? `App ${g.appid}` : "Unknown game");

type Mark = "ok" | "warn" | "fail" | "none" | "busy";
const MARK: Record<Mark, { sign: string; color: string }> = {
  ok: { sign: "✓", color: "#f2f2f2" },
  busy: { sign: "↑", color: "#f2f2f2" },
  warn: { sign: "!", color: "#8a8a8a" },
  fail: { sign: "!", color: "#d71921" },
  none: { sign: "–", color: "#8a8a8a" },
};

/** One game: a round mark, its name and one line; A shows or hides the details under it. */
const GameRow: FC<{ mark: Mark; name: string; line: ReactNode; open: boolean; toggle: () => void; children?: ReactNode }> = ({
  mark,
  name,
  line,
  open,
  toggle,
  children,
}) => {
  const m = MARK[mark];
  const flip = useOnce(toggle);
  return (
    <>
      <PanelSectionRow>
        <Field
          label={
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span
                style={{
                  width: 18, height: 18, flex: "none", borderRadius: "50%", fontSize: 11, lineHeight: "15px",
                  textAlign: "center", border: `1.5px solid ${m.color}`, color: m.color, boxSizing: "border-box",
                }}
              >
                {m.sign}
              </span>
              <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{name}</span>
            </span>
          }
          description={
            <span style={{ color: mark === "fail" ? "#ff5a5f" : undefined, overflowWrap: "anywhere" }}>{line}</span>
          }
          onActivate={flip}
          onClick={flip}
          focusable
          highlightOnFocus
          bottomSeparator="none"
        >
          <span style={{ color: "#8a8a8a", fontSize: 14 }}>{open ? "▴" : "▾"}</span>
        </Field>
      </PanelSectionRow>
      {open && children}
    </>
  );
};

/** Lines of details in an outlined card. */
const Details: FC<{ lines: (ReactNode | null | false)[] }> = ({ lines }) => (
  <PanelSectionRow>
    <Field bottomSeparator="none" padding="none" childrenLayout="below" childrenContainerWidth="max">
      <div className="dot-card" style={{ width: "100%", fontSize: 12.5, lineHeight: 1.45 }}>
        {lines.filter(Boolean).map((l, i) => (
          <div key={i} style={{ overflowWrap: "anywhere" }}>
            {l}
          </div>
        ))}
      </div>
    </Field>
  </PanelSectionRow>
);

function steamMark(g: CloudGame): Mark {
  if (g.level === "ok" && g.uploading) return "busy";
  return g.level;
}

/** Where the game's save is: here, in the cloud, both (null: cloud not asked yet). */
function place(g: CloudGame): { local: boolean; cloud: boolean | null } {
  const c = g.cloud;
  const checked = !!c && !c.error && c.present != null;
  return { local: (g.files ?? 0) > 0, cloud: checked ? !!c?.present && (c?.files ?? 1) > 0 : null };
}

const hasSave = (g: CloudGame) => {
  const p = place(g);
  return p.local || p.cloud === true || g.last_upload?.result === "ok";
};

/** Names A–Z first, then "App 123" by number. */
function byName(a: CloudGame, b: CloudGame): number {
  const na = g2(a), nb = g2(b);
  if (!!na !== !!nb) return na ? -1 : 1;
  if (na && nb) return na.localeCompare(nb);
  return (a.appid ?? 0) - (b.appid ?? 0);
}
const g2 = (g: CloudGame) => g.name ?? steamName(g.appid);

const WhereTag: FC<{ g: CloudGame; where: string }> = ({ g, where }) => {
  const p = place(g);
  const [text, warn] = p.cloud === null
    ? [p.local ? "This device · cloud not checked yet" : "Cloud not checked yet", false]
    : p.local && p.cloud ? [`This device + ${where}`, false]
      : p.local ? ["This device only", true]
        : p.cloud ? [`${where} only`, false] : [null, false];
  if (!text) return null;
  return (
    <span style={{
      display: "inline-block", fontSize: 10.5, letterSpacing: 0.5, borderRadius: 8, padding: "0 6px", marginTop: 4,
      border: `1px solid ${warn ? "rgba(215,25,33,.55)" : "#3a3a3a"}`, color: warn ? "#ff5a5f" : "#f2f2f2",
    }}>
      {text}
    </span>
  );
};

function steamLine(g: CloudGame, where: string): string {
  if (g.problem) return g.problem;
  if (g.uploading) return "Uploading now…";
  const p = place(g);
  if (!p.local && p.cloud) {
    return `In ${where}${g.cloud?.newest ? `, updated ${when(g.cloud.newest)}` : ""} · not on this device`;
  }
  const parts = [`Synced ${when(g.synced_at)}`];
  if (g.files != null) parts.push(`${plural(g.files, "file")}${g.bytes ? `, ${size(g.bytes)}` : ""}`);
  const c = g.cloud;
  if (c?.stale) parts.push("cloud check soon");
  return parts.join(" · ");
}

function steamDetails(g: CloudGame, where: string): (string | null)[] {
  const u = g.last_upload;
  const c = g.cloud;
  let cloud: string;
  if (!c) cloud = `${where}: not checked yet.`;
  else if (c.error) cloud = `${where}: the check failed (${c.error}).`;
  else if (c.present === false) cloud = `${where}: this game is not there.`;
  else
    cloud = `${where}: ${c.matched ?? 0} of ${c.compared ?? 0} files${c.newest ? `, updated ${when(c.newest)}` : ""}.`;
  return [
    u
      ? `Last upload ${u.at}${u.this_session ? "" : " (an earlier Steam session)"}: ${
          u.result === "ok" ? "finished" : u.result === "failed" ? "failed" : u.this_session ? "running" : "did not finish"
        }${u.files != null ? `, ${plural(u.files, "file")}` : ""}.`
      : "No upload in CloudRedirect's log.",
    g.synced_at != null
      ? `On this device: ${g.files != null ? `${plural(g.files, "file")}, ${size(g.bytes)}` : "the record is unreadable"}, synced ${when(g.synced_at)}.`
      : null,
    cloud + (c?.checked_at ? ` Checked ${when(c.checked_at)}${c.stale ? "; the saves changed since" : ""}.` : ""),
    c && c.missing_count > 0 ? `Not in the cloud: ${c.missing.join(", ")}${c.missing_count > c.missing.length ? " …" : ""}` : null,
    g.appid != null ? `Steam app ${g.appid}` : null,
  ];
}

function osMark(g: OpenSaveGame): Mark {
  if (g.conflict || g.folder_missing || g.emptied) return "fail";
  return g.last_snapshot ? "ok" : "none";
}

function osLine(g: OpenSaveGame): string {
  if (g.conflict) return "Two devices changed this save: choose which to keep in the OpenSave app.";
  if (g.emptied) return "Every save file was deleted here: OpenSave holds it back until you answer in its app.";
  if (g.folder_missing) return "The save folder is not there (moved, or on a card that is out).";
  if (g.playing) return "Playing now";
  const parts = [g.last_snapshot ? `Saved ${when(g.last_snapshot)}` : "No snapshot yet"];
  if (g.last_synced) parts.push(`synced ${when(g.last_synced)}`);
  return parts.join(" · ");
}

/** The Cloud saves page: Steam games (CloudRedirect) and other games (OpenSave). */
export const CloudSavesPage: FC = () => {
  const [st, setSt] = useState<CloudSavesState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showEmpty, setShowEmpty] = useState(false);
  const visible = usePanelVisible();
  const loading = useRef(false);

  const load = async (auto: boolean) => {
    if (loading.current) return;      // a slow answer (OpenSave busy) is not asked again on top
    loading.current = true;
    try {
      setSt(await cloudSaves(auto));
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      loading.current = false;
    }
  };
  useEffect(() => {
    void load(true);                 // once on opening: also asks the cloud when the last answer is old
    if (!visible) return;
    const id = setInterval(() => void load(false), 4000);
    return () => clearInterval(id);
  }, [visible]);

  if (!st) return <Info label={error ? "Backend not reachable" : "Loading…"}>{error}</Info>;

  const toggle = (key: string) => setOpen(open === key ? null : key);
  const where = st.provider_label ?? "The cloud";
  const run = async (key: string, fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      toast(String(e));
    } finally {
      setBusy(null);
      await load(false);
    }
  };
  const check = () =>
    run("check", async () => {
      const r = await cloudSavesCheck();
      if (!r.started && !r.checking) toast("The cloud cannot be checked right now.");
    });

  const os = st.opensave;
  const top = st.games.filter((g) => hasSave(g) || g.level === "fail");
  const withSaves = [...top.filter((g) => g.level === "fail").sort(byName), ...top.filter((g) => g.level !== "fail").sort(byName)];
  const noSaves = st.games.filter((g) => !top.includes(g)).sort(byName);
  const row = (g: CloudGame, i: number) => {
    const key = `cr-${g.appid ?? `x${i}`}`;
    const line = (
      <>
        {steamLine(g, where)}
        <br />
        <WhereTag g={g} where={where} />
      </>
    );
    return (
      <GameRow key={key} mark={steamMark(g)} name={gameName(g)} line={line} open={open === key} toggle={() => toggle(key)}>
        <Details lines={steamDetails(g, where)} />
      </GameRow>
    );
  };
  return (
    <>
      <PanelSection title="Steam games · CloudRedirect">
        {!st.installed ? (
          <Info label="CloudRedirect is not installed">
            It syncs the saves of the games in SLSsteam's AdditionalApps to your cloud. Once it is set up, each game
            shows here.
          </Info>
        ) : (
          <>
            <Stats>
              <Stat label="With saves" value={withSaves.filter(hasSave).length} size={34} sub={`of ${plural(st.games.length, "game")}`} />
              <Stat
                label="Need a look"
                value={st.summary.problems + st.problems.length}
                size={34}
                sub={st.summary.problems + st.problems.length ? "see below" : "all fine"}
              />
            </Stats>
            {st.problems.length > 0 && (
              <Info label="CloudRedirect" warn focusable>
                {st.problems.map((p, i) => (
                  <div key={i}>{p}</div>
                ))}
              </Info>
            )}
            {st.games.length === 0 && (
              <Info label="No games">Add games to AdditionalApps in SLSsteam's config.yaml, one per line (- 1234).</Info>
            )}
            {withSaves.map(row)}
            {noSaves.length > 0 && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  description={showEmpty ? undefined : "Games in your list that have nothing synced yet."}
                  onClick={() => setShowEmpty(!showEmpty)}
                >
                  {`No saves yet (${noSaves.length})  ${showEmpty ? "▴" : "▾"}`}
                </ButtonItem>
              </PanelSectionRow>
            )}
            {showEmpty && noSaves.map(row)}
            {st.can_check && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={st.checking || busy === "check"}
                  description={
                    st.cloud_error
                      ? `Last check: ${st.cloud_error}`
                      : st.cloud_at
                        ? `Checked against ${where} ${when(st.cloud_at)}. Only reads; nothing in the cloud changes.`
                        : "Only reads; nothing in the cloud changes."
                  }
                  onClick={() => void check()}
                >
                  {st.checking ? "Checking the cloud…" : "Check the cloud now"}
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>

      <OpenSaveSection os={os} open={open} toggle={toggle} busy={busy} run={run} />
    </>
  );
};

const OpenSaveSection: FC<{
  os: OpenSaveState;
  open: string | null;
  toggle: (key: string) => void;
  busy: string | null;
  run: (key: string, fn: () => Promise<void>) => Promise<void>;
}> = ({ os, open, toggle, busy, run }) => {
  const cloudReady = !!os.cloud?.ready;
  const cloudName = os.cloud?.provider ? os.cloud.provider.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "the cloud";
  const peers = os.peers ?? 0;

  const start = () =>
    run("start", async () => {
      const r = await opensaveStart();
      toast(r.ok ? (r.already ? "OpenSave is running." : "OpenSave started.") : (r.error ?? "OpenSave did not start."));
    });
  const backup = (g: OpenSaveGame) =>
    run(`b-${g.id}`, async () => {
      const r = await opensaveBackup(g.id);
      toast(
        r.ok
          ? r.uploaded
            ? `${g.name}: ${plural(r.uploaded, "snapshot")} backed up to ${cloudName}.`
            : `${g.name}: already backed up in ${cloudName}.`
          : `${g.name}: ${r.error}`,
      );
    });
  const SYNC_SAID: Record<string, string> = {
    queued: "a sync is running; this one follows it",
    changed: "synced",
    "in-sync": "already the same on your devices",
    conflict: "two devices changed it: choose which to keep in the OpenSave app",
    offline: "none of your other devices is online",
    paused: "syncing is paused in OpenSave",
    held: "held back: its save files were deleted here (answer in the OpenSave app)",
  };
  const sync = (g: OpenSaveGame) =>
    showModal(
      <ConfirmModal
        strTitle={`Sync ${g.name}?`}
        strDescription="OpenSave compares this save with your other devices. When one of them has a newer save, it replaces the one here; OpenSave keeps the earlier version in its history, to roll back in its app."
        strOKButtonText="Sync"
        onOK={() =>
          void run(`s-${g.id}`, async () => {
            const r = await opensaveSync(g.id);
            const said = SYNC_SAID[(r.ok ? r.outcome : r.reason) ?? ""] ?? r.error ?? "done";
            toast(`${g.name}: ${said}.`);
          })
        }
      />,
    );
  const untrack = (g: OpenSaveGame) =>
    showModal(
      <ConfirmModal
        strTitle={`Stop tracking ${g.name} in OpenSave?`}
        strDescription="CloudRedirect looks after this Steam game. OpenSave stops watching it; its save files and OpenSave's snapshots stay where they are."
        strOKButtonText="Stop tracking"
        onOK={() =>
          void run(`u-${g.id}`, async () => {
            const r = await opensaveUntrack(g.id);
            toast(r.ok ? `${g.name}: OpenSave no longer tracks it.` : `${g.name}: ${r.error}`);
          })
        }
      />,
    );

  return (
    <PanelSection title="Other games · OpenSave">
      {!os.running ? (
        os.installed ? (
          <>
            <Info label="OpenSave is not running">Its background service starts here; it keeps running after the menu closes.</Info>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy === "start"} onClick={() => void start()}>
                {busy === "start" ? "Starting…" : "Start OpenSave"}
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : (
          <Info label="OpenSave is not installed">
            For emulators and non-Steam games. In Desktop Mode, install OpenSave.flatpak from the Releases page of
            github.com/Liquid-co/OpenSave, connect a cloud in its app and track your games. They show here.
          </Info>
        )
      ) : (
        <>
          {os.error && <Info label="OpenSave" warn>{os.error}</Info>}
          <Info label={cloudReady ? `Backs up to ${cloudName}` : "No cloud backup"}>
            {cloudReady
              ? "Every new save is copied there by OpenSave itself."
              : "Set one up in the OpenSave app (Desktop Mode) to keep copies off this device."}
            {peers > 0 && ` ${plural(peers, "other device")}, ${os.peers_online ?? 0} online.`}
            {os.paused && " Syncing is paused."}
          </Info>
          {os.games.length === 0 && <Info label="No games tracked">Track your emulator and non-Steam saves in the OpenSave app.</Info>}
          {os.games.map((g) => {
            const key = `os-${g.id}`;
            return (
              <GameRow key={key} mark={osMark(g)} name={g.name} line={osLine(g)} open={open === key} toggle={() => toggle(key)}>
                <Details
                  lines={[
                    g.last_snapshot ? `Last snapshot ${when(g.last_snapshot)}.` : "No snapshot yet: OpenSave makes one when the game saves.",
                    g.last_synced ? `Last synced with another device ${when(g.last_synced)}.` : null,
                  ]}
                />
                {cloudReady && (
                  <PanelSectionRow>
                    <ButtonItem
                      layout="below"
                      disabled={!!busy}
                      description="Uploads only; the save on this device does not change."
                      onClick={() => void backup(g)}
                    >
                      {busy === `b-${g.id}` ? "Backing up…" : `Back up to ${cloudName} now`}
                    </ButtonItem>
                  </PanelSectionRow>
                )}
                {peers > 0 && (
                  <PanelSectionRow>
                    <ButtonItem layout="below" disabled={!!busy || g.playing} onClick={() => sync(g)}>
                      {busy === `s-${g.id}` ? "Syncing…" : g.playing ? "Sync (after you stop playing)" : "Sync with my other devices"}
                    </ButtonItem>
                  </PanelSectionRow>
                )}
              </GameRow>
            );
          })}
          {os.steam_games.length > 0 && (
            <>
              <Info label="OpenSave also tracks Steam games" warn focusable>
                CloudRedirect looks after Steam games, and two tools on one save can overwrite each other. These are
                never synced or backed up from here: {os.steam_games.map((g) => g.name).join(", ")}.
              </Info>
              {os.steam_games.map((g) => (
                <PanelSectionRow key={g.id}>
                  <ButtonItem layout="below" disabled={!!busy} onClick={() => untrack(g)}>
                    {busy === `u-${g.id}` ? "Stopping…" : `Stop tracking ${g.name} in OpenSave`}
                  </ButtonItem>
                </PanelSectionRow>
              ))}
            </>
          )}
          <Info label="Only non-Steam games">Emulators and non-Steam games sync here; Steam games stay with CloudRedirect.</Info>
        </>
      )}
    </PanelSection>
  );
};

/** Says so once when a game's saves did not reach the cloud (an upload failed, files missing). */
export function watchCloudSaves(): () => void {
  const tell = () =>
    void cloudSavesAlerts()
      .then((alerts) => {
        for (const a of alerts.slice(0, 3)) toast(`${gameName(a)}: ${a.problem} See Device → Cloud saves.`);
      })
      .catch(() => undefined);
  const first = setTimeout(tell, 90000);
  const every = setInterval(tell, 120000);
  return () => {
    clearTimeout(first);
    clearInterval(every);
  };
}
