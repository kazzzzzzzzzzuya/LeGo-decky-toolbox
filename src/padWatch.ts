import { toaster } from "@decky/api";

import { getStatus } from "./backend";
import { padBatteries, PLUGIN_NAME } from "./ui";

const LEVELS = [15, 5];       // a detached controller says so once at each of these
const RESET = 20;             // ... and again after it was charged above this

/** Low battery of a detached controller, also with the menu closed: checked once a minute. */
export function watchControllerBattery(): () => void {
  const told: Record<string, number> = {};          // side -> lowest level already told
  const check = async () => {
    try {
      const st = await getStatus();
      for (const p of padBatteries({ status: st.gyro }) ?? []) {
        if (!p.connected || p.attached || p.battery == null) {
          if (p.attached) delete told[p.side];
          continue;
        }
        if (p.battery > RESET) {
          delete told[p.side];
          continue;
        }
        const level = LEVELS.filter((l) => p.battery! <= l).pop();
        if (level != null && (told[p.side] == null || level < told[p.side])) {
          told[p.side] = level;
          toaster.toast({
            title: PLUGIN_NAME,
            body: `${p.side === "left" ? "Left" : "Right"} controller at ${p.battery} %: attach it to the tablet to charge.`,
          });
        }
      }
    } catch {
      /* backend not ready */
    }
  };
  const id = setInterval(() => void check(), 60000);
  return () => clearInterval(id);
}
