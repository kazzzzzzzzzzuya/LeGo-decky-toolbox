import { ButtonItem, ConfirmModal, DropdownItem, PanelSectionRow, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { FC, useEffect, useState } from "react";

import { checkUpdates, Release, Updates } from "../backend";
import { Info, PLUGIN_NAME } from "../ui";

const UPDATE = 2; // Decky's install types
const DOWNGRADE = 3;

const dayOf = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "");

function versionKey(v: string): number[] {
  return (v.match(/\d+/g) ?? []).slice(0, 4).map(Number);
}
function older(a: string, b: string): boolean {
  const [x, y] = [versionKey(a), versionKey(b)];
  for (let i = 0; i < 4; i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) < (y[i] ?? 0);
  return false;
}

async function install(r: Release, current: string) {
  const fn = (window as unknown as { DeckyBackend?: { callable?: (route: string) => (...a: unknown[]) => Promise<unknown> } })
    .DeckyBackend?.callable?.("utilities/install_plugin");
  if (!fn) {
    toaster.toast({
      title: PLUGIN_NAME,
      body: "Decky's installer is not reachable from here. Use Decky → Developer → Install Plugin from URL with the release's zip.",
    });
    return;
  }
  try {
    // Decky asks to confirm, checks the zip's SHA-256 and reloads the plugin. Settings stay.
    await fn(r.url, PLUGIN_NAME, r.version, r.sha256 ?? "", older(r.version, current) ? DOWNGRADE : UPDATE);
  } catch (e) {
    toaster.toast({ title: PLUGIN_NAME, body: `Decky could not start the installation: ${e}` });
  }
}

function askInstall(r: Release, current: string) {
  const back = older(r.version, current);
  showModal(
    <ConfirmModal
      strTitle={back ? `Go back to ${r.version}?` : `Install ${r.version}?`}
      strDescription={
        back
          ? `Decky installs ${r.version} over ${current}. Your settings stay; features added after ${r.version} are gone until you update again.`
          : `Decky installs ${r.version} over ${current}. Your settings stay.`
      }
      strOKButtonText="Install"
      onOK={() => void install(r, current)}
    />,
  );
}

/** "Update to x" at the top of the Game tab, only when there is one. */
export const UpdateBanner: FC<{ updates: Updates | null }> = ({ updates }) => {
  if (!updates?.ok || !updates.newer || !updates.latest) return null;
  const r = updates.releases[0];
  return (
    <PanelSectionRow>
      <ButtonItem
        layout="below"
        description={`You have ${updates.current}.${r.notes ? ` ${r.notes.split("\n")[0].slice(0, 140)}` : ""}`}
        onClick={() => askInstall(r, updates.current)}
      >
        Update to {updates.latest}
      </ButtonItem>
    </PanelSectionRow>
  );
};

export function useUpdates(): [Updates | null, boolean, (force: boolean) => Promise<void>] {
  const [updates, setUpdates] = useState<Updates | null>(null);
  const [checking, setChecking] = useState(false);
  const check = async (force: boolean) => {
    setChecking(true);
    try {
      setUpdates(await checkUpdates(force));
    } catch (e) {
      setUpdates({ ok: false, error: String(e), current: "", releases: [] });
    } finally {
      setChecking(false);
    }
  };
  useEffect(() => {
    void check(false); // at most every few hours: the backend keeps the answer
  }, []);
  return [updates, checking, check];
}

/** For the About section: the state, a check button, and one list for any other version. */
export const UpdateRows: FC<{ updates: Updates | null; checking: boolean; check: (force: boolean) => Promise<void> }> = ({
  updates,
  checking,
  check,
}) => {
  const others = (updates?.releases ?? []).filter((r) => r.version !== updates?.current);
  return (
    <>
      <Info label="Updates">
        {checking
          ? "Checking…"
          : !updates
            ? "–"
            : !updates.ok
              ? `Could not check: ${updates.error}`
              : updates.newer
                ? `${updates.latest} is available`
                : `Up to date (${updates.current})`}
      </Info>
      {updates?.ok && updates.newer && updates.latest && updates.releases[0] && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={`You have ${updates.current}.${updates.releases[0].notes ? ` ${updates.releases[0].notes.split("\n")[0].slice(0, 140)}` : ""}`}
            onClick={() => askInstall(updates.releases[0], updates.current)}
          >
            Update to {updates.latest}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => void check(true)}>
          {checking ? "Checking…" : "Check for updates"}
        </ButtonItem>
      </PanelSectionRow>
      {updates?.ok && others.length > 0 && (
        <PanelSectionRow>
          <DropdownItem
            label="Install another version"
            description="Pick one and confirm. Your settings stay."
            strDefaultLabel="Choose a version"
            rgOptions={others.map((r) => ({
              data: r.version,
              label: `${r.version}${r.version === updates.latest ? " · latest" : ""}${older(r.version, updates.current) ? " · older" : ""} · ${dayOf(r.published)}`,
            }))}
            selectedOption={null}
            onChange={(o) => {
              const r = others.find((x) => x.version === o.data);
              if (r) askInstall(r, updates.current);
            }}
          />
        </PanelSectionRow>
      )}
    </>
  );
};
