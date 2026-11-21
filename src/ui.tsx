import { ButtonItem, DialogButton, Field, Focusable, PanelSection, PanelSectionRow } from "@decky/ui";
import { FC, ReactNode, useState } from "react";
import { FaChevronLeft } from "react-icons/fa";

import type { Capability } from "./backend";

export const PLUGIN_NAME = "Legion Go Toolbox";
export const ACCENT = "#f2f2f2";   // Dot theme: white marks, red only for what needs a look
export const WARN = "#ff5a5f";

/** An information row, in a soft blue box (amber when it warns). The box sits inside the
 *  Field: Steam gives a Field negative side margins, so a box around one is overrun.
 *  focusable lets the controller stop on it, for longer text the panel should scroll to. */
export const Info: FC<{ label: ReactNode; children?: ReactNode; warn?: boolean; focusable?: boolean }> = ({
  label,
  children,
  warn,
  focusable,
}) => (
  <PanelSectionRow>
    <Field
      focusable={focusable}
      bottomSeparator="none"
      padding="none"
      childrenLayout="below"
      childrenContainerWidth="max"
    >
      <div className={warn ? "lgo-info warn" : "lgo-info"}>
        <div className="lgo-info-label">{label}</div>
        {children ? (
          <div className="lgo-info-text" style={warn ? { color: WARN } : undefined}>
            {children}
          </div>
        ) : null}
      </div>
    </Field>
  </PanelSectionRow>
);

/** Shown instead of a module's controls when the device cannot do it. */
export const Unavailable: FC<{ cap: Capability; what: string; children?: ReactNode }> = ({
  cap,
  what,
  children,
}) => (
  <PanelSectionRow>
    <Field
      label={`${what} is not available`}
      childrenLayout="below"
      description={
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <div>{cap.reason ?? "Not supported on this device."}</div>
          {children}
        </div>
      }
    />
  </PanelSectionRow>
);

export const ErrorRow: FC<{ message?: string }> = ({ message }) =>
  message ? (
    <Info label="Problem" warn>
      {message}
    </Info>
  ) : null;

/** r, g, b (0-255) <-> hue (0-360) and saturation (0-1) at full value. */
export function rgbToHueSat(rgb: [number, number, number]): { hue: number; sat: number } {
  const r = rgb[0] / 255;
  const g = rgb[1] / 255;
  const b = rgb[2] / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  let hue = 0;
  if (d > 0) {
    if (max === r) hue = ((g - b) / d) % 6;
    else if (max === g) hue = (b - r) / d + 2;
    else hue = (r - g) / d + 4;
    hue *= 60;
    if (hue < 0) hue += 360;
  }
  return { hue: Math.round(hue), sat: max === 0 ? 0 : d / max };
}

export function hueSatToRgb(hue: number, sat: number): [number, number, number] {
  const h = (((hue % 360) + 360) % 360) / 60;
  const c = sat;
  const x = c * (1 - Math.abs((h % 2) - 1));
  let rgb: [number, number, number];
  if (h < 1) rgb = [c, x, 0];
  else if (h < 2) rgb = [x, c, 0];
  else if (h < 3) rgb = [0, c, x];
  else if (h < 4) rgb = [0, x, c];
  else if (h < 5) rgb = [x, 0, c];
  else rgb = [c, 0, x];
  const m = 1 - c;
  return [
    Math.round((rgb[0] + m) * 255),
    Math.round((rgb[1] + m) * 255),
    Math.round((rgb[2] + m) * 255),
  ];
}

export function modeLabel(mode: string): string {
  switch (mode) {
    case "custom":
      return "Custom (set the watts)";
    case "low-power":
    case "quiet":
      return "Quiet";
    case "balanced":
      return "Balanced";
    case "balanced-performance":
      return "Balanced performance";
    case "performance":
      return "Performance";
    default:
      return mode.charAt(0).toUpperCase() + mode.slice(1).replace(/[-_]/g, " ");
  }
}

function rememberedOpen(id: string): boolean {
  try {
    return window.localStorage.getItem(`lgo-fold-${id}`) === "1";
  } catch {
    return false;
  }
}

/** A closed section: one row with its name and a one-line summary; selecting it shows the
 *  settings inside. Open or closed is remembered per section. */
export const Fold: FC<{ id: string; title: string; summary?: ReactNode; inline?: boolean; children: ReactNode }> = ({
  id,
  title,
  summary,
  inline,
  children,
}) => {
  const [open, setOpen] = useState(() => rememberedOpen(id));
  const toggle = () => {
    setOpen(!open);
    try {
      window.localStorage.setItem(`lgo-fold-${id}`, open ? "0" : "1");
    } catch {
      /* private storage is optional */
    }
  };
  const row = (
    <PanelSectionRow>
      <ButtonItem layout="below" description={open ? undefined : summary} onClick={toggle}>
        {title + (open ? "  ▴" : "  ▾")}
      </ButtonItem>
    </PanelSectionRow>
  );
  return (
    <>
      <div className="lgo-fold">{inline ? row : <PanelSection>{row}</PanelSection>}</div>
      {open && children}
    </>
  );
};

/** A big dot-matrix reading in a card: label, number, unit, an optional line under it. */
export const Stat: FC<{ label: string; value: ReactNode; unit?: string; sub?: ReactNode; size?: number }> = ({
  label,
  value,
  unit,
  sub,
  size = 52,
}) => (
  <div className="dot-card dot-grid" style={{ flex: 1, minWidth: 0 }}>
    <div className="dot-label">{label}</div>
    <div className="dot-num" style={{ fontSize: size, lineHeight: 0.95, marginTop: 4, whiteSpace: "nowrap" }}>
      {value}
      {unit && <span style={{ fontSize: Math.round(size * 0.38), color: "#8a8a8a", marginLeft: 4 }}>{unit}</span>}
    </div>
    {sub ? <div style={{ fontSize: 12, color: "#8a8a8a", marginTop: 4, lineHeight: 1.35 }}>{sub}</div> : null}
  </div>
);

/** One or two Stats side by side, as a panel row. */
export const Stats: FC<{ children: ReactNode }> = ({ children }) => (
  <PanelSectionRow>
    <Field bottomSeparator="none" padding="none" childrenLayout="below" childrenContainerWidth="max">
      <div style={{ display: "flex", gap: 8, width: "100%" }}>{children}</div>
    </Field>
  </PanelSectionRow>
);

/** Small bar chart of recent readings (oldest first); the last bar is white. */
export const Bars: FC<{ label: string; values: (number | null)[]; unit?: string }> = ({ label, values, unit }) => {
  const nums = values.filter((v): v is number => v != null);
  if (nums.length < 2) return null;
  const max = Math.max(...nums, 1);
  return (
    <PanelSectionRow>
      <Field bottomSeparator="none" padding="none" childrenLayout="below" childrenContainerWidth="max">
        <div className="dot-card" style={{ width: "100%" }}>
          <div className="dot-label" style={{ display: "flex", justifyContent: "space-between" }}>
            <span>{label}</span>
            <span>
              {Math.round(nums[nums.length - 1])}
              {unit}
            </span>
          </div>
          <div style={{ display: "flex", gap: 4, alignItems: "flex-end", height: 44, marginTop: 8 }}>
            {values.map((v, i) => (
              <div
                key={i}
                style={{
                  flex: 1,
                  borderRadius: 3,
                  height: v == null ? 3 : `${Math.max(6, (v / max) * 100)}%`,
                  background: i === values.length - 1 ? "#f2f2f2" : "#2a2a2a",
                }}
              />
            ))}
          </div>
        </div>
      </Field>
    </PanelSectionRow>
  );
};

/** A row of pill buttons for a few choices; the chosen one is filled red. */
export function Pills<T extends string>({ options, value, onChange }: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <PanelSectionRow>
      <Focusable flow-children="horizontal" style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "4px 0" }}>
        {options.map((o) => (
          <DialogButton
            key={o.id}
            onClick={() => onChange(o.id)}
            className={o.id === value ? "dot-pill on" : "dot-pill"}
            style={{ width: "auto", minWidth: 0, padding: "4px 12px", fontSize: 12, lineHeight: "18px", flex: "none" }}
          >
            {o.label}
          </DialogButton>
        ))}
      </Focusable>
    </PanelSectionRow>
  );
}

/** One line of a checklist: a round mark (white tick, or red "!") and a detail on the right. */
export const Check: FC<{ ok: boolean; label: string; detail?: string }> = ({ ok, label, detail }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", fontSize: 13.5 }}>
    <span
      style={{
        width: 18, height: 18, flex: "none", borderRadius: "50%", fontSize: 11, lineHeight: "15px", textAlign: "center",
        border: `1.5px solid ${ok ? "#f2f2f2" : "#d71921"}`, color: ok ? "#f2f2f2" : "#d71921", boxSizing: "border-box",
      }}
    >
      {ok ? "✓" : "!"}
    </span>
    <span style={{ minWidth: 0 }}>
      {label}
      {detail && <div style={{ fontSize: 11.5, color: ok ? "#8a8a8a" : "#ff5a5f", overflowWrap: "anywhere" }}>{detail}</div>}
    </span>
  </div>
);

/** A row that opens a page: name, a line of what is set now, and a chevron. */
export const NavRow: FC<{ label: ReactNode; sub?: ReactNode; warn?: boolean; onClick: () => void }> = ({
  label,
  sub,
  warn,
  onClick,
}) => (
  <PanelSectionRow>
    <Field
      label={
        <span>
          {warn && <span className="dot-reddot" />}
          {label}
        </span>
      }
      description={sub}
      onActivate={onClick}
      onClick={onClick}
      highlightOnFocus
      focusable
      bottomSeparator="none"
    >
      <span style={{ color: "#8a8a8a", fontSize: 18 }}>›</span>
    </Field>
  </PanelSectionRow>
);

/** A small grey group title over rows. */
export const Group: FC<{ children: ReactNode }> = ({ children }) => (
  <div className="dot-label" style={{ margin: "12px 4px 4px" }}>
    {children}
  </div>
);

/** A page inside a tab: B or the back row returns to the tab's list. */
export const SubPage: FC<{ title: string; back: () => void; children: ReactNode }> = ({ title, back, children }) => (
  <Focusable
    onCancelButton={(e: { stopPropagation?: () => void }) => {
      e?.stopPropagation?.();
      back();
    }}
    onCancelActionDescription="Back"
  >
    <PanelSection>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={back}>
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <FaChevronLeft size={12} /> {title}
          </span>
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
    {children}
  </Focusable>
);

/** A switch row drawn by the theme (Steam's own toggle ignores restyling on some clients and
 *  stayed blue). Same props as Decky's ToggleField: A or a tap flips it. */
export const Toggle: FC<{
  label: ReactNode;
  description?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}> = ({ label, description, checked, disabled, onChange }) => {
  const flip = () => {
    if (!disabled) onChange(!checked);
  };
  return (
    <Field label={label} description={description} focusable highlightOnFocus onActivate={flip} onClick={flip}>
      <span className={`dot-switch${checked ? " on" : ""}${disabled ? " disabled" : ""}`} role="switch" aria-checked={checked} />
    </Field>
  );
};
