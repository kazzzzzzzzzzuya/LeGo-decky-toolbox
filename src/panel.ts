import { useQuickAccessVisible } from "@decky/api";
import { useEffect, useState } from "react";

// Whether the plugin's panel is on screen (same method as Frame Suite). Decky's useQuickAccessVisible
// only knows Decky's own tab: in a QuickTab tab it stays false, so the panel's own element is asked too.
// On screen means it has a size and lies inside its window sideways (a closed menu slides out sideways).
let panelEl: HTMLElement | null = null;
let shown = false;
const listeners = new Set<() => void>();

function checkShown(): boolean {
  let v = false;
  // Steam draws the Quick Access menu in a window of its own: ask the panel's own document and window.
  const doc = panelEl?.ownerDocument;
  const win = doc?.defaultView;
  if (panelEl && panelEl.isConnected && doc && win && doc.visibilityState !== "hidden") {
    const r = panelEl.getBoundingClientRect();
    v = r.width > 0 && r.height > 0 && r.right > 0 && r.left < win.innerWidth &&
      win.getComputedStyle(panelEl).visibility !== "hidden";
  }
  if (v !== shown) {
    shown = v;
    listeners.forEach((l) => l());
  }
  return v;
}

export const panel = {
  attach(el: HTMLElement | null) {
    panelEl = el;
    checkShown();
  },
  shown: checkShown,
};

/** True while the panel is on screen: in Decky's own tab or in a QuickTab tab. */
export function usePanelVisible(): boolean {
  const decky = useQuickAccessVisible();
  const [v, setV] = useState(shown);
  useEffect(() => {
    const l = () => setV(shown);
    listeners.add(l);
    const timer = setInterval(checkShown, 500);
    l();
    return () => {
      listeners.delete(l);
      clearInterval(timer);
    };
  }, []);
  return decky || v;
}
