"""Steam update check: are the Steam client mods still working after Steam
updated itself, and backups of their settings from when they were.

Read-only towards Steam: it looks at Steam's build number, at which libraries
the running steam process has loaded (/proc/<pid>/maps) and at the mods'
files. Nothing is injected or hooked. It writes only when asked to: restoring
a backup, or "Hold Steam updates" (Valve's own steam.cfg switch for the
Steam bootstrapper).

Covered when installed: SLSsteam, CloudRedirect (official or the LeGo
64-bit fork) and ASSella / Uran's library.
"""

import hashlib
import json
import os
import re
import shutil
import time

from .useros import write_atomic

SNAPSHOTS_KEPT = 8
MAX_FILE_BYTES = 2 << 20
HOLD_CFG = "BootStrapperInhibitAll=enable\nBootStrapperForceSelfUpdate=disable\n"
LOG_TAIL = 64 << 10
CR_PROBLEMS = re.compile(r"init failed|not installed|signature.*(fail|mismatch|not found)|"
                         r"could not (find|resolve)|hook.*fail", re.I)
CR_SESSION = re.compile(r"cloudredirect build|lego fork", re.I)


def _read(path, limit=None):
    try:
        with open(path, "rb") as f:
            if limit:
                size = os.fstat(f.fileno()).st_size
                if size > limit:
                    f.seek(size - limit)
            return f.read()
    except OSError:
        return None


def yaml_problems(text):
    """Problems a simple look at SLSsteam's config.yaml can see."""
    out, seen = [], set()
    for n, line in enumerate(text.splitlines(), 1):
        if line[:len(line) - len(line.lstrip())].count("\t"):
            out.append("line %d is indented with a tab" % n)
        m = re.match(r"^([A-Za-z][\w-]*)\s*:", line)
        if m:
            if m.group(1) in seen:
                out.append("%s appears twice" % m.group(1))
            seen.add(m.group(1))
        if len(out) >= 3:
            break
    if not seen:
        out.append("no settings found")
    return out


def cr_log_problems(raw):
    """Problem lines of the last CloudRedirect session in its log."""
    lines = raw.decode("utf-8", "replace").splitlines()
    start = 0
    for i, line in enumerate(lines):
        if CR_SESSION.search(line):
            start = i
    return [line.strip()[:160] for line in lines[start:] if CR_PROBLEMS.search(line)][-3:]


class SteamCheck(object):
    def __init__(self, user, state_dir, logger=None, proc="/proc"):
        self.user = user
        self.log = logger
        self.proc = proc
        self.snap_dir = os.path.join(state_dir, "steam-snapshots")
        self.state_path = os.path.join(state_dir, "steam-check.json")
        self.state = self._load_state()
        self._fork_cache = (None, False)

    # -- paths ---------------------------------------------------------------
    @property
    def steam_root(self):
        for p in (self.user.path(".local", "share", "Steam"), self.user.path(".steam", "steam")):
            if os.path.isdir(p):
                return os.path.realpath(p)
        return self.user.path(".local", "share", "Steam")

    def files(self):
        """{key: path} of the settings files backed up (those that exist)."""
        out = {
            "SLSsteam/config.yaml": self.user.path(".config", "SLSsteam", "config.yaml"),
            "ACCELA/plugin_library.json": self.user.path(".local", "share", "ACCELA", "db", "plugin_library.json"),
        }
        cr = self.user.path(".config", "CloudRedirect")
        try:
            for name in sorted(os.listdir(cr)):
                p = os.path.join(cr, name)
                if os.path.isfile(p) and not name.endswith((".log", ".tmp")) \
                        and os.path.getsize(p) <= MAX_FILE_BYTES:
                    out["CloudRedirect/" + name] = p
        except OSError:
            pass
        return {k: v for k, v in out.items() if os.path.isfile(v)}

    # -- state ---------------------------------------------------------------
    def _load_state(self):
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        write_atomic(self.state_path, json.dumps(self.state, indent=1))

    # -- reading Steam -----------------------------------------------------------
    def steam_version(self):
        best = None
        pkg = os.path.join(self.steam_root, "package")
        try:
            names = [n for n in os.listdir(pkg) if n.startswith("steam_client_") and n.endswith(".manifest")]
        except OSError:
            return None
        for n in names:
            raw = _read(os.path.join(pkg, n), 1 << 20) or b""
            m = re.search(rb'"version"\s*"(\d+)"', raw)
            if m and (best is None or int(m.group(1)) > best):
                best = int(m.group(1))
        return best

    def steam_libs(self):
        """Paths of the libraries the running Steam client loaded, or None
        when Steam is not running."""
        try:
            pids = [p for p in os.listdir(self.proc) if p.isdigit()]
        except OSError:
            return None
        for pid in pids:
            comm = (_read(os.path.join(self.proc, pid, "comm")) or b"").strip()
            if comm != b"steam":
                continue
            maps = _read(os.path.join(self.proc, pid, "maps"))
            if not maps or b"steamclient.so" not in maps:
                continue
            return {line.split(None, 5)[5] for line in maps.decode("utf-8", "replace").splitlines()
                    if len(line.split(None, 5)) == 6}
        return None

    def _is_fork(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return False
        key = (st.st_mtime, st.st_size)
        if self._fork_cache[0] != key:
            self._fork_cache = (key, b"LeGo fork" in (_read(path) or b""))
        return self._fork_cache[1]

    # -- the check ---------------------------------------------------------------
    def check(self):
        version = self.steam_version()
        libs = self.steam_libs()
        running = libs is not None
        names = {os.path.basename(p) for p in (libs or ())}
        items = []

        def item(key, label, ok, detail, installed=True):
            items.append({"id": key, "label": label, "ok": ok, "detail": detail, "installed": installed})

        item("steam", "Steam client", running,
             ("build %s" % version if version else "build unknown") + (" · running" if running else " · not running"))

        sls = self.user.path(".local", "share", "SLSsteam", "SLSsteam.so")
        if os.path.exists(sls):
            cfg = self.user.path(".config", "SLSsteam", "config.yaml")
            raw = _read(cfg, 4 << 20)
            problems = ["config.yaml is missing"] if raw is None else yaml_problems(raw.decode("utf-8", "replace"))
            loaded = "SLSsteam.so" in names
            ok = loaded and not problems if running else not problems
            detail = ("loaded" if loaded else "NOT loaded in Steam") if running else "Steam not running"
            if problems:
                detail += " · config: " + "; ".join(problems)
            item("slssteam", "SLSsteam", ok, detail)

        cr_dir = self.user.path(".local", "share", "CloudRedirect")
        cr_so = os.path.join(cr_dir, "cloud_redirect.so")
        if os.path.exists(cr_so):
            fork = self._is_fork(cr_so)
            loaded = "cloud_redirect.so" in names
            log = _read(self.user.path(".config", "CloudRedirect", "cloud_redirect.log"), LOG_TAIL)
            problems = cr_log_problems(log) if log else []
            ok = (loaded if running else True) and not problems
            detail = ("LeGo 64-bit fork" if fork else "official build")
            detail += (" · loaded" if loaded else " · NOT loaded in Steam") if running else ""
            if problems:
                detail += " · log: " + problems[-1]
            if not fork and os.path.exists(cr_so + ".official"):
                detail += " · the fork was replaced (Update/Deploy or Headcrab?)"
                ok = False
            item("cloudredirect", "CloudRedirect", ok, detail)

        lib = self.user.path(".local", "share", "ACCELA", "db", "plugin_library.json")
        if os.path.exists(lib):
            try:
                with open(lib) as f:
                    count = len(json.load(f) or {})
                item("accela", "ASSella / Uran library", True, "%d games" % count)
            except (OSError, ValueError) as e:
                item("accela", "ASSella / Uran library", False, "unreadable: %s" % e)

        last_good = self.state.get("last_good")
        all_ok = all(i["ok"] for i in items)
        if running and all_ok and version:
            if last_good != version:
                self.state["last_good"] = version
                self.state["good_at"] = time.strftime("%Y-%m-%d %H:%M")
                self._save_state()
            self.snapshot("working on build %s" % version)
        changed = bool(last_good and version and version != last_good)
        overall = "idle" if not running else ("ok" if all_ok else "fail")
        return {
            "overall": overall,
            "items": items,
            "version": version,
            "last_good": self.state.get("last_good"),
            "good_at": self.state.get("good_at"),
            "updated_since_good": changed and overall != "ok",
            "hold": self.hold_state(),
            "checked_at": time.strftime("%H:%M"),
        }

    # -- backups -----------------------------------------------------------------
    def snapshots(self):
        out = []
        try:
            names = sorted(os.listdir(self.snap_dir), reverse=True)
        except OSError:
            return out
        for n in names:
            try:
                with open(os.path.join(self.snap_dir, n, "meta.json")) as f:
                    meta = json.load(f)
                out.append({"name": n, "created": meta.get("created"), "reason": meta.get("reason"),
                            "steam": meta.get("steam"), "files": sorted(meta.get("files", {}))})
            except (OSError, ValueError):
                continue
        return out

    def _digest(self, files):
        h = hashlib.sha256()
        for key in sorted(files):
            h.update(key.encode() + b"\0" + (_read(files[key]) or b"") + b"\0")
        return h.hexdigest()

    def snapshot(self, reason, force=False):
        """Copy the settings files; skipped when nothing changed since the last copy."""
        files = self.files()
        if not files:
            return None
        digest = self._digest(files)
        if not force and digest == self.state.get("snapshot_digest"):
            return None
        name = base = time.strftime("%Y%m%d-%H%M%S")
        n = 1
        while os.path.exists(os.path.join(self.snap_dir, name)):
            name, n = "%s-%d" % (base, n), n + 1
        target = os.path.join(self.snap_dir, name)
        try:
            for key, src in files.items():
                dst = os.path.join(target, "files", key)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            meta = {"created": time.strftime("%Y-%m-%d %H:%M"), "reason": reason,
                    "steam": self.steam_version(), "files": files}
            with open(os.path.join(target, "meta.json"), "w") as f:
                json.dump(meta, f, indent=1)
        except OSError as e:
            shutil.rmtree(target, ignore_errors=True)
            if self.log:
                self.log.warning("Snapshot failed: %s", e)
            return None
        self.state["snapshot_digest"] = digest
        self._save_state()
        for old in self.snapshots()[SNAPSHOTS_KEPT:]:
            shutil.rmtree(os.path.join(self.snap_dir, old["name"]), ignore_errors=True)
        return name

    def restore(self, name):
        """Put a backup's files back where they came from."""
        if not re.match(r"^\d{8}-\d{6}(-\d+)?$", str(name or "")):
            return {"ok": False, "error": "Unknown backup"}
        base = os.path.join(self.snap_dir, name)
        try:
            with open(os.path.join(base, "meta.json")) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            return {"ok": False, "error": "That backup is not readable"}
        self.snapshot("before restoring %s" % name, force=True)
        restored, errors = [], []
        for key, dst in (meta.get("files") or {}).items():
            src = os.path.join(base, "files", key)
            if ".." in key.split("/") or not os.path.realpath(dst).startswith(os.path.realpath(self.user.home) + os.sep):
                errors.append("%s: outside your home folder" % key)
                continue
            data = _read(src)
            if data is None:
                errors.append("%s: missing in the backup" % key)
                continue
            err = write_atomic(dst, data, user=self.user)
            (errors.append(err) if err else restored.append(key))
        return {"ok": not errors, "restored": restored, "error": "; ".join(errors) or None}

    # -- hold Steam updates --------------------------------------------------------
    @property
    def cfg_path(self):
        return os.path.join(self.steam_root, "steam.cfg")

    def hold_state(self):
        raw = _read(self.cfg_path)
        if raw is None:
            return {"held": False, "foreign": False}
        return {"held": raw.decode("utf-8", "replace") == HOLD_CFG, "foreign": raw.decode("utf-8", "replace") != HOLD_CFG}

    def set_hold(self, on):
        st = self.hold_state()
        if st["foreign"]:
            return {"ok": False, "error": "%s exists with other settings; it is left alone" % self.cfg_path}
        if on and not st["held"]:
            err = write_atomic(self.cfg_path, HOLD_CFG, user=self.user)
            return {"ok": err is None, "error": err}
        if not on and st["held"]:
            try:
                os.unlink(self.cfg_path)
            except OSError as e:
                return {"ok": False, "error": str(e)}
        return {"ok": True, "error": None}
