"""Legion Go Toolbox - Decky Loader backend entry point."""

import asyncio
import os
import sys

import decky

_HERE = os.path.dirname(os.path.realpath(__file__))
_MODULES = os.path.join(_HERE, "py_modules")
if _MODULES not in sys.path:
    sys.path.insert(0, _MODULES)

from lgo_gyro.service import GyroService  # noqa: E402
from lgo_toolbox import __version__, backup  # noqa: E402
from lgo_toolbox.updates import Updates  # noqa: E402
from lgo_toolbox.hub import Hub  # noqa: E402
from lgo_toolbox.system import System  # noqa: E402

GYRO_SETTINGS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "gyro.json")
HUB_SETTINGS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "toolbox.json")
BACKUP_FILE = os.path.join(getattr(decky, "DECKY_USER_HOME", None) or os.path.expanduser("~"),
                           "legion-go-toolbox-backup.json")


async def _bg(fn, *args):
    """Hardware calls can take a moment: keep them off the event loop."""
    return await asyncio.get_event_loop().run_in_executor(None, fn, *args)


class Plugin:
    gyro = None
    hub = None
    system = None
    updates = Updates(__version__)
    restored = None        # when settings were brought back from the backup at start

    @staticmethod
    def _gyro():
        if Plugin.gyro is None:
            Plugin.gyro = GyroService(GYRO_SETTINGS, logger=decky.logger)
            Plugin.gyro.start()
        return Plugin.gyro

    @staticmethod
    def _hub():
        if Plugin.hub is None:
            gyro = Plugin._gyro()
            Plugin.hub = Hub(
                HUB_SETTINGS, logger=decky.logger,
                controller_status=lambda: gyro.get_status()["device"]["receiving"],
                state_dir=decky.DECKY_PLUGIN_SETTINGS_DIR)
            Plugin.hub.start()
        return Plugin.hub

    @staticmethod
    def _system():
        if Plugin.system is None:
            from lgo_toolbox.useros import User
            user = User(getattr(decky, "DECKY_USER", None), getattr(decky, "DECKY_USER_HOME", None))
            Plugin.system = System(decky.DECKY_PLUGIN_SETTINGS_DIR, logger=decky.logger, user=user)
            Plugin.system.start()
        return Plugin.system

    @staticmethod
    def _adopt_gyro_settings():
        """Carry tuning and calibration over from the stand-alone
        "Legion Go Gyro" plugin the first time this one runs."""
        if os.path.exists(GYRO_SETTINGS):
            return
        old = os.path.join(os.path.dirname(decky.DECKY_PLUGIN_SETTINGS_DIR.rstrip("/")),
                           "Legion Go Gyro", "settings.json")
        try:
            with open(old, "rb") as src:
                data = src.read()
            with open(GYRO_SETTINGS, "wb") as dst:
                dst.write(data)
            decky.logger.info("Adopted settings from Legion Go Gyro")
        except OSError:
            pass

    @staticmethod
    def _restore_after_reinstall(hub):
        """No settings yet but a backup in the home folder: a reinstall, or an
        update from 2.9.0 or older (whose uninstall step deleted the settings
        Decky's update runs it too). Take the backup over."""
        data = backup.load(BACKUP_FILE)
        if data.get("error") or not isinstance(data.get("toolbox"), dict):
            return
        hub.restore(data["toolbox"])
        if isinstance(data.get("gyro"), dict):
            Plugin._gyro().update_settings(data["gyro"])
        if isinstance(data.get("system"), dict):
            Plugin._system().restore(data["system"])
        Plugin.restored = data.get("saved_at") or "?"
        decky.logger.info("Settings restored from the backup of %s", Plugin.restored)

    # ---- lifecycle -------------------------------------------------------

    async def _main(self):
        decky.logger.info("Legion Go Toolbox %s loading", __version__)
        try:
            os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
            fresh = not os.path.exists(HUB_SETTINGS)
            Plugin._adopt_gyro_settings()
            hub = Plugin._hub()
            Plugin._system()
            if fresh:
                Plugin._restore_after_reinstall(hub)
        except Exception:
            decky.logger.exception("Failed to start")

    async def _unload(self):
        hub, gyro, system = Plugin.hub, Plugin.gyro, Plugin.system
        Plugin.hub = Plugin.gyro = Plugin.system = None
        if system is not None:
            await _bg(system.stop)
        if hub is not None:
            await _bg(hub.stop)
        if gyro is not None:
            await _bg(gyro.close)
        decky.logger.info("Legion Go Toolbox unloaded")

    async def _uninstall(self):
        # Decky runs this when it updates the plugin too, so the settings stay
        # (they are in ~/homebrew/settings/Legion Go Toolbox/). Battery
        # playtime's requests to Frame Suite go: Frame Suite takes back the
        # lsfg-vk profiles it made for them only if the file stays away for
        # ten minutes, so an update in between changes nothing.
        try:
            from lgo_toolbox.suite import Suite, write_requests
            write_requests(Suite().home(), {})
        except Exception:
            pass

    async def _migration(self):
        pass

    # ---- whole plugin ----------------------------------------------------

    async def get_state(self):
        hub, gyro = Plugin._hub(), Plugin._gyro()
        return {
            "version": __version__,
            "restored_backup": Plugin.restored,
            "caps": await _bg(hub.capabilities, True),
            "settings": hub.get_settings(),
            "status": await _bg(hub.status),
            "gyro": {
                "settings": gyro.get_settings(),
                "defaults": gyro.get_defaults(),
                "status": gyro.get_status(),
            },
        }

    async def get_status(self):
        hub = Plugin._hub()
        st = await _bg(hub.status)
        st["watts_history"] = Plugin._system().watts_history()
        return {"hub": st, "gyro": Plugin._gyro().get_status()}

    async def update_settings(self, patch):
        return await _bg(Plugin._hub().update, patch)

    async def reset_settings(self):
        return await _bg(Plugin._hub().reset)

    async def delete_power_profile(self, key):
        return await _bg(Plugin._hub().delete_power_profile, str(key))

    async def smooth_plan(self, fps, app_id=None):
        return await _bg(Plugin._hub().smooth_plan, int(fps),
                         None if app_id is None else int(app_id))

    async def set_smooth_game(self, app_id, fps, name, prefix, added_command, fg=0,
                              fgmod=False):
        return await _bg(Plugin._hub().set_smooth_game, app_id,
                         None if fps is None else int(fps), name, prefix, added_command,
                         int(fg) if fg in (0, 1, 2, 3, 4) else 0, bool(fgmod))

    async def set_playtime_goal(self, app_id, hours, floor=30, allow_fg=True, name=""):
        return await _bg(Plugin._hub().set_playtime_goal, int(app_id),
                         None if hours is None else float(hours),
                         int(floor) if floor in (30, 36, 40, 45, 48, 60) else 30,
                         bool(allow_fg), str(name or "")[:120])

    async def restart_playtime(self, app_id):
        return await _bg(Plugin._hub().restart_playtime, int(app_id))

    async def check_updates(self, force=False):
        return await _bg(Plugin.updates.check, bool(force))

    async def acpi_install_start(self):
        return await _bg(Plugin._hub().acpi_install_start)

    # ---- backup ------------------------------------------------------------
    async def backup_info(self):
        return await _bg(backup.info, BACKUP_FILE)

    async def backup_settings(self):
        hub, gyro = Plugin._hub(), Plugin._gyro()
        return await _bg(backup.save, BACKUP_FILE, __version__,
                         hub.get_settings(), gyro.get_settings(),
                         Plugin._system().get_settings())

    async def restore_settings(self):
        """Returns {"ok", "error", "settings", "gyro"}."""
        data = await _bg(backup.load, BACKUP_FILE)
        if data.get("error"):
            return {"ok": False, "error": data["error"]}
        hub, gyro = Plugin._hub(), Plugin._gyro()
        settings = await _bg(hub.restore, data["toolbox"])
        if isinstance(data.get("gyro"), dict):
            gyro.update_settings(data["gyro"])
        if isinstance(data.get("system"), dict):
            await _bg(Plugin._system().restore, data["system"])
        return {"ok": True, "error": None, "settings": settings,
                "gyro": gyro.get_settings()}

    async def delete_fan_profile(self, key):
        return await _bg(Plugin._hub().delete_fan_profile, str(key))

    async def set_game_controller(self, app_id, kind, name):
        """kind None removes the game's own controller type."""
        return await _bg(Plugin._hub().set_game_controller, app_id, kind, name)

    async def set_running_app(self, app_id, name):
        await _bg(Plugin._hub().set_running_app, app_id, name)

    async def on_suspend(self):
        await _bg(Plugin._system().before_sleep)
        await _bg(Plugin._hub().on_suspend)

    async def on_resume(self):
        await _bg(Plugin._hub().on_resume)

    # ---- System tab: speaker EQ, sleep guard, Steam update check ----------

    async def system_state(self):
        return await _bg(Plugin._system().state)

    async def system_update(self, patch):
        return await _bg(Plugin._system().update, patch)

    async def steam_check(self):
        system = Plugin._system()
        await _bg(system.steam_check)
        return await _bg(system.state)

    async def steam_snapshots(self):
        return await _bg(Plugin._system().steam.snapshots)

    async def steam_snapshot_now(self):
        name = await _bg(Plugin._system().steam.snapshot, "saved by hand", True)
        return {"ok": name is not None, "name": name,
                "error": None if name else "Nothing to back up was found"}

    async def steam_restore(self, name):
        return await _bg(Plugin._system().steam.restore, str(name))

    async def steam_hold(self, on):
        system = Plugin._system()
        out = await _bg(system.steam.set_hold, bool(on))
        await _bg(system.steam_check)
        return out

    async def sleep_clear(self):
        system = Plugin._system()
        await _bg(system.sleep.clear)
        return await _bg(system.state)

    # ---- gyro ------------------------------------------------------------

    async def gyro_set_settings(self, patch):
        return Plugin._gyro().update_settings(patch)

    async def gyro_reset_settings(self):
        return Plugin._gyro().reset_settings()

    async def gyro_calibrate(self, target):
        svc = Plugin._gyro()
        name = svc.request_calibration(target)
        if name is None:
            return "nodata"
        return (await Plugin._await_calibration(svc, [name]))[name]

    async def gyro_calibrate_all(self):
        svc = Plugin._gyro()
        return await Plugin._await_calibration(svc, svc.request_calibration_all())

    @staticmethod
    async def _await_calibration(svc, names):
        serials = {n: svc.calibration_state(n)[1] for n in names}
        results = {}
        for _ in range(90):
            if len(results) == len(names):
                break
            await asyncio.sleep(0.1)
            for n in names:
                _, serial, result = svc.calibration_state(n)
                if n not in results and serial != serials[n]:
                    results[n] = result or "nodata"
        for n in names:
            results.setdefault(n, "nodata")
        return results
