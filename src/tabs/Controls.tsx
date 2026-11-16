import { DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { FC } from "react";

import type { RemapButton } from "../backend";
import { update, useStore } from "../store";
import { ErrorRow, Unavailable } from "../ui";

const BUTTONS: { key: RemapButton; label: string }[] = [
  { key: "Y1", label: "Y1 (left back, upper)" },
  { key: "Y2", label: "Y2 (left back, lower)" },
  { key: "Y3", label: "Y3 (right back)" },
  { key: "M2", label: "M2 (right side, upper)" },
  { key: "M3", label: "M3 (right side, lower)" },
];

// Every combination: what the two Legion buttons become, and which of View (two squares) and Menu (three
// lines) opens Steam; the other one opens Quick Access.
type Layout = "steam_menu" | "steam_view" | "lview_steam_menu" | "lmenu_steam_view";
const LAYOUTS: { data: Layout; label: string; legion: string; steam: string; qam: string }[] = [
  { data: "steam_view", label: "L View, R Menu · View = Steam", legion: "View / Menu", steam: "View", qam: "Menu" },
  { data: "lview_steam_menu", label: "L View, R Menu · Menu = Steam (default)", legion: "View / Menu", steam: "Menu", qam: "View" },
  { data: "steam_menu", label: "L Menu, R View · Menu = Steam", legion: "Menu / View", steam: "Menu", qam: "View" },
  { data: "lmenu_steam_view", label: "L Menu, R View · View = Steam", legion: "Menu / View", steam: "View", qam: "Menu" },
];
const ICON: Record<string, string> = { View: "View (two squares)", Menu: "Menu (three lines)" };

const ACTIONS: { data: string; label: string }[] = [
  { data: "none", label: "No action" },
  { data: "a", label: "A" },
  { data: "b", label: "B" },
  { data: "x", label: "X" },
  { data: "y", label: "Y" },
  { data: "lb", label: "LB" },
  { data: "rb", label: "RB" },
  { data: "lt", label: "LT" },
  { data: "rt", label: "RT" },
  { data: "view", label: "View" },
  { data: "menu", label: "Menu" },
  { data: "dpad_up", label: "D-pad up" },
  { data: "dpad_down", label: "D-pad down" },
  { data: "dpad_left", label: "D-pad left" },
  { data: "dpad_right", label: "D-pad right" },
  { data: "ls_click", label: "Left stick click" },
  { data: "rs_click", label: "Right stick click" },
  { data: "ls_up", label: "Left stick up" },
  { data: "ls_down", label: "Left stick down" },
  { data: "ls_left", label: "Left stick left" },
  { data: "ls_right", label: "Left stick right" },
  { data: "rs_up", label: "Right stick up" },
  { data: "rs_down", label: "Right stick down" },
  { data: "rs_left", label: "Right stick left" },
  { data: "rs_right", label: "Right stick right" },
];

export const ControlsTab: FC = () => {
  const { state } = useStore();
  if (!state) return null;
  const { caps, settings, status } = state;
  const c = settings.controls;

  return (
    <>
      <PanelSection title="Menu buttons">
        {!caps.swap_menu.available && !c.swap_menu ? (
          <Unavailable cap={caps.swap_menu} what="Swapping the menu buttons" />
        ) : (
          <>
            <PanelSectionRow>
              <ToggleField
                label="Swap menu buttons"
                description={(() => {
                  const l = LAYOUTS.find((x) => x.data === c.swap_layout) ?? LAYOUTS[1];
                  return `Legion L / Legion R become ${l.legion}. The ${ICON[l.steam]} button opens Steam, the ${ICON[l.qam]} button Quick Access.`;
                })()}
                checked={c.swap_menu}
                onChange={(v) => update({ controls: { swap_menu: v } })}
              />
            </PanelSectionRow>
            {c.swap_menu && (
              <PanelSectionRow>
                <DropdownItem
                  label="Layout"
                  description="Which button opens Steam: pick the one that matches where you want it on your controller."
                  rgOptions={LAYOUTS.map((l) => ({ data: l.data, label: l.label }))}
                  selectedOption={c.swap_layout}
                  onChange={(o) =>
                    update({ controls: { swap_layout: o.data as Layout } })
                  }
                />
              </PanelSectionRow>
            )}
            <ErrorRow message={status.errors.swap_menu} />
          </>
        )}
      </PanelSection>

      <PanelSection title="Back buttons">
        {!caps.remap.available ? (
          <Unavailable cap={caps.remap} what="Button remapping" />
        ) : (
          <>
            <PanelSectionRow>
              <ToggleField
                label="Remap back buttons"
                description="Stored in the controllers themselves. Steam still sees the back buttons too, so leave them unassigned in Steam Input for a game where you use this."
                checked={c.remap_managed}
                onChange={(v) => update({ controls: { remap_managed: v } })}
              />
            </PanelSectionRow>
            {c.remap_managed &&
              BUTTONS.map((b) => (
                <PanelSectionRow key={b.key}>
                  <DropdownItem
                    label={b.label}
                    rgOptions={ACTIONS}
                    selectedOption={c.remap[b.key]}
                    onChange={(o) => update({ controls: { remap: { [b.key]: o.data as string } } })}
                  />
                </PanelSectionRow>
              ))}
            <PanelSectionRow>
              <ToggleField
                label="Touchpad"
                description="The touchpad on the right controller."
                checked={c.touchpad ?? true}
                onChange={(v) => update({ controls: { touchpad: v } })}
              />
            </PanelSectionRow>
            <ErrorRow message={status.errors.remap} />
          </>
        )}
      </PanelSection>
    </>
  );
};
