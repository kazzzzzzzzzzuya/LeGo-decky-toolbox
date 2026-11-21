"""Cloud saves: did each game's save reach the cloud?

Steam games: CloudRedirect syncs the games in SLSsteam's AdditionalApps to the
user's cloud (Google Drive, OneDrive, R2, S3 or a folder). This only reads:

- SLSsteam's config.yaml, the way CloudRedirect's own small parser reads it,
  so a game it would skip (a quoted number, a list on one line) is named;
- CloudRedirect's log: what happened at each game's last start and exit;
- its record of each game's synced files,
  ~/.config/CloudRedirect/storage/<account>/<app>/manifest.cloudredirect;
- the cloud, through cloud_redirect_cli's read-only listings (auth-status,
  list-remote-app-ids, list-remote-app-files), run as the user. Never one of
  its commands that change cloud data. The answer is kept and asked again only
  when asked to, when the page opens and the last answer is older than half an
  hour, or a minute and a half after a game's saves changed here (at most one
  automatic check every five minutes).

Non-Steam games and emulators: OpenSave, through its daemon's local API
(~/.opensave/daemon.addr, loopback only). Status, and when asked: start the
daemon, back a game up now (uploads its snapshots; nothing on the device
changes), sync a game with the user's other devices. Steam games belong to
CloudRedirect: OpenSave is never asked to sync or back one up from here, and a
Steam game OpenSave tracks too is named, with a way to stop tracking it in
OpenSave (its save files and snapshots stay).
"""

import calendar
import json
import os
import re
import shutil
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .steam_check import CR_SESSION
from .useros import write_atomic

STEAMID64_BASE = 76561197960265728
NON_STEAM = 0x80000000          # app ids from here on are non-Steam shortcuts
MAX_GAMES = 200
MAX_JSON = 8 << 20
LOG_TAIL = 4 << 20
CLI_TIMEOUT_S = 60
CLOUD_STALE_S = 30 * 60         # opening the page checks the cloud again after this
AFTER_SYNC_S = 90               # a game's cloud check this long after its saves changed here
AUTO_GAP_S = 5 * 60             # at most one automatic cloud check per this
AUTO_BACKOFF_S = 30 * 60        # ... and after one that failed, this
TICK_S = 30
PROVIDERS = {"gdrive": "Google Drive", "onedrive": "OneDrive", "r2": "Cloudflare R2", "s3": "S3 storage"}
FOLDER_PROVIDERS = ("local", "folder")
BOOL_FALSE = ("no", "false", "0", "No", "False", "NO", "FALSE")

OPENSAVE_FLATPAK = "io.github.sivadaboi.OpenSave"
OPENSAVE_ID = re.compile(r"^[A-Za-z0-9._~-]{1,128}$")
OPENSAVE_ADDR = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\]):(\d{1,5})$")
OPENSAVE_START_S = 20.0


# -- reading files ---------------------------------------------------------------
def _read(path, limit=MAX_JSON, tail=False):
    """A regular file's bytes, or None; not following a link at the end. Over `limit` bytes:
    None, or with tail its last `limit` bytes."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if st.st_size > limit:
            if not tail:
                return None
            os.lseek(fd, st.st_size - limit, os.SEEK_SET)
        chunks, left = [], limit
        while left > 0:
            b = os.read(fd, min(left, 1 << 20))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def _json(path, limit=MAX_JSON):
    raw = _read(path, limit)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, RecursionError):
        return None


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def elf_bits(path):
    """32 or 64 for an ELF file, else None."""
    try:
        with open(path, "rb") as f:
            raw = f.read(5)
    except OSError:
        return None
    if len(raw) == 5 and raw[:4] == b"\x7fELF":
        return {1: 32, 2: 64}.get(raw[4])
    return None


# -- SLSsteam's config, read like CloudRedirect reads it ----------------------------------
def _strtoul(s):
    """The number C's strtoul() reads at the start of s, or None when it reads none."""
    m = re.match(r"^[ \t\n\r\f\v]*\+?(\d+)", s)
    return int(m.group(1)) if m else None


def read_sls_config(text):
    """SLSsteam's config.yaml as CloudRedirect's parser (yaml_parser.h) sees it:
    {"apps": [app ids], "skipped": [entries it cannot read], "cloud_blocked": bool,
     "problems": [plain words]}."""
    entries = {}
    current = None
    for line in text.split("\n"):
        t = line.lstrip(" \t")
        if not t or t[0] == "#":
            continue
        if t.startswith("- "):
            item = t[2:].split("#", 1)[0].rstrip(" \t\r")
            if current is not None:
                entries.setdefault(current, {"list": [], "is_list": False, "value": None})["list"].append(item)
            continue
        if ":" not in t:
            current = None
            continue
        key, _, value = t.partition(":")
        key = key.rstrip(" \t\r")
        current = key
        value = value.lstrip(" \t")
        if not value:
            entries.setdefault(key, {"list": [], "is_list": False, "value": None})["is_list"] = True
            continue
        value = value.split("#", 1)[0].rstrip(" \t\r")
        if value in ("~", ""):
            continue
        entries[key] = {"list": [], "is_list": False, "value": value}

    problems, apps, skipped = [], [], []
    dc = entries.get("DisableCloud")
    blocked = not (dc and dc["value"] in BOOL_FALSE)
    if blocked:
        problems.append('DisableCloud in SLSsteam\'s config.yaml is not "no", so SLSsteam blocks cloud saves.')
    ae = entries.get("AdditionalApps")
    if ae is None:
        problems.append("SLSsteam's config.yaml has no AdditionalApps, so CloudRedirect syncs no game.")
    elif ae["value"] is not None:
        problems.append("AdditionalApps is written on one line. CloudRedirect only reads it as a list, "
                        "one game per line (- 1234), so it syncs no game.")
    elif not ae["is_list"]:
        if ae["list"]:
            why = ("config.yaml has Windows line endings" if "\r\n" in text
                   else 'remove what follows "AdditionalApps:" on its line')
            problems.append("CloudRedirect reads no game from AdditionalApps: %s." % why)
    else:
        for item in ae["list"]:
            n = _strtoul(item)
            if n is not None and 0 < n <= 0xFFFFFFFF:
                if n not in apps:
                    apps.append(n)
            elif n == 0 or not item.strip():
                continue                      # 0 (or nothing) is no game; CloudRedirect passes over it too
            else:
                skipped.append(item[:40])
        quoted = [x for x in skipped if re.search(r"\d", x)]
        other = [x for x in skipped if not re.search(r"\d", x)]
        if quoted:
            problems.append("CloudRedirect skips %s in AdditionalApps. Write each game as a plain number, "
                            "without quotes (- 1234)." % ", ".join(repr(s) for s in quoted[:3]))
        if other:
            problems.append("CloudRedirect skips %s in AdditionalApps: not a game number."
                            % ", ".join(repr(s) for s in other[:3]))
    return {"apps": apps[:MAX_GAMES], "skipped": skipped, "cloud_blocked": blocked, "problems": problems}


# -- Steam: the account and game names ----------------------------------------------------
def account_id(steam_root, storage):
    """The short Steam account id CloudRedirect files saves under: the most recent login,
    else the newest account folder in its storage."""
    raw = _read(os.path.join(steam_root, "config", "loginusers.vdf"), 1 << 20) or b""
    for m in re.finditer(rb'"(\d{17})"\s*\{(.*?)\}', raw, re.S):
        if re.search(rb'"mostrecent"\s*"1"', m.group(2), re.I):
            acct = int(m.group(1)) - STEAMID64_BASE
            if 0 < acct < 1 << 32:
                return acct
    best = None
    try:
        names = os.listdir(storage)
    except OSError:
        names = []
    for n in names:
        if n.isdigit() and n != "0" and len(n) <= 10:
            try:
                mt = os.stat(os.path.join(storage, n)).st_mtime
            except OSError:
                continue
            if best is None or mt > best[0]:
                best = (mt, int(n))
    return best[1] if best else None


def library_paths(steam_root):
    paths = [steam_root]
    raw = _read(os.path.join(steam_root, "steamapps", "libraryfolders.vdf"), 1 << 20) or b""
    for m in re.finditer(rb'"path"\s*"((?:[^"\\]|\\.)*)"', raw):
        p = m.group(1).decode("utf-8", "replace").replace("\\\\", "\\")
        if p not in paths:
            paths.append(p)
    return paths


def app_name(libs, app):
    for lib in libs:
        raw = _read(os.path.join(lib, "steamapps", "appmanifest_%d.acf" % app), 1 << 20)
        if raw:
            m = re.search(rb'"name"\s*"((?:[^"\\]|\\.)*)"', raw)
            if m:
                return m.group(1).decode("utf-8", "replace")[:120]
    return None


# -- CloudRedirect's record of a game's synced files -----------------------------------------------
def read_manifest(path):
    """{name: (sha1 hex or "", size)} of manifest.cloudredirect, or None when unreadable."""
    data = _json(path)
    if not isinstance(data, dict):
        return None
    out = {}
    for name, e in list(data.items())[:100000]:
        if not isinstance(name, str) or ".cloudredirect" in name or not isinstance(e, dict):
            continue
        sha = e.get("sha") if isinstance(e.get("sha"), str) and re.match(r"^[0-9a-fA-F]{40}$", e["sha"]) else ""
        size = e.get("size")
        size = int(size) if isinstance(size, (int, float)) and size >= 0 else 0
        out[name] = (sha.lower(), size)
    return out


# -- CloudRedirect's log -----------------------------------------------------------------------
LOG_LINE = re.compile(r"^\[(\d\d:\d\d):\d\d\]\[\w+\] (.*)$")
R_BEGIN = re.compile(r"^\[NS\] BeginBatch app=(\d+) batchId=\d+ assignedCN=\d+ appBuildId=\d+ uploads=(-?\d+) deletes=(-?\d+)")
R_BEGIN_FAIL = re.compile(r"^\[NS\] BeginBatch app=(\d+): cloud CN unverifiable")
R_COMMIT = re.compile(r"^\[NS-UP\] CommitFileUpload app=(\d+) file=.* succeeded=(\d+)")
R_COMPLETE_FAIL = re.compile(r"^\[NS\] CompleteBatch app=(\d+) batch=\d+ FAILED")
R_PROMOTE_FAIL = re.compile(r"^\[NS\] CompleteBatch app=(\d+): staged promotion failed")
R_PUB_OK = re.compile(r"^\[NS\] CompleteBatch\(pub\): publish \d+/\d+ succeeded for app (\d+)")
R_PUB_FAIL = re.compile(r"^\[NS\] CompleteBatch\(pub\): all publish attempts exhausted for app (\d+)")
R_CHANGELIST = re.compile(r"^\[NS-CL\] GetAppFileChangelist app=(\d+)")
R_CURL = re.compile(r"curl failed: (-?\d+)(?: \[([^\]]*)\])?")
CURL_SAID = {"6": "server not found, no internet?", "7": "could not connect", "28": "timed out",
             "35": "secure connection failed", "56": "connection dropped",
             "60": "certificate check failed"}
WHY = {
    "cloud": "the cloud could not be reached",
    "steam": "Steam reported the upload as failed",
    "promote": "the files could not be put in place in the cloud",
    "publish": "the upload could not be finished in the cloud",
}


def parse_log(raw):
    """What the log says, per game and for the current Steam session (since CloudRedirect last
    started): {"apps": {app: {"upload": {...}, "start": {...}}}, "session": {...}}."""
    apps = {}
    sess = {"started": None, "curl_failures": 0, "curl_last": None, "signed_out": False,
            "init_failed": False, "cloud_blocked": False}
    session = 0
    for seq, line in enumerate(raw.decode("utf-8", "replace").splitlines()):
        m = LOG_LINE.match(line.strip())
        if not m:
            continue
        at, msg = m.group(1), m.group(2)
        if CR_SESSION.search(msg):
            session += 1
            sess = {"started": at, "curl_failures": 0, "curl_last": None, "signed_out": False,
                    "init_failed": False, "cloud_blocked": False}
            continue
        if "curl failed" in msg:
            c = R_CURL.search(msg)
            sess["curl_failures"] += 1
            sess["curl_last"] = (("curl %s (%s)" % (c.group(1), c.group(2) or CURL_SAID.get(c.group(1), "error")))
                                 if c else msg)[:120]
            continue
        if "configured but not authenticated" in msg:
            sess["signed_out"] = True
            continue
        if "init FAILED" in msg and "Cloud provider" in msg:
            sess["init_failed"] = True
            continue
        if "DisableCloud enabled/missing" in msg:
            sess["cloud_blocked"] = True
            continue
        if not msg.startswith("[NS"):
            continue

        def game(app):
            return apps.setdefault(int(app), {"upload": None, "start": None})

        b = R_BEGIN.match(msg)
        if b:
            game(b.group(1))["upload"] = {"at": at, "session": session, "seq": seq, "files": max(0, int(b.group(2))),
                                          "deletes": max(0, int(b.group(3))), "ok_files": 0, "bad_files": 0,
                                          "result": None, "why": None}
            continue
        b = R_BEGIN_FAIL.match(msg)
        if b:
            game(b.group(1))["upload"] = {"at": at, "session": session, "seq": seq, "files": None, "deletes": None,
                                          "ok_files": 0, "bad_files": 0, "result": "failed", "why": "cloud"}
            continue
        for rx, result, why in ((R_PUB_OK, "ok", None), (R_PUB_FAIL, "failed", "publish"),
                                (R_COMPLETE_FAIL, "failed", "steam"), (R_PROMOTE_FAIL, "failed", "promote")):
            b = rx.match(msg)
            if b:
                up = game(b.group(1))["upload"]
                if up is not None and up["result"] is None:
                    up["result"], up["why"] = result, why
                break
        else:
            b = R_COMMIT.match(msg)
            if b:
                up = game(b.group(1))["upload"]
                if up is not None and up["result"] is None:
                    up["ok_files" if b.group(2) == "1" else "bad_files"] += 1
                continue
            b = R_CHANGELIST.match(msg)
            if b:
                g = game(b.group(1))
                offline = "INCONCLUSIVE" in msg
                st = g["start"]
                if st and st["session"] == session and st["at"] == at:
                    st["offline"] = offline          # a later try in the same minute counts
                    st["seq"] = seq
                else:
                    g["start"] = {"at": at, "session": session, "seq": seq, "offline": offline}
    return {"apps": apps, "session": sess, "sessions": session}


# -- the cloud, as cloud_redirect_cli lists it ----------------------------------------------------
def parse_cli_json(out):
    """The JSON object cloud_redirect_cli printed, or None."""
    text = (out or "").strip()
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except (ValueError, RecursionError):
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                v = json.loads(line)
                return v if isinstance(v, dict) else None
            except (ValueError, RecursionError):
                continue
    return None


def compare_cloud(files, acct, app, entries):
    """A game's cloud listing against its record here: which of the files it synced have
    their content in the cloud (blobs are named by the content's SHA-1)."""
    prefix = "%s/%s/" % (acct, app)
    blobs, paths = set(), set()
    count = total = newest = 0
    for f in files if isinstance(files, list) else []:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str):
            continue
        p = f["path"].lstrip("/")
        if p.startswith(prefix):
            p = p[len(prefix):]
        if p.startswith("staging/"):
            continue
        mt = f.get("modified_time")
        if isinstance(mt, (int, float)) and mt > 0:
            newest = max(newest, int(mt / 1000 if mt > 1e11 else mt))
        if p.startswith("blobs/"):
            count += 1
            size = f.get("size")
            total += int(size) if isinstance(size, (int, float)) and size > 0 else 0
            blobs.add(p.rsplit("/", 1)[-1].lower())
            paths.add(p[len("blobs/"):])
    compared, missing = 0, []
    for name, (sha, _size) in sorted((entries or {}).items()):
        here = (sha and sha in blobs) or name in paths
        if not sha and not here:
            continue                      # nothing to tell it by
        compared += 1
        if not here:
            missing.append(name)
    return {"present": True, "files": count, "bytes": total, "newest": newest or None,
            "compared": compared, "matched": compared - len(missing),
            "missing": missing[:5], "missing_count": len(missing)}


# -- the status ----------------------------------------------------------------------------
class CloudSaves(object):
    def __init__(self, user, state_dir, steam=None, logger=None):
        self.user = user
        self.steam = steam                      # SteamCheck: Steam's root and loaded libraries
        self.log = logger
        self.path = os.path.join(state_dir, "cloud-saves.json")
        self._lock = threading.RLock()
        self._data = self._load()
        self._checking = False
        self._tick_at = 0.0
        self._auto_after = 0.0
        self._names = {}
        self._log_cache = (None, None)
        self._sls_cache = (None, None)
        self._rec_cache = {}
        self.opensave = OpenSave(user, logger)

    # -- persisted: the last cloud answer and what was already told -------------------------
    def _load(self):
        data = _json(self.path) if os.path.exists(self.path) else None
        if not isinstance(data, dict):
            data = {}
        data.setdefault("cloud", {})
        data.setdefault("told", [])
        return data

    def _save(self):
        write_atomic(self.path, json.dumps(self._data, indent=1))

    # -- paths -------------------------------------------------------------------------------
    @property
    def cr_config(self):
        return self.user.path(".config", "CloudRedirect")

    @property
    def cr_share(self):
        return self.user.path(".local", "share", "CloudRedirect")

    def steam_root(self):
        if self.steam is not None:
            return self.steam.steam_root
        return self.user.path(".local", "share", "Steam")

    def sls_path(self):
        for p in (self.user.path(".config", "SLSsteam", "config.yaml"),
                  self.user.path(".var", "app", "com.valvesoftware.Steam", ".config", "SLSsteam", "config.yaml")):
            if os.path.isfile(p):
                return p
        return None

    def cli_path(self):
        p = os.path.join(self.cr_share, "cloud_redirect_cli")
        return p if os.path.isfile(p) else None

    def provider(self):
        cfg = _json(os.path.join(self.cr_config, "config.json"), 1 << 20)
        p = cfg.get("provider") if isinstance(cfg, dict) else None
        return p.strip().lower()[:20] if isinstance(p, str) and p.strip() else None

    # -- cached reads --------------------------------------------------------------------------
    def _sls(self):
        path = self.sls_path()
        key = (path, _stamp(path) if path else None)
        if self._sls_cache[0] != key:
            raw = _read(path, 4 << 20) if path else None
            parsed = read_sls_config(raw.decode("utf-8", "replace")) if raw is not None else None
            self._sls_cache = (key, parsed)
        return self._sls_cache[1]

    def _events(self):
        path = os.path.join(self.cr_config, "cloud_redirect.log")
        key = _stamp(path)
        if self._log_cache[0] != key:
            raw = _read(path, LOG_TAIL, tail=True)
            self._log_cache = (key, parse_log(raw) if raw else None)
        return self._log_cache[1]

    def _record(self, acct, app):
        path = os.path.join(self.cr_config, "storage", str(acct), str(app), "manifest.cloudredirect")
        key = _stamp(path)
        if key is None:
            return None
        cached = self._rec_cache.get(path)
        if cached and cached[0] == key:
            return cached[1]
        entries = read_manifest(path)
        rec = {"entries": entries or {}, "unreadable": entries is None,
               "files": len(entries or {}), "bytes": sum(s for _, s in (entries or {}).values()),
               "synced_at": int(key[0] // 1000000000)}
        if len(self._rec_cache) > 4 * MAX_GAMES:
            self._rec_cache.clear()
        self._rec_cache[path] = (key, rec)
        return rec

    def _name(self, libs, app):
        if app not in self._names:
            name = app_name(libs, app)
            if name is None:
                return None                   # not installed now: ask again later
            self._names[app] = name
        return self._names[app]

    def steam_apps(self):
        """The games CloudRedirect syncs (SLSsteam's AdditionalApps, as it reads them)."""
        sls = self._sls()
        return list(sls["apps"]) if sls else []

    # -- context: what is installed and which games ------------------------------------------
    def _context(self):
        so = os.path.join(self.cr_share, "cloud_redirect.so")
        installed = os.path.isfile(so)
        sls = self._sls()
        provider = self.provider()
        storage = os.path.join(self.cr_config, "storage")
        acct = account_id(self.steam_root(), storage) if installed else None
        apps = list(sls["apps"]) if sls else []
        cli = self.cli_path()
        can_check = bool(installed and cli and acct and provider in PROVIDERS)
        return {"installed": installed, "so": so, "sls": sls, "provider": provider, "account": acct,
                "apps": apps, "cli": cli, "can_check": can_check}

    # -- the cloud check ---------------------------------------------------------------------
    def _cli(self, cli, *args):
        env = {}
        rt = self.user.runtime_dir
        if rt and os.path.exists(os.path.join(rt, "bus")):
            env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + os.path.join(rt, "bus")
        rc, out, err = self.user.run([cli, "--cli"] + [str(a) for a in args], timeout=CLI_TIMEOUT_S, env=env)
        data = parse_cli_json(out)
        if data is None:
            why = (err or out or "").strip().splitlines()
            return None, (why[-1][:160] if why else ("no answer (exit %s)" % rc))
        return data, None

    def checking(self):
        return self._checking

    def start_check(self, apps=None):
        """Ask the cloud in the background (all games, or these). False when it cannot or
        one is running."""
        ctx = self._context()
        if not ctx["can_check"]:
            return False
        with self._lock:
            if self._checking:
                return False
            self._checking = True
        targets = [a for a in ctx["apps"] if apps is None or a in apps]
        threading.Thread(target=self._check, args=(ctx, targets, apps is None),
                         name="lgo-cloud-check", daemon=True).start()
        return True

    def _check(self, ctx, targets, full):
        try:
            result = self._run_check(ctx, targets)
            with self._lock:
                cloud = self._data["cloud"]
                if cloud.get("account") != ctx["account"] or cloud.get("provider") != ctx["provider"]:
                    cloud = self._data["cloud"] = {"apps": {}}
                cloud.update(account=ctx["account"], provider=ctx["provider"], auth=result["auth"],
                             error=result["error"], at=int(time.time()))
                if full and not result["error"]:
                    cloud["full_at"] = cloud["at"]
                cloud.setdefault("apps", {}).update(result["apps"])
                self._save()
            if result["error"]:
                self._auto_after = time.time() + AUTO_BACKOFF_S
        except Exception:
            if self.log:
                self.log.exception("Cloud check failed")
        finally:
            self._checking = False

    def _run_check(self, ctx, targets):
        prov, acct, cli = ctx["provider"], ctx["account"], ctx["cli"]
        out = {"auth": None, "error": None, "apps": {}}
        auth, err = self._cli(cli, "auth-status", prov)
        if auth is None:
            out["error"] = "cloud_redirect_cli: %s" % err
            return out
        out["auth"] = bool(auth.get("authenticated"))
        if not out["auth"]:
            return out
        ids, err = self._cli(cli, "list-remote-app-ids", prov, acct)
        if ids is None or not ids.get("success"):
            out["error"] = "Could not list the cloud: %s" % ((ids or {}).get("error") or err or "no answer")
            return out
        present = {str(x) for x in ids.get("app_ids") or []}
        now = int(time.time())
        for app in targets:
            rec = self._record(acct, app)
            entry = {"checked_at": now, "record_at": rec["synced_at"] if rec else None}
            if str(app) not in present:
                entry.update(present=False)
            else:
                files, err = self._cli(cli, "list-remote-app-files", prov, acct, app)
                if files is None or not files.get("success"):
                    entry.update(error=((files or {}).get("error") or err or "no answer")[:160])
                else:
                    entry.update(compare_cloud(files.get("files"), acct, app, rec["entries"] if rec else {}))
                    entry["complete"] = bool(files.get("complete", True))
            out["apps"][str(app)] = entry
        return out

    def tick(self, now=None):
        """From the System thread: a game's saves changed here a while ago and the cloud was not
        asked since: ask (that game only)."""
        now = time.time() if now is None else now
        if now - self._tick_at < TICK_S or self._checking or now < self._auto_after:
            return
        self._tick_at = now
        ctx = self._context()
        if not ctx["can_check"]:
            return
        cloud = self._data["cloud"].get("apps", {})
        due = []
        for app in ctx["apps"]:
            rec = self._record(ctx["account"], app)
            if rec and now - rec["synced_at"] >= AFTER_SYNC_S \
                    and rec["synced_at"] != (cloud.get(str(app)) or {}).get("record_at"):
                due.append(app)
        if due and self.start_check(due):
            self._auto_after = now + AUTO_GAP_S

    # -- the page ----------------------------------------------------------------------------
    def state(self, auto=False):
        ctx = self._context()
        if auto and ctx["can_check"] and not self._checking:
            full_at = self._data["cloud"].get("full_at") or 0
            if time.time() - full_at > CLOUD_STALE_S and time.time() >= self._auto_after:
                self.start_check()
        ev = self._events() or {"apps": {}, "session": {}, "sessions": 0}
        sess = ev["session"]
        sls = ctx["sls"]
        provider = ctx["provider"]
        label = PROVIDERS.get(provider) or ("a folder" if provider in FOLDER_PROVIDERS else provider)
        with self._lock:
            cloud = dict(self._data["cloud"])
            capps = dict(cloud.get("apps") or {})
        if cloud.get("account") != ctx["account"] or cloud.get("provider") != provider:
            cloud, capps = {}, {}

        libs = library_paths(self.steam_root())
        games = []
        for app in ctx["apps"]:
            games.append(self._game(app, self._name(libs, app), ctx, ev, capps.get(str(app))))
        for item in (sls or {}).get("skipped", [])[:MAX_GAMES]:
            m = re.search(r"\d+", item)
            app = int(m.group(0)) if m and 0 < int(m.group(0)) <= 0xFFFFFFFF else None
            if app is None:
                continue                      # not a game: named once above the list
            games.append({"appid": app, "name": self._name(libs, app) if app else None, "level": "fail",
                          "key": "skip|%s" % item,
                          "problem": "CloudRedirect skips this game: in AdditionalApps it is written as %r. "
                                     "Write it as a plain number (- %s)." % (item, app or 1234),
                          "files": None, "bytes": None, "synced_at": None, "last_upload": None, "cloud": None})

        loaded, arch = None, None
        libs_loaded = self.steam.steam_libs() if self.steam is not None else None
        if ctx["installed"] and libs_loaded is not None:
            names = {os.path.basename(p) for p in libs_loaded}
            loaded = "cloud_redirect.so" in names
            if not loaded:
                client = next((p for p in libs_loaded if os.path.basename(p) == "steamclient.so"), None)
                so_bits, steam_bits = elf_bits(ctx["so"]), elf_bits(client) if client else None
                if so_bits and steam_bits and so_bits != steam_bits:
                    arch = ("cloud_redirect.so is %d-bit, but Steam runs as %d-bit, so it cannot load. "
                            "Install CloudRedirect's %d-bit build." % (so_bits, steam_bits, steam_bits))

        problems = list((sls or {}).get("problems") or [])
        if ctx["installed"] and sls is None:
            problems.append("SLSsteam's config.yaml was not found, so CloudRedirect syncs no game.")
        if arch:
            problems.append(arch)
        elif loaded is False:
            problems.append("CloudRedirect is not loaded in Steam: nothing syncs until it is. "
                            "Restart Steam; after a Steam update it may need its own update.")
        if sess.get("init_failed"):
            problems.append("CloudRedirect could not start its connection to %s." % (label or "the cloud"))
        signed_in = cloud.get("auth") if cloud else None
        if sess.get("signed_out") or signed_in is False:
            problems.append("CloudRedirect is not signed in to %s: open the CloudRedirect app and sign in."
                            % (label or "a cloud"))
        if sess.get("curl_failures"):
            problems.append("%d connection failure%s since Steam started (last: %s)."
                            % (sess["curl_failures"], "" if sess["curl_failures"] == 1 else "s", sess["curl_last"]))
        if ctx["installed"] and os.path.exists(os.path.join(self.cr_config, "disable")):
            problems.append("CloudRedirect is switched off: ~/.config/CloudRedirect/disable exists.")
        if ctx["installed"] and not provider:
            problems.append("No cloud is chosen in CloudRedirect: saves stay on this device. Choose one in its app.")

        fails = sum(1 for g in games if g["level"] == "fail")
        return {
            "installed": ctx["installed"],
            "provider": provider,
            "provider_label": label,
            "account": ctx["account"],
            "loaded": loaded,
            "signed_in": signed_in,
            "problems": problems,
            "session_started": sess.get("started"),
            "can_check": ctx["can_check"],
            "checking": self._checking,
            "cloud_at": cloud.get("at"),
            "cloud_error": cloud.get("error"),
            "games": games,
            "summary": {"games": len(games), "problems": fails,
                        "warnings": sum(1 for g in games if g["level"] == "warn")},
        }

    def _game(self, app, name, ctx, ev, cloud):
        rec = self._record(ctx["account"], app) if ctx["account"] else None
        evs = ev["apps"].get(app) or {}
        up, st = evs.get("upload"), evs.get("start")
        sessions = ev.get("sessions", 0)
        last = None
        if up:
            last = {"at": up["at"], "this_session": up["session"] == sessions, "result": up["result"],
                    "files": up["files"]}
        c = None
        if cloud:
            fresh = rec is None or cloud.get("record_at") == rec["synced_at"]
            c = {"checked_at": cloud.get("checked_at"), "present": cloud.get("present"),
                 "matched": cloud.get("matched"), "compared": cloud.get("compared"),
                 "missing": cloud.get("missing") or [], "missing_count": cloud.get("missing_count") or 0,
                 "newest": cloud.get("newest"), "error": cloud.get("error"), "stale": not fresh}

        level, problem, key = "ok", None, None
        synced_here = bool(rec and rec["files"]) or bool(up and up["result"] == "ok")
        if up and up["result"] == "failed":
            level, key = "fail", "%s|up|%s|%s|%s" % (app, up["at"], up["why"], rec and rec["synced_at"])
            problem = "The last upload failed (%s%s): %s." % (
                up["at"], "" if last["this_session"] else ", an earlier Steam session", WHY.get(up["why"], "unknown"))
        elif c and not c["stale"] and not c["error"] and c["present"] is False and synced_here:
            level, problem = "fail", "Not in the cloud: the saves are only on this device."
            key = "%s|cloud|%s" % (app, cloud.get("record_at"))
        elif c and not c["stale"] and not c["error"] and c["missing_count"]:
            level, key = "fail", "%s|cloud|%s" % (app, cloud.get("record_at"))
            problem = "%d of %d save files are not in the cloud: %s." % (
                c["missing_count"], c["compared"], ", ".join(c["missing"][:3]))
        elif st and st["offline"] and (not up or st["seq"] > up["seq"]):
            level = "warn"
            problem = ("At the last start (%s) the cloud could not be reached; Steam used the saves on this device."
                       % st["at"])
        elif up and up["result"] is None and last["this_session"]:
            level, problem = "ok", None              # uploading right now
        elif not synced_here and not (c and c["present"]):
            level = "none"
            problem = "Nothing synced yet: play, save and close the game once."
        if rec and rec["unreadable"] and level == "ok":
            level, problem = "warn", "CloudRedirect's record of this game's files could not be read."
        return {"appid": app, "name": name, "level": level, "problem": problem, "key": key,
                "files": rec["files"] if rec and not rec["unreadable"] else None,
                "bytes": rec["bytes"] if rec and not rec["unreadable"] else None,
                "synced_at": rec["synced_at"] if rec else None,
                "uploading": bool(up and up["result"] is None and last["this_session"]),
                "last_upload": last, "cloud": c}

    def alerts(self):
        """Failures not told yet, once each: [{"appid", "name", "problem"}]."""
        st = self.state()
        failing = {}
        for g in st["games"]:
            if g["level"] == "fail" and g["problem"] and g.get("key"):
                failing[g["key"]] = g
        with self._lock:
            told = set(self._data.get("told") or [])
            new = [k for k in failing if k not in told]
            keep = sorted((told & set(failing)) | set(new))
            if keep != sorted(told):
                self._data["told"] = keep[-500:]
                self._save()
        return [{"appid": failing[k]["appid"], "name": failing[k]["name"], "problem": failing[k]["problem"]}
                for k in new]


# -- OpenSave: non-Steam games and emulators ---------------------------------------------------
COMPAT = re.compile(r"/steamapps/compatdata/(\d+)(?:/|$)")
USERDATA = re.compile(r"/userdata/\d+/(\d+)(?:/|$)")


def _iso(s):
    """Unix seconds of an OpenSave time ("2026-11-21T14:02:05.000Z"), or None."""
    if not isinstance(s, str) or len(s) < 19:
        return None
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def steam_app_of(game):
    """The Steam app a tracked OpenSave game is a save of, or None for a non-Steam game:
    its app id, or a save folder inside a Steam game's Proton prefix or Steam userdata."""
    aid = str(game.get("appId") or "").strip()
    if aid.isdigit() and 0 < int(aid) < NON_STEAM:
        return int(aid)
    path = str(game.get("savePath") or "")
    for rx in (COMPAT, USERDATA):
        m = rx.search(path)
        if m and 0 < int(m.group(1)) < NON_STEAM:
            return int(m.group(1))
    return None


class OpenSaveRefused(Exception):
    def __init__(self, message, reason="", status=0):
        Exception.__init__(self, message)
        self.reason = reason
        self.status = status


class OpenSave(object):
    def __init__(self, user, logger=None):
        self.user = user
        self.log = logger
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def addr(self):
        raw = _read(self.user.path(".opensave", "daemon.addr"), 256)
        addr = raw.decode("utf-8", "replace").strip() if raw else ""
        m = OPENSAVE_ADDR.match(addr)
        return addr if m and 0 < int(m.group(2)) < 65536 else "127.0.0.1:8383"

    def request(self, path, method="GET", body=None, timeout=5.0):
        req = urllib.request.Request("http://%s%s" % (self.addr(), path), method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                raw = resp.read(MAX_JSON + 1)
        except urllib.error.HTTPError as e:
            message, reason = "OpenSave answered %d" % e.code, ""
            try:
                payload = json.loads(e.read(1 << 16) or b"{}")
                message = str(payload.get("error") or message)[:200]
                reason = str(payload.get("reason") or "")[:20]
            except (ValueError, AttributeError):
                pass
            raise OpenSaveRefused(message, reason, e.code)
        if len(raw) > MAX_JSON:
            raise OpenSaveRefused("OpenSave's answer is too large")
        return json.loads(raw.decode("utf-8", "replace")) if raw else None

    def command(self):
        """How to run opensave-cli as the user, or None when OpenSave is not installed."""
        for p in (self.user.path(".local", "bin", "opensave-cli"), self.user.path(".local", "bin", "opensave"),
                  "/usr/local/bin/opensave-cli", "/usr/bin/opensave-cli"):
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return [p]
        for base in (self.user.path(".local", "share", "flatpak"), "/var/lib/flatpak"):
            if os.path.isdir(os.path.join(base, "app", OPENSAVE_FLATPAK)):
                fp = shutil.which("flatpak") or "/usr/bin/flatpak"
                return [fp, "run", "--command=opensave-cli", OPENSAVE_FLATPAK]
        return None

    def state(self, steam_apps=()):
        installed = self.command() is not None
        try:
            status = self.request("/api/status", timeout=3) or {}
        except Exception:
            return {"installed": installed, "running": False, "games": [], "steam_games": []}
        try:
            games = self.request("/api/games", timeout=5) or {}
            settings = self.request("/api/settings", timeout=3) or {}
        except Exception as e:
            return {"installed": True, "running": True, "error": str(e)[:200], "games": [], "steam_games": []}
        cs = settings.get("cloudSync") if isinstance(settings, dict) else None
        cloud = ({"enabled": bool(cs.get("enabled")), "ready": bool(cs.get("ready")),
                  "provider": str(cs.get("provider") or "")[:40]} if isinstance(cs, dict) else None)
        conflicts = status.get("conflicts") if isinstance(status.get("conflicts"), dict) else {}
        pause = status.get("syncPause") if isinstance(status.get("syncPause"), dict) else {}
        steam_apps = set(steam_apps)
        rows, steam_rows = [], []
        for key, g in list(games.items() if isinstance(games, dict) else [])[:MAX_GAMES]:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id") or key)
            if not OPENSAVE_ID.match(gid):
                continue
            branch = (g.get("branches") or {}).get(g.get("activeBranch") or "") if isinstance(g.get("branches"), dict) else None
            snaps = branch.get("snapshots") if isinstance(branch, dict) else None
            last_snap = max([t for t in (_iso((s or {}).get("timestamp")) for s in (snaps or [])
                                         if isinstance(s, dict)) if t] or [0]) or None
            synced = g.get("lastSyncedWith") if isinstance(g.get("lastSyncedWith"), dict) else {}
            last_synced = max([t for t in (_iso(v) for v in synced.values()) if t] or [0]) or None
            app = steam_app_of(g)
            row = {"id": gid, "name": str(g.get("name") or gid)[:120], "steam_app": app,
                   "cloudredirect": app in steam_apps, "last_snapshot": last_snap, "last_synced": last_synced,
                   "folder_missing": bool(g.get("savePathMissing")), "emptied": bool(g.get("emptied")),
                   "conflict": gid in conflicts, "playing": bool(g.get("playingSince"))}
            (steam_rows if app is not None else rows).append(row)
        rows.sort(key=lambda r: r["name"].lower())
        return {"installed": True, "running": True, "cloud": cloud,
                "peers": int(status.get("peerCount") or 0), "peers_online": int(status.get("peersOnline") or 0),
                "paused": bool(pause.get("paused")), "games": rows, "steam_games": steam_rows}

    def _game(self, gid):
        if not isinstance(gid, str) or not OPENSAVE_ID.match(gid):
            raise OpenSaveRefused("Unknown game")
        games = self.request("/api/games", timeout=5) or {}
        for key, g in games.items() if isinstance(games, dict) else []:
            if isinstance(g, dict) and str(g.get("id") or key) == gid:
                return g
        raise OpenSaveRefused("OpenSave does not track this game")

    def _act(self, fn):
        try:
            return fn()
        except OpenSaveRefused as e:
            return {"ok": False, "reason": e.reason or "error", "error": str(e)}
        except Exception as e:
            return {"ok": False, "reason": "error", "error": "OpenSave did not answer: %s" % e}

    def backup(self, gid):
        """Upload the game's snapshots to OpenSave's cloud. Nothing on the device changes."""
        def go():
            if steam_app_of(self._game(gid)) is not None:
                return {"ok": False, "reason": "steam", "error": "A Steam game: CloudRedirect looks after it."}
            res = self.request("/api/cloud/sync-local/" + urllib.parse.quote(gid, safe=""), "POST", {},
                               timeout=180) or {}
            return {"ok": True, "uploaded": int(res.get("uploaded") or 0)}
        return self._act(go)

    def sync(self, gid):
        """Sync the game with the user's other devices (OpenSave keeps earlier versions)."""
        def go():
            if steam_app_of(self._game(gid)) is not None:
                return {"ok": False, "reason": "steam", "error": "A Steam game: CloudRedirect looks after it."}
            res = self.request("/api/games/%s/sync" % urllib.parse.quote(gid, safe=""), "POST", {},
                               timeout=180) or {}
            if res.get("queued"):
                return {"ok": True, "outcome": "queued"}
            peers = [p for p in (res.get("results") or {}).values() if isinstance(p, dict)]
            if any(p.get("status") == "conflict" for p in peers):
                return {"ok": True, "outcome": "conflict"}
            changed = ("updated", "updated_bidirectional", "deletions_synced", "triggered_peer_pull")
            return {"ok": True, "outcome": "changed" if any(p.get("status") in changed for p in peers) else "in-sync"}
        return self._act(go)

    def untrack(self, gid):
        """Stop OpenSave tracking a Steam game (CloudRedirect's). Its files and snapshots stay."""
        def go():
            if steam_app_of(self._game(gid)) is None:
                return {"ok": False, "reason": "error", "error": "Only Steam games are offered here."}
            self.request("/api/games/" + urllib.parse.quote(gid, safe=""), "DELETE", timeout=30)
            return {"ok": True}
        return self._act(go)

    def start(self):
        """Start OpenSave's background service as the user, the way OpenSave's own Decky
        plugin does; waits until it answers."""
        try:
            self.request("/api/status", timeout=2)
            return {"ok": True, "already": True}
        except Exception:
            pass
        cmd = self.command()
        if cmd is None:
            return {"ok": False, "error": "OpenSave is not installed."}
        env = {}
        rt = self.user.runtime_dir
        if rt and os.path.exists(os.path.join(rt, "bus")):
            env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + os.path.join(rt, "bus")
        try:
            self.user.spawn(cmd + ["daemon"], env=env)
        except Exception as e:
            return {"ok": False, "error": "Could not start OpenSave: %s" % e}
        deadline = time.monotonic() + OPENSAVE_START_S
        while time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                self.request("/api/status", timeout=2)
                return {"ok": True, "already": False}
            except Exception:
                continue
        return {"ok": False, "error": "OpenSave did not answer within %d seconds." % OPENSAVE_START_S}
