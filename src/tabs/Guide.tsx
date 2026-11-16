import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { FC, useEffect, useRef } from "react";

import { Info } from "../ui";

const KEY = "lgo-guide-seen";

/** Whether Getting started was closed once. Without storage it is not pushed every time. */
export function guideSeen(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return true;
  }
}

function markSeen() {
  try {
    window.localStorage.setItem(KEY, "1");
  } catch {
    /* no storage */
  }
}

/** Getting started, at the top of the Overview tab: shown by itself until closed once,
 *  and again from the button at the end of the tab. */
export const GuideSection: FC<{
  go: (tab: string) => void;
  close: () => void;
  reopened?: boolean;
}> = ({ go, close, reopened }) => {
  // Opened again from the end of the tab: bring it into view.
  const top = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (reopened) top.current?.scrollIntoView({ block: "start" });
  }, [reopened]);
  const done = () => {
    markSeen();
    close();
  };
  const open = (tab: string) => {
    markSeen();
    go(tab);
  };
  return (
    <div ref={top}>
      <PanelSection title="Getting started">
        <Info focusable label="1 · Power and battery">
          Power tab: turn on "Manage power". For a set frame rate at the least
          power, choose Power mode "Custom (set the watts)", then "Auto TDP for
          a frame rate" and a Target frame rate. "Separate settings per game"
          keeps one setup per game.
        </Info>
        <Info focusable label="2 · Smooth frame rate">
          While a game runs, pick a cap for it under "Smooth frame rate" (Power
          tab). The screen rate is set to match, so frames are evenly paced.
          Restart the game once after the first choice.
        </Info>
        <Info focusable label="3 · Battery playtime">
          On battery with a game running, choose a Goal, for example 7 hours.
          Power, then the frame rate, are lowered only as far as needed, never
          below your lowest frame rate.
        </Info>
        <Info focusable label="4 · The rest">
          Fan, Lights, Controls and Gyro work on their own tabs. Settings are
          saved and come back after sleep and restarts.
        </Info>
        <Info focusable label="With Frame Suite">
          Nothing to link: MAKO and lsfg-vk frame generation in a game are
          picked up by Smooth mode, Auto TDP and Battery playtime by themselves.
        </Info>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => open("Power")}>
            Open the Power tab
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={done}>
            Got it, close this
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </div>
  );
};
