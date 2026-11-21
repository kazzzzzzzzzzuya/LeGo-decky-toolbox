import { DialogButton, Field, Focusable, PanelSection, PanelSectionRow } from "@decky/ui";
import { useQuickAccessVisible } from "@decky/api";
import { FC, ReactNode, useEffect, useRef, useState } from "react";
import { FaBalanceScale, FaLeaf, FaRocket } from "react-icons/fa";

import { ModeId, ModeInfo, modeInfo, SystemState, systemState } from "../backend";
import { applyMode, hm, Mode, modeById, MODES, modeSets } from "../modes";
import { useStore } from "../store";
import { Info, NavRow } from "../ui";
import type { Updates } from "../backend";
import { UpdateBanner } from "./Updates";

const ICONS: Record<ModeId, ReactNode> = {
  battery: <FaLeaf size={20} />,
  balanced: <FaBalanceScale size={20} />,
  smooth: <FaRocket size={20} />,
};

/** One big reading: label over a dot-matrix number and its unit. */
const Reading: FC<{ label: string; value: string | number; unit: string }> = ({ label, value, unit }) => (
  <div style={{ flex: 1, minWidth: 0 }}>
    <div className="dot-label">{label}</div>
    <div className="dot-num" style={{ fontSize: 30, lineHeight: 1, marginTop: 3, whiteSpace: "nowrap" }}>
      {value}
      <span style={{ fontSize: 12, color: "#8a8a8a", marginLeft: 2 }}>{unit}</span>
    </div>
  </div>
);

/** The running game in plain words, the alert when something broke, and the one choice per game. */
export const GameTab: FC<{ go: (tab: string) => void; updates: Updates | null }> = ({ go, updates }) => {
  const { state } = useStore();
  const appId = state?.status.app.id ?? null;
  const [info, setInfo] = useState<ModeInfo | null>(null);
  const [sys, setSys] = useState<SystemState | null>(null);
  const [busy, setBusy] = useState<ModeId | null>(null);
  const working = useRef(false);

  const visible = useQuickAccessVisible();
  useEffect(() => {
    if (!visible) return;
    let alive = true;
    const load = () => {
      modeInfo(appId)
        .then((i) => alive && setInfo(i))
        .catch(() => undefined);
      systemState()
        .then((s) => alive && setSys(s))
        .catch(() => undefined);
    };
    load();
    const id = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [appId, visible]);

  if (!state) return null;
  const { status } = state;
  const app = status.app;
  const name = app.name || (appId != null ? `App ${appId}` : "");
  const batt = status.battery.info;
  const charging = batt ? batt.status !== "Discharging" : false;
  const before = status.fps_before_menu ?? null;
  const fps = before ?? status.power.auto.fps;
  const watts = batt?.watts != null && !charging ? batt.watts : status.power.tdp;
  const mode = info?.mode ?? null;

  const choose = async (m: Mode) => {
    if (appId == null || working.current) return;
    working.current = true;
    setBusy(m.id);
    try {
      const next = await applyMode(appId, name, m);
      if (next) setInfo(next);
    } finally {
      working.current = false;
      setBusy(null);
    }
  };

  // Only what needs a look: the first problem the plugin hit, or a Steam mod that stopped loading.
  const problem = Object.values(status.errors).find(Boolean);
  const steamFail = sys?.steam?.overall === "fail" ? sys.steam.items.find((i) => !i.ok && i.id !== "steam") : null;

  return (
    <>
      <UpdateBanner updates={updates} />
      <PanelSection>
        <PanelSectionRow>
          <Field bottomSeparator="none" padding="none" childrenLayout="below" childrenContainerWidth="max">
            <div className="dot-card dot-grid" style={{ width: "100%" }}>
              <div className="dot-label">{appId != null ? "Now playing" : "No game running"}</div>
              {appId != null && <div style={{ fontSize: 16, fontWeight: 600, marginTop: 3 }}>{name}</div>}
              <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
                {appId != null && (
                  <Reading label={before != null ? "Before menu" : "Frame rate"} value={fps != null ? Math.round(fps) : "–"} unit="fps" />
                )}
                <Reading label={charging ? "TDP" : "Power"} value={watts != null ? Math.round(watts) : "–"} unit="W" />
                <Reading
                  label={charging ? "Battery" : "Left"}
                  value={charging ? (batt?.percent ?? "–") : hm(batt?.minutes != null ? batt.minutes / 60 : null)}
                  unit={charging ? "%" : "h"}
                />
              </div>
              <div style={{ fontSize: 12.5, color: "#8a8a8a", marginTop: 8 }}>
                {[
                  status.fan.temp != null ? `${status.fan.temp} °C` : null,
                  batt ? `battery ${batt.percent} %` : null,
                  charging ? (batt?.status === "Full" ? "full" : "charging") : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
          </Field>
        </PanelSectionRow>
        {(problem || steamFail) && (
          <NavRow
            warn
            label={steamFail ? `${steamFail.label} isn't working` : "Something needs a look"}
            sub={steamFail ? (sys?.steam?.updated_since_good ? "Steam was updated" : steamFail.detail) : problem}
            onClick={() => go("Device")}
          />
        )}
      </PanelSection>

      <PanelSection>
        {appId == null ? (
          <Info label="Start a game">Then choose here how it runs: longest battery, balanced or smoothest.</Info>
        ) : (
          <>
            <div className="dot-title" style={{ fontSize: 16, margin: "2px 4px 8px" }}>
              Run this game for…
            </div>
            <PanelSectionRow>
              <Focusable flow-children="vertical" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {MODES.map((m) => (
                  <DialogButton
                    key={m.id}
                    className={m.id === mode ? "lgo-mode on" : "lgo-mode"}
                    onClick={() => void choose(m)}
                  >
                    <span className="lgo-mode-icon">{ICONS[m.id]}</span>
                    <span style={{ minWidth: 0, flex: 1, textAlign: "left" }}>
                      <span style={{ display: "block", fontSize: 15, fontWeight: 600 }}>
                        {busy === m.id ? "Setting up…" : m.label}
                      </span>
                      <span className="lgo-mode-line">{m.line}</span>
                    </span>
                    <span style={{ textAlign: "right", flex: "none" }}>
                      <span className="dot-num" style={{ display: "block", fontSize: 18 }}>
                        {hm(info?.hours?.[m.id])}
                      </span>
                      <span className="lgo-mode-line" style={{ fontSize: 10 }}>
                        hours
                      </span>
                    </span>
                  </DialogButton>
                ))}
              </Focusable>
            </PanelSectionRow>
            {modeById(mode) ? (
              <Info label={`${modeById(mode)!.label} sets`}>
                {modeSets(modeById(mode)!, state).join(" · ")}. Remembered for this game; fine-tune in More.
              </Info>
            ) : (
              <Info label="No mode yet">
                This game runs with your own settings. Hours appear after playing a while in a mode.
              </Info>
            )}
          </>
        )}
      </PanelSection>
    </>
  );
};
