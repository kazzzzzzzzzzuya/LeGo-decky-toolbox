"""Newer (and earlier) releases of this plugin on GitHub, for the update
button on the Home tab. Decky's own installer does the installing: it asks
the user to confirm and checks the zip's SHA-256."""

import json
import re
import subprocess
import time

from . import sysio

REPO = "kazzzzzzzzzzuya/LeGo-decky-toolbox"
API = "https://api.github.com/repos/%s/releases?per_page=15" % REPO
TTL_S = 3 * 3600
ZIP = "legion-go-toolbox.zip"


def version_key(v):
    return [int(x) for x in re.findall(r"\d+", str(v).split("-")[0])][:4]


def parse(releases, current):
    """GitHub's release list -> what the panel shows."""
    out = []
    for r in releases if isinstance(releases, list) else []:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        asset = next((a for a in r.get("assets") or [] if isinstance(a, dict) and a.get("name") == ZIP), None)
        tag = str(r.get("tag_name") or "")
        if not asset or not re.fullmatch(r"v?\d+(\.\d+){1,3}", tag):
            continue
        digest = str(asset.get("digest") or "")
        out.append({"version": tag.lstrip("v"), "url": str(asset.get("browser_download_url") or ""),
                    "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
                    "published": r.get("published_at"), "notes": str(r.get("body") or "")[:1500]})
    out.sort(key=lambda r: version_key(r["version"]), reverse=True)
    if not out:
        return {"ok": False, "error": "No release with a plugin zip found.", "current": current, "releases": []}
    latest = out[0]["version"]
    return {"ok": True, "current": current, "latest": latest,
            "newer": version_key(latest) > version_key(current), "releases": out}


def fetch():
    out = subprocess.run(["curl", "-fsSL", "--max-time", "20", "-H", "Accept: application/vnd.github+json",
                          "-H", "User-Agent: legion-go-toolbox", API],
                         capture_output=True, env=sysio.clean_env(), timeout=30)
    if out.returncode != 0:
        msg = out.stderr.decode(errors="replace").strip()[:120]
        raise RuntimeError("GitHub could not be reached (%s)" % (msg or "curl %d" % out.returncode))
    return json.loads(out.stdout.decode())


class Updates(object):
    def __init__(self, current, fetch_fn=fetch, clock=time.monotonic):
        self.current = current
        self._fetch = fetch_fn
        self._clock = clock
        self._cache = None       # (time, result)

    def check(self, force=False):
        now = self._clock()
        if self._cache and not force and now - self._cache[0] < TTL_S:
            return self._cache[1]
        try:
            result = parse(self._fetch(), self.current)
        except Exception as e:
            result = {"ok": False, "error": str(e), "current": self.current, "releases": []}
        self._cache = (now, result)
        return result
