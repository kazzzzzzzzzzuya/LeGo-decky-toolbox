import { Router, Tabs, gamepadTabbedPageClasses, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { FC, ReactNode, useEffect, useRef, useState } from "react";
import { FaBolt, FaFan, FaGamepad, FaHome, FaLightbulb, FaSlidersH } from "react-icons/fa";
import { MdScreenRotation } from "react-icons/md";
import { GiToolbox } from "react-icons/gi";

import { onResume, onSuspend, setRunningApp } from "./backend";
import { flushWrites, load, refreshStatus, useStore } from "./store";
import { ControlsTab } from "./tabs/Controls";
import { FanTab } from "./tabs/Fan";
import { GyroTab } from "./tabs/Gyro";
import { SteamGyroSection } from "./tabs/SteamGyro";
import { HomeTab } from "./tabs/Home";
import { LightsTab } from "./tabs/Lights";
import { PowerTab } from "./tabs/Power";
import { SystemTab, watchSteamMods } from "./tabs/System";
import { PLUGIN_NAME } from "./ui";

// Blue and white, in the style of MAKO: the tabs are a row of icon tiles, the current one filled
// blue; each tab starts with its name, centred over a blue and white line; notes sit in soft boxes.
const BLUE = "#3d9bff";
const TAB_STYLES = `
  .lgo-toolbox-tabs > div > div:first-child {
    background: #0b1219;
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
    padding: 4px 6px;
  }
  .lgo-toolbox-tabs [role="tab"] {
    flex: 1 1 0;
    min-width: 0;
    height: 34px;
    box-sizing: border-box;
    padding-left: 4px !important;
    padding-right: 4px !important;
    display: flex !important;
    align-items: center;
    justify-content: center;
    border-radius: 9px !important;
    background: rgba(255, 255, 255, 0.05) !important;
    border: 1px solid rgba(61, 155, 255, 0.35) !important;
    color: #f5f8fc !important;
  }
  .lgo-toolbox-tabs [role="tab"] svg {
    display: block;
    margin: 0;
    color: ${BLUE};
  }
  /* Steam dims the tab row while focus is in the page below: keep it as it is. */
  .lgo-toolbox-tabs [role="tablist"],
  .lgo-toolbox-tabs [role="tab"] {
    opacity: 1 !important;
    filter: none !important;
  }
  .lgo-toolbox-tabs .lgo-header {
    text-align: center;
    font-weight: 700;
    font-size: 15px;
    color: #f5f8fc;
    padding: 8px 0 6px;
    margin: 2px 0 6px;
    border-bottom: 3px solid transparent;
    border-image: linear-gradient(90deg, rgba(61,155,255,0.15), ${BLUE}, rgba(255,255,255,0.85), ${BLUE}, rgba(61,155,255,0.15)) 1;
  }
  .lgo-toolbox-tabs .lgo-info {
    box-sizing: border-box;
    width: 100%;
    padding: 6px 10px;
    border-radius: 8px;
    border: 1px solid rgba(61, 155, 255, 0.30);
    border-left: 3px solid ${BLUE};
    background: rgba(61, 155, 255, 0.08);
    margin: 3px 0;
  }
  .lgo-toolbox-tabs .lgo-info.warn {
    border-color: rgba(242, 193, 78, 0.45);
    border-left-color: #f2c14e;
    background: rgba(242, 193, 78, 0.08);
  }
  .lgo-toolbox-tabs .lgo-info-label {
    font-size: 14px;
    font-weight: 600;
    color: #f5f8fc;
  }
  .lgo-toolbox-tabs .lgo-info-text {
    font-size: 12px;
    line-height: 1.35;
    color: #b8c4d2;
    margin-top: 2px;
    overflow-wrap: anywhere;
  }
`;

// The current tab, filled blue with a white icon (marked through its own title, whatever Steam's
// generated class names are, and through Steam's "Selected" class).
const CURRENT_TAB_LOOK = `
    background: ${BLUE} !important;
    border-color: ${BLUE} !important;
    box-shadow: 0 0 10px rgba(61, 155, 255, 0.45);
    opacity: 1 !important;
    filter: none !important;
`;
const currentTabStyles = () => {
  let css = `.lgo-toolbox-tabs [role="tab"]:has(.lgo-tab-current) {${CURRENT_TAB_LOOK}}\n`;
  css += `.lgo-toolbox-tabs .lgo-tab-current, .lgo-toolbox-tabs .lgo-tab-current svg { color: #ffffff !important; }\n`;
  const selected = gamepadTabbedPageClasses?.Selected;
  const tab = gamepadTabbedPageClasses?.Tab;
  if (selected && tab) {
    css += `.lgo-toolbox-tabs .${tab}.${selected} {${CURRENT_TAB_LOOK}}\n`;
    css += `.lgo-toolbox-tabs .${tab}.${selected} svg { color: #ffffff !important; }\n`;
  }
  return css;
};

const TAB_NAMES: Record<string, string> = {
  Home: "Overview",
  Power: "Power and frame rate",
  Fan: "Fan",
  Lights: "Lights",
  Controls: "Controls",
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
    { id: "Lights", title: icon("Lights", <FaLightbulb size={18} />), content: wrap("Lights", <LightsTab />) },
    { id: "Controls", title: icon("Controls", <FaGamepad size={18} />), content: wrap("Controls", <ControlsTab />) },
    { id: "Gyro", title: icon("Gyro", <MdScreenRotation size={18} />), content: wrap(
        "Gyro",
        <>
          <SteamGyroSection />
          <GyroTab />
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
        <GiToolbox style={{ color: BLUE }} />
        {PLUGIN_NAME}
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
