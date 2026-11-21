import { gamepadDialogClasses as dlg, gamepadSliderClasses as sld } from "@decky/ui";

/* Dot theme: true black, white, grey, one red accent, dot-matrix numbers.
 * Shared by Legion Go Toolbox and Frame Suite (same file in both repositories).
 * Steam's own controls are reached through Decky's class maps, so a Steam update that renames
 * them only drops the restyle (Steam's default look), never the controls. */

export const DOT = {
  bg: "#000000",
  card: "#0f0f0f",
  line: "#262626",
  line2: "#3a3a3a",
  text: "#f2f2f2",
  mute: "#8a8a8a",
  red: "#d71921",
};

// Doto (dot-matrix), weight 900, Latin subset. SIL Open Font License 1.1,
// Copyright 2024 The Doto Project Authors (github.com/oliverlalan/Doto).
const DOTO = "data:font/woff2;base64,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";

const sel = (root: string, cls: string | undefined, rest = "") => (cls ? `${root} .${cls}${rest}` : "");
const rules = (list: [string, string][]) => list.filter(([s]) => s).map(([s, b]) => `${s} { ${b} }`).join("\n");

/** Global CSS of the theme, scoped to the element with class `root` (e.g. ".lgo-toolbox-tabs"). */
export function dotCss(root: string): string {
  const { bg, card, line, line2, text, mute, red } = DOT;
  const toggle = dlg?.Toggle, on = dlg?.On;
  return `
@font-face { font-family: "LgoDoto"; src: url(${DOTO}) format("woff2"); font-weight: 900; font-display: block; }
${root} { background: ${bg}; color: ${text}; }
${root} .dot-num, ${root} .dot-title { font-family: "LgoDoto", monospace; font-weight: 900; letter-spacing: 1px; }
${root} .dot-label { font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: ${mute}; }
${root} .dot-card { box-sizing: border-box; width: 100%; background: ${card}; border: 1px solid ${line}; border-radius: 20px; padding: 10px 14px; margin: 4px 0; }
${root} .dot-grid { background-image: radial-gradient(#2c2c2c 1px, transparent 1.2px); background-size: 9px 9px; }
${root} .DialogButton { background: transparent !important; border: 1px solid ${line2} !important; border-radius: 16px !important; color: ${text} !important; box-shadow: none !important; }
${root} .DialogButton.gpfocus, ${root} .DialogButton:hover { background: ${text} !important; color: #000 !important; border-color: ${text} !important; }
${root} .DialogButton:disabled { opacity: .45; }
${rules([
    [sel(root, dlg?.FieldDescription), `color: ${mute} !important;`],
    [sel(root, dlg?.FieldLabel), `color: ${text};`],
    [sel(root, dlg?.WithBottomSeparatorStandard, "::after"), `background: #1c1c1c !important;`],
    [sel(root, dlg?.WithBottomSeparatorThick, "::after"), `background: #1c1c1c !important;`],
    [sel(root, dlg?.ToggleRail), `background: transparent !important; border: 1.5px solid ${line2}; border-radius: 13px; box-sizing: border-box;`],
    [sel(root, dlg?.ToggleSwitch), `background: #5a5a5a !important; box-shadow: none !important;`],
    [toggle && on ? `${root} .${toggle}.${on} .${dlg.ToggleRail}` : "", `background: ${text} !important; border-color: ${text};`],
    [toggle && on ? `${root} .${toggle}.${on} .${dlg.ToggleSwitch}` : "", `background: #000 !important;`],
    [sel(root, sld?.SliderTrack), `background: radial-gradient(#555 1px, transparent 1.3px) 0 50% / 6px 2px repeat-x, transparent !important; box-shadow: none !important;`],
    [sel(root, sld?.SliderHandle), `background: ${text} !important; box-shadow: 0 0 0 4px ${bg} !important; border: none !important;`],
    [sel(root, sld?.SliderNotchTick), `background: ${line2} !important;`],
    [sel(root, sld?.TickActive), `background: ${text} !important;`],
    [sel(root, sld?.DescriptionValue), `font-family: "LgoDoto", monospace; font-weight: 900; font-size: 16px; color: ${text};`],
  ])}
/* Fallbacks by name pattern: Steam's class names read "module_Name_hash", so these hold even
   when Decky's class map is out of date (seen: the toggle stayed Steam's blue). */
${root} [class*="_ToggleRail_"] { background: transparent !important; border: 1.5px solid ${line2}; border-radius: 13px; box-sizing: border-box; }
${root} [class*="_ToggleSwitch_"] { background: #5a5a5a !important; box-shadow: none !important; }
${root} [class*="_On_"] [class*="_ToggleRail_"], ${root} [class*="_On_"] > [class*="_ToggleRail_"] { background: ${text} !important; border-color: ${text}; }
${root} [class*="_On_"] [class*="_ToggleSwitch_"] { background: #000 !important; }
${root} [class*="_SliderTrack_"] { background: radial-gradient(#555 1px, transparent 1.3px) 0 50% / 6px 2px repeat-x, transparent !important; box-shadow: none !important; }
${root} [class*="_SliderHandle_"] { background: ${text} !important; box-shadow: 0 0 0 4px ${bg} !important; border: none !important; }
${root} [class*="_FieldDescription_"] { color: ${mute} !important; }
${root} .dot-red { color: ${red}; }
${root} .DialogButton.dot-pill.on { background: ${red} !important; border-color: ${red} !important; color: #fff !important; }
${root} .dot-reddot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: ${red}; margin-right: 6px; vertical-align: middle; }
`;
}
