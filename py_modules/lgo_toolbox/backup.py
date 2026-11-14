"""Settings backup: one JSON file in the user's home folder, so a reinstall
(or another Legion Go) can take the same profiles over."""

import json
import os
import time

MAGIC = "legion-go-toolbox-backup"
MAX_BYTES = 4 << 20


def info(path):
    """{"path", "exists", "saved_at", "version"} of the backup file."""
    out = {"path": path, "exists": False, "saved_at": None, "version": None}
    data = load(path)
    if not data.get("error"):
        out.update(exists=True, saved_at=data.get("saved_at"), version=data.get("version"))
    return out


def save(path, version, toolbox, gyro):
    data = {"kind": MAGIC, "version": version,
            "saved_at": time.strftime("%Y-%m-%d %H:%M"),
            "toolbox": toolbox, "gyro": gyro}
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        try:
            # Written by root into the user's home: hand it to the user.
            st = os.stat(os.path.dirname(path) or ".")
            os.chown(path, st.st_uid, st.st_gid)
        except OSError:
            pass
        return dict(info(path), error=None)
    except (OSError, IOError, TypeError, ValueError) as e:
        return dict(info(path), error="Could not write %s: %s" % (path, e))


def load(path):
    """The backup's content, or {"error": reason}."""
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return {"error": "The backup file is too large to be one"}
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"error": "No backup file at %s" % path}
    except (OSError, IOError, ValueError) as e:
        return {"error": "Could not read the backup: %s" % e}
    if not isinstance(data, dict) or data.get("kind") != MAGIC \
            or not isinstance(data.get("toolbox"), dict):
        return {"error": "That file is not a Legion Go Toolbox backup"}
    return data
