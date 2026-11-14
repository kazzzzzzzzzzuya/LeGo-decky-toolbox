"""Build and load the ``acpi_call`` kernel module on SteamOS.

SteamOS ships neither the module nor a compiler. The technique is the one
Legion Center worked out on real devices: put a throw-away overlay over the
running root (its changes land in a loopback image on /home), install
SteamOS's own toolchain and the running kernel's headers *inside* it with
pacman, and build there.

Unlike a DKMS install, nothing is written to the system partition: the one
file that results, ``acpi_call.ko``, is kept in the plugin's data folder per
kernel version and loaded with ``insmod`` when the plugin starts. A SteamOS
update that brings a new kernel needs one more build (the Home tab says so).
"""

import os
import re
import shutil
import signal
import subprocess
import threading
import time

from . import acpi, sysio

SOURCE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "acpi_call_src")
PACMAN_DB = "/usr/lib/holo/pacmandb"
PACMAN_CONF = "/etc/pacman.conf"
MIRRORLIST = "/etc/pacman.d/mirrorlist"
IMAGE = "/home/.lgo-toolbox-build.img"
WORK = "/home/.lgo-toolbox-build"
IMAGE_SIZE = "3G"
NEED_FREE = 4 * 1024 ** 3
# chroot only changes the file-system root: keep anything in the build from
# loading modules, rebooting or touching raw I/O on the real machine.
DROP_CAPS = ["setpriv", "--no-new-privs", "--bounding-set=-sys_module,-sys_boot,-sys_rawio"]
TOOLS = ("pacman", "pacman-key", "mount", "umount", "chroot", "setpriv", "mkfs.ext4",
         "truncate", "curl", "insmod")
LOG_LINES = 40


class InstallError(Exception):
    pass


def kernel_release():
    return os.uname().release


def stored_module(state_dir, release=None):
    return os.path.join(state_dir, "acpi_call", release or kernel_release(), "acpi_call.ko")


def built_for_other_kernel(state_dir):
    """True if a module was built before, but not for the running kernel
    (a SteamOS update changed the kernel)."""
    base = os.path.join(state_dir, "acpi_call")
    try:
        names = os.listdir(base)
    except OSError:
        return False
    return any(n != kernel_release() and os.path.isfile(os.path.join(base, n, "acpi_call.ko"))
               for n in names)


def load_stored(state_dir, run=sysio.run, proc=acpi.PATH):
    """Load the module built earlier for this kernel. True if /proc/acpi/call
    exists afterwards."""
    if os.path.exists(proc):
        return True
    ko = stored_module(state_dir)
    if not os.path.isfile(ko):
        return False
    run(["insmod", ko], timeout=10.0)
    return os.path.exists(proc)


def headers_url(pkg_file, conf_text, mirror_text):
    """Download address of a kernel package, from the system's own pacman
    settings (the jupiter repository and the first mirror)."""
    repo = re.search(r"^\[(jupiter-[^\]]+)\]", conf_text or "", re.M)
    mirror = re.search(r"^Server\s*=\s*(\S+)", mirror_text or "", re.M)
    if not repo or not mirror:
        return None
    base = mirror.group(1).replace("$repo", repo.group(1)).replace("$arch", "x86_64")
    return "%s/%s" % (base.rstrip("/"), pkg_file)


class Installer(object):
    """Runs the build in a background thread; ``status()`` reports progress."""

    def __init__(self, state_dir, logger=None, on_done=None):
        self.state_dir = state_dir
        self._log = logger
        self._on_done = on_done
        self._lock = threading.Lock()
        self._thread = None
        self._state = {"running": False, "step": None, "error": None, "done": False, "log": []}

    # ---- public --------------------------------------------------------------
    def status(self):
        with self._lock:
            out = dict(self._state)
            out["log"] = list(out["log"])
        out["available"] = os.path.exists(acpi.PATH)
        out["built"] = bool(self.state_dir) and os.path.isfile(stored_module(self.state_dir))
        out["kernel_changed"] = (not out["available"] and not out["built"]
                                 and bool(self.state_dir)
                                 and built_for_other_kernel(self.state_dir))
        return out

    def start(self):
        with self._lock:
            if self._state["running"]:
                return False
            self._state = {"running": True, "step": "Starting", "error": None,
                           "done": False, "log": []}
        self._thread = threading.Thread(target=self._run_all, name="acpi-install", daemon=True)
        self._thread.start()
        return True

    # ---- helpers ---------------------------------------------------------------
    def _step(self, text):
        with self._lock:
            self._state["step"] = text
        self._note("== " + text)

    def _note(self, line):
        if self._log:
            self._log.info("acpi_call install: %s", line)
        with self._lock:
            self._state["log"] = (self._state["log"] + [line[:300]])[-LOG_LINES:]

    def _sh(self, cmd, timeout=120.0, check=True):
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=timeout, env=sysio.clean_env(),
                               stdin=subprocess.DEVNULL)
            rc, out = p.returncode, p.stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            rc, out = -1, "timed out after %d s" % timeout
        except OSError as e:
            rc, out = -1, str(e)
        tail = [l for l in out.strip().splitlines() if l.strip()][-6:]
        if rc != 0:
            if check:
                for line in tail:
                    self._note(line)
            if check:
                raise InstallError("%s failed%s" % (
                    cmd[0] if cmd[0] != "setpriv" else "A build step",
                    (": " + tail[-1][:200]) if tail else ""))
        return rc, out

    def _chroot(self, merged, script, timeout=1500.0, check=True):
        """Run a shell script inside the overlay. Its output goes to a file,
        not a pipe: helpers it leaves running (gpg-agent after pacman-key)
        would keep a pipe open and stall the step."""
        log = os.path.join(merged, "tmp", "lgo-step.log")
        try:
            os.makedirs(os.path.dirname(log), exist_ok=True)
            open(log, "w").close()
        except OSError:
            pass
        wrapped = "( %s ) > /tmp/lgo-step.log 2>&1 < /dev/null" % script
        rc, out = self._sh(DROP_CAPS + ["chroot", merged, "/bin/bash", "-c", wrapped],
                           timeout=timeout, check=False)
        try:
            with open(log, "r", errors="replace") as f:
                out = f.read()[-20000:] + out
        except OSError:
            pass
        if rc != 0:
            tail = [l for l in out.strip().splitlines() if l.strip()][-6:]
            for line in tail:
                self._note(line)
            if check:
                raise InstallError("A build step failed%s" % (
                    (": " + tail[-1][:200]) if tail else ""))
        return rc, out

    # ---- overlay ---------------------------------------------------------------
    def _kill_inside(self, merged):
        """End processes still rooted in the overlay (gpg-agent from
        pacman-key), or it cannot be unmounted."""
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                root = os.readlink("/proc/%s/root" % pid)
            except OSError:
                continue
            if root == merged or root.startswith(merged + "/"):
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except OSError:
                    pass

    def _teardown(self):
        merged = os.path.join(WORK, "merged")
        if os.path.isdir(merged):
            self._kill_inside(merged)
            time.sleep(0.3)
        for target in (merged, WORK):
            if os.path.ismount(target):
                if self._sh(["umount", "-R", target], check=False)[0] != 0:
                    self._sh(["umount", "-Rl", target], check=False)
        self._sh(["sync"], check=False)
        if not os.path.ismount(WORK):
            try:
                if os.path.isdir(WORK):
                    os.rmdir(WORK)
            except OSError:
                pass
            try:
                os.remove(IMAGE)
            except OSError:
                pass

    def _setup(self):
        self._teardown()                      # leftovers of an interrupted run
        os.makedirs(WORK, exist_ok=True)
        self._sh(["truncate", "-s", IMAGE_SIZE, IMAGE])
        self._sh(["mkfs.ext4", "-q", "-F", IMAGE])
        self._sh(["mount", "-o", "loop", IMAGE, WORK])
        upper, ovl, merged = (os.path.join(WORK, n) for n in ("upper", "ovlwork", "merged"))
        for d in (upper, ovl, merged):
            os.makedirs(d, exist_ok=True)
        self._sh(["mount", "-t", "overlay", "overlay", "-o",
                  "index=off,lowerdir=/,upperdir=%s,workdir=%s" % (upper, ovl), merged])
        self._sh(["mount", "-t", "proc", "proc", os.path.join(merged, "proc")])
        for name in ("sys", "dev"):
            self._sh(["mount", "--rbind", "/" + name, os.path.join(merged, name)])
            self._sh(["mount", "--make-rslave", os.path.join(merged, name)])
        # /etc/resolv.conf is a link into /run, which the overlay does not carry.
        resolv = os.path.join(merged, "etc", "resolv.conf")
        try:
            if os.path.lexists(resolv):
                os.remove(resolv)
            shutil.copy("/etc/resolv.conf", resolv)
        except OSError:
            pass
        if not os.path.exists(os.path.join(merged, "bin", "bash")):
            raise InstallError("The build overlay did not mount correctly")
        return merged

    # ---- the build -------------------------------------------------------------
    def _kernel_package(self):
        rel = kernel_release()
        rc, out = self._sh(["pacman", "-Qoq", "--dbpath", PACMAN_DB,
                            "/usr/lib/modules/" + rel], check=False)
        name = out.strip().split()[0] if rc == 0 and out.strip() else None
        if not name:
            return None, None
        rc, out = self._sh(["pacman", "-Q", "--dbpath", PACMAN_DB, name], check=False)
        parts = out.strip().split()
        return name, (parts[1] if rc == 0 and len(parts) >= 2 else None)

    def _run_all(self):
        error = None
        try:
            self._build()
        except InstallError as e:
            error = str(e)
        except Exception as e:   # never take the plugin down
            error = "Unexpected error: %s" % e
        finally:
            try:
                self._step("Cleaning up")
                self._teardown()
            except Exception as e:
                self._note("cleanup: %s" % e)
        if error is None:
            if load_stored(self.state_dir):
                self._note("acpi_call is loaded")
            else:
                error = "The module was built but could not be loaded (see the Decky log)"
        with self._lock:
            self._state.update(running=False, done=error is None, error=error,
                               step="Done" if error is None else "Failed")
        if error:
            self._note("FAILED: " + error)
        if self._on_done:
            try:
                self._on_done(error is None)
            except Exception:
                pass

    def _build(self):
        rel = kernel_release()
        self._step("Checking the system")
        if os.geteuid() != 0:
            raise InstallError("The plugin does not run as root")
        missing = [t for t in TOOLS if shutil.which(t, path=sysio.clean_env().get(
            "PATH", "") + ":/usr/bin:/usr/sbin:/sbin:/bin") is None]
        if missing:
            raise InstallError("This system lacks %s (only SteamOS is supported)"
                               % ", ".join(missing))
        if not os.path.isfile(os.path.join(SOURCE_DIR, "acpi_call.c")):
            raise InstallError("The plugin's copy of the acpi_call source is missing")
        try:
            free = shutil.disk_usage("/home").free
        except OSError:
            free = 0
        if free < NEED_FREE:
            raise InstallError("Needs about 4 GB of free space on the internal drive "
                               "for the build (freed again afterwards)")
        pkg, version = self._kernel_package()
        self._note("kernel %s, package %s %s" % (rel, pkg, version))

        self._step("Preparing a temporary build area")
        merged = self._setup()
        src = os.path.join(merged, "tmp", "acpi_call")
        shutil.rmtree(src, ignore_errors=True)
        shutil.copytree(SOURCE_DIR, src)

        self._step("Downloading the compiler (a few minutes)")
        self._chroot(merged, "pacman-key --init && pacman-key --populate", timeout=600.0)
        self._chroot(merged, "pacman -Sy --dbpath %s" % PACMAN_DB, timeout=600.0)
        self._chroot(merged, "pacman -S base-devel --dbpath %s --needed --overwrite '*' "
                             "--noconfirm" % PACMAN_DB)

        build_dir = "/usr/lib/modules/%s/build" % rel
        if not os.path.exists(os.path.join(merged, build_dir.lstrip("/"), "Makefile")):
            self._step("Downloading the kernel headers")
            got = False
            if pkg and version:
                fname = "%s-headers-%s-x86_64.pkg.tar.zst" % (pkg, version)
                url = headers_url(fname, sysio.read_text(PACMAN_CONF, ""),
                                  sysio.read_text(MIRRORLIST, ""))
                if url:
                    dest = os.path.join(merged, "tmp", fname)
                    rc, _ = self._sh(["curl", "-fsSL", "--retry", "2", "-o", dest, url],
                                     timeout=900.0, check=False)
                    if rc == 0:
                        rc, _ = self._chroot(
                            merged, "pacman -U /tmp/%s --dbpath %s --needed --overwrite '*' "
                                    "--noconfirm" % (fname, PACMAN_DB), check=False)
                        got = rc == 0
            if not got and pkg:
                self._chroot(merged, "pacman -S %s-headers --dbpath %s --needed "
                                     "--overwrite '*' --noconfirm" % (pkg, PACMAN_DB),
                             check=False)
            if not os.path.exists(os.path.join(merged, build_dir.lstrip("/"), "Makefile")):
                raise InstallError(
                    "No kernel headers for this kernel (%s) could be downloaded. Update "
                    "SteamOS, restart and try again" % rel)

        self._step("Building acpi_call")
        self._chroot(merged, "make -C %s M=/tmp/acpi_call modules" % build_dir, timeout=900.0)
        ko = os.path.join(src, "acpi_call.ko")
        if not os.path.isfile(ko):
            raise InstallError("The build produced no module")
        rc, out = self._sh(["modinfo", "-F", "vermagic", ko], check=False)
        if rc == 0 and out.strip() and out.split()[0] != rel:
            raise InstallError("The module was built for kernel %s, not the running %s"
                               % (out.split()[0], rel))

        self._step("Saving the module")
        dest = stored_module(self.state_dir)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(ko, dest + ".tmp")
        os.replace(dest + ".tmp", dest)
        # Modules of kernels that are gone are of no use any more.
        base = os.path.dirname(os.path.dirname(dest))
        for name in os.listdir(base):
            if name != rel and not os.path.isdir("/usr/lib/modules/" + name):
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)
