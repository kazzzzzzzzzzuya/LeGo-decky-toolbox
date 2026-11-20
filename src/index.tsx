import { Router, Tabs, gamepadTabbedPageClasses, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { FC, ReactNode, useEffect, useRef, useState } from "react";
import { FaBolt, FaFan, FaGamepad, FaHome, FaSlidersH } from "react-icons/fa";
import { MdScreenRotation } from "react-icons/md";
import { GiToolbox } from "react-icons/gi";

import { onResume, onSuspend, setRunningApp } from "./backend";
import { DOT, dotCss } from "./dot";
import { flushWrites, load, refreshStatus, useStore } from "./store";
import { ControlsTab } from "./tabs/Controls";
import { FanTab } from "./tabs/Fan";
import { GyroTab } from "./tabs/Gyro";
import { SteamGyroSection } from "./tabs/SteamGyro";
import { HomeTab } from "./tabs/Home";
import { LightsTab } from "./tabs/Lights";
import { PowerTab } from "./tabs/Power";
import { SystemTab, watchSteamMods } from "./tabs/System";
import { Fold, PLUGIN_NAME } from "./ui";

// Dot theme (see dot.ts): black, white and grey, one red accent; tabs are a row of round outlined
// icons, the current one filled white; each tab starts with its name in dot-matrix type.
const ROOT = ".lgo-toolbox-tabs";
const TAB_STYLES = `
  ${dotCss(ROOT)}
  .lgo-toolbox-tabs > div > div:first-child {
    background: #000;
    box-shadow: none;
    backdrop-filter: none;
  }
  .lgo-toolbox-tabs [role="tabpanel"] {
    padding-left: 8px !important;
    padding-right: 8px !important;
  }
  .lgo-toolbox-tabs .lgo-toolbox-tab-content {
    padding-bottom: 96px;
  }
  .lgo-toolbox-tabs [role="tablist"] {
    display: flex;
    flex-wrap: nowrap;
    justify-content: center;
    gap: 6px;
    padding: 4px 6px 8px;
  }
  .lgo-toolbox-tabs [role="tab"] {
    flex: 1 1 0;
    min-width: 0;
    height: 36px;
    box-sizing: border-box;
    padding-left: 4px !important;
    padding-right: 4px !important;
    display: flex !important;
    align-items: center;
    justify-content: center;
    border-radius: 18px !important;
    background: transparent !important;
    border: 1px solid ${DOT.line2} !important;
    color: ${DOT.text} !important;
  }
  .lgo-toolbox-tabs [role="tab"] svg {
    display: block;
    margin: 0;
    color: ${DOT.text};
  }
  /* Steam dims the tab row while focus is in the page below: keep it as it is. */
  .lgo-toolbox-tabs [role="tablist"],
  .lgo-toolbox-tabs [role="tab"] {
    opacity: 1 !important;
    filter: none !important;
  }
  .lgo-toolbox-tabs .lgo-header {
    font-family: "LgoDoto", monospace;
    font-weight: 900;
    font-size: 22px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: ${DOT.text};
    padding: 6px 4px 8px;
    margin: 2px 0 4px;
  }
  .lgo-toolbox-tabs .lgo-info {
    box-sizing: border-box;
    width: 100%;
    padding: 9px 14px;
    border-radius: 18px;
    border: 1px solid ${DOT.line};
    background: ${DOT.card};
    margin: 3px 0;
  }
  .lgo-toolbox-tabs .lgo-info.warn {
    border-color: rgba(215, 25, 33, 0.55);
  }
  .lgo-toolbox-tabs .lgo-info-label {
    font-size: 14px;
    font-weight: 600;
    color: ${DOT.text};
  }
  .lgo-toolbox-tabs .lgo-info.warn .lgo-info-label::before {
    content: "";
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: ${DOT.red};
    margin-right: 7px;
    vertical-align: middle;
  }
  .lgo-toolbox-tabs .lgo-info-text {
    font-size: 12px;
    line-height: 1.35;
    color: ${DOT.mute};
    margin-top: 2px;
    overflow-wrap: anywhere;
  }
  .lgo-toolbox-tabs .lgo-fold .DialogButton {
    border-style: dashed !important;
    border-radius: 20px !important;
    text-align: left;
  }
`;

// The current tab, filled white with a black icon (marked through its own title, whatever Steam's
// generated class names are, and through Steam's "Selected" class).
const CURRENT_TAB_LOOK = `
    background: ${DOT.text} !important;
    border-color: ${DOT.text} !important;
    box-shadow: none;
    opacity: 1 !important;
    filter: none !important;
`;
const currentTabStyles = () => {
  let css = `.lgo-toolbox-tabs [role="tab"]:has(.lgo-tab-current) {${CURRENT_TAB_LOOK}}\n`;
  css += `.lgo-toolbox-tabs .lgo-tab-current, .lgo-toolbox-tabs .lgo-tab-current svg { color: #000 !important; }\n`;
  const selected = gamepadTabbedPageClasses?.Selected;
  const tab = gamepadTabbedPageClasses?.Tab;
  if (selected && tab) {
    css += `.lgo-toolbox-tabs .${tab}.${selected} {${CURRENT_TAB_LOOK}}\n`;
    css += `.lgo-toolbox-tabs .${tab}.${selected} svg { color: #000 !important; }\n`;
  }
  return css;
};

const TAB_NAMES: Record<string, string> = {
  Home: "Overview",
  Power: "Power and frame rate",
  Fan: "Fan",
  Controls: "Buttons and lights",
  Gyro: "Gyro",
  System: "Sound, sleep and Steam",
};

const wrap = (id: string, content: ReactNode) => (
  <div className="lgo-toolbox-tab-content">
    <div className="lgo-header">{TAB_NAMES[id] ?? id}</div>
    {content}
  </div>
);

const Content: FC = () => {
  const { state, error } = useStore();
  const [tab, setTab] = useState("Home");

  // The gyro bars want quick updates; everything else is fine at 1 Hz.
  useEffect(() => {
    void load();
    return () => flushWrites();
  }, []);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const id = setInterval(
      () => {
        // The panel stays mounted while the menu is closed: do not poll then.
        const el = root.current;
        if (el && el.getClientRects().length === 0) return;
        void refreshStatus();
      },
      tab === "Gyro" ? 250 : 1000,
    );
    return () => clearInterval(id);
  }, [tab]);

  if (!state) {
    return (
      <div style={{ padding: "16px" }}>
        {error ? `Backend not reachable: ${error}` : "Loading…"}
      </div>
    );
  }

  const icon = (id: string, node: ReactNode) => (
    <span className={id === tab ? "lgo-tab-current" : undefined} style={{ display: "flex" }}>
      {node}
    </span>
  );
  const tabs = [
    { id: "Home", title: icon("Home", <FaHome size={18} />), content: wrap("Home", <HomeTab go={setTab} />) },
    { id: "Power", title: icon("Power", <FaBolt size={18} />), content: wrap("Power", <PowerTab />) },
    { id: "Fan", title: icon("Fan", <FaFan size={18} />), content: wrap("Fan", <FanTab />) },
    {
      id: "Controls",
      title: icon("Controls", <FaGamepad size={18} />),
      content: wrap(
        "Controls",
        <>
          <ControlsTab />
          <Fold id="lights" title="Lights" summary="Stick lights and the power-button light">
            <LightsTab />
          </Fold>
        </>,
      ),
    },
    { id: "Gyro", title: icon("Gyro", <MdScreenRotation size={18} />), content: wrap(
        "Gyro",
        <>
          <SteamGyroSection />
          <Fold
            id="gyro-emulators"
            title="Gyro for emulators"
            summary={state.gyro.settings.enabled ? "On: each controller is a motion device (DSU)" : "Dolphin, Switch emulators and others"}
          >
            <GyroTab />
          </Fold>
        </>,
      ),
    },
    { id: "System", title: icon("System", <FaSlidersH size={18} />), content: wrap("System", <SystemTab />) },
  ];

  return (
    <div
      ref={root}
      className="lgo-toolbox-tabs"
      style={{ height: "95%", width: "300px", position: "fixed", marginTop: "-12px", overflow: "hidden" }}
    >
      <style>{TAB_STYLES + currentTabStyles()}</style>
      <Tabs activeTab={tab} onShowTab={(next: string) => setTab(next)} tabs={tabs} />
    </div>
  );
};

/** Tell the backend which game runs, so per-game power profiles and the
 *  frame-rate measurement follow it even while the menu is closed. */
function watchRunningApp(): () => void {
  let last: string | null = null;
  const check = () => {
    try {
      const app = Router.MainRunningApp;
      const id = app?.appid != null ? Number(app.appid) : null;
      const key = id == null ? "none" : String(id);
      if (key === last) return;
      last = key;
      void setRunningApp(id, app?.display_name ?? "").catch(() => {
        last = null; // try again on the next tick
      });
    } catch {
      /* Steam not ready yet */
    }
  };
  check();
  const timer = setInterval(check, 2000);
  return () => clearInterval(timer);
}

interface Unregisterable {
  unregister: () => void;
}

function watchSleep(): () => void {
  const subs: Unregisterable[] = [];
  try {
    const sys = (window as unknown as { SteamClient?: { System?: Record<string, unknown> } })
      .SteamClient?.System;
    const hook = (name: string, fn: () => void) => {
      const register = sys?.[name] as ((cb: () => void) => Unregisterable) | undefined;
      if (typeof register === "function") subs.push(register.call(sys, fn));
    };
    hook("RegisterForOnSuspendRequest", () => void onSuspend().catch(() => undefined));
    hook("RegisterForOnResumeFromSuspend", () => void onResume().catch(() => undefined));
  } catch {
    /* older Steam client without these hooks */
  }
  return () => subs.forEach((s) => s?.unregister?.());
}

export default definePlugin(() => {
  const stopApp = watchRunningApp();
  const stopSleep = watchSleep();
  const stopMods = watchSteamMods();
  return {
    name: PLUGIN_NAME,
    titleView: (
      <div className={staticClasses.Title} style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: DOT.red, flex: "none" }} />
        <span style={{ fontFamily: "LgoDoto, monospace", fontWeight: 900, letterSpacing: 1, textTransform: "uppercase" }}>
          {PLUGIN_NAME}
        </span>
      </div>
    ),
    alwaysRender: true,
    content: <Content />,
    icon: <GiToolbox />,
    onDismount() {
      stopApp();
      stopSleep();
      stopMods();
      flushWrites();
    },
  };
});
