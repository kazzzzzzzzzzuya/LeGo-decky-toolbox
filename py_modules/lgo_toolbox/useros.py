"""The Steam user's account and session: Decky runs as root, but PipeWire,
Steam and their files belong to the user."""

import os
import pwd
import shutil
import subprocess

from . import sysio


class User(object):
    def __init__(self, name=None, home=None):
        name = name or os.environ.get("DECKY_USER") or "deck"
        try:
            pw = pwd.getpwnam(name)
            self.uid, self.gid = pw.pw_uid, pw.pw_gid
            self.home = home or pw.pw_dir
        except KeyError:
            self.uid = self.gid = None
            self.home = home or os.path.expanduser("~")
        self.name = name

    @property
    def runtime_dir(self):
        return "/run/user/%d" % self.uid if self.uid is not None else None

    def path(self, *parts):
        return os.path.join(self.home, *parts)

    def env(self):
        env = sysio.clean_env()
        env.update(HOME=self.home, USER=self.name, LOGNAME=self.name)
        if self.runtime_dir:
            env["XDG_RUNTIME_DIR"] = self.runtime_dir
        return env

    def _as_user(self):
        """subprocess arguments that drop to the user (only when we are root)."""
        if self.uid is None or os.geteuid() != 0 or self.uid == 0:
            return {}
        return {"user": self.uid, "group": self.gid, "extra_groups": []}

    def which(self, prog):
        return shutil.which(prog, path=self.env().get("PATH") or "/usr/bin:/bin")

    def run(self, cmd, timeout=5.0, env=None):
        """(returncode, stdout, stderr) of a command run as the user; rc -1
        when it could not start or timed out. env adds to the user's environment."""
        full = self.env()
        full.update(env or {})
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, timeout=timeout, env=full,
                               **self._as_user())
            return (p.returncode, p.stdout.decode("utf-8", "replace"),
                    p.stderr.decode("utf-8", "replace"))
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            return -1, "", str(e)

    def spawn(self, cmd, log_path=None, env=None):
        """Start a long-running process as the user. Its output goes to
        log_path (opened here, as root). env adds to the user's environment."""
        full = self.env()
        full.update(env or {})
        log = open(log_path, "w") if log_path else subprocess.DEVNULL
        try:
            return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, env=full,
                                    start_new_session=True, **self._as_user())
        finally:
            if log_path:
                log.close()

    def give(self, path):
        """Hand a file root wrote in the user's home over to the user."""
        if self.uid is None:
            return
        try:
            os.chown(path, self.uid, self.gid)
        except OSError:
            pass


def write_atomic(path, data, user=None, mode=0o644):
    """Write bytes or text through a temporary file. Returns None or the error."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    tmp = path + ".lgo-tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        if user is not None:
            user.give(tmp)
        os.replace(tmp, path)
        return None
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return "Could not write %s: %s" % (path, e.strerror or e)
