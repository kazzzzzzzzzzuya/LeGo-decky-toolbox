import calendar
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
import unittest

import helpers  # noqa: F401  (sets up sys.path)
from lgo_toolbox import cloud_saves as cs

ACCT = 12345678
STEAMID = cs.STEAMID64_BASE + ACCT
SHA_A = "a" * 40
SHA_B = "b" * 40


class FakeUser(object):
    uid, gid, name = 1000, 1000, "deck"

    def __init__(self, home):
        self.home = home
        self.runtime_dir = home
        self.calls = []
        self.answers = {}           # CLI command -> stdout
        self.spawned = []

    def path(self, *p):
        return os.path.join(self.home, *p)

    def run(self, cmd, timeout=5.0, env=None):
        self.calls.append(cmd[2:])
        out = self.answers.get(cmd[2])
        if callable(out):
            out = out(cmd[3:])
        return (0, out, "") if out is not None else (1, "", "boom")

    def spawn(self, cmd, log_path=None, env=None):
        self.spawned.append(cmd)


class FakeSteam(object):
    def __init__(self, root, libs=None):
        self.steam_root = root
        self.libs = libs

    def steam_libs(self):
        return self.libs


class SlsConfig(unittest.TestCase):
    def test_block_list_is_read(self):
        r = cs.read_sls_config("DisableCloud: no\nAdditionalApps:\n  - 10   # Counter-Strike\n  - 3489700\n"
                               "DecryptionKeys:\n  1: abc\n")
        self.assertEqual(r["apps"], [10, 3489700])
        self.assertFalse(r["cloud_blocked"])
        self.assertEqual(r["problems"], [])

    def test_what_cloudredirect_skips_is_named(self):
        r = cs.read_sls_config('DisableCloud: no\nAdditionalApps:\n  - "3489700"\n  - 20\n')
        self.assertEqual(r["apps"], [20])
        self.assertEqual(r["skipped"], ['"3489700"'])
        self.assertIn("without quotes", r["problems"][0])

        r = cs.read_sls_config("DisableCloud: no\nAdditionalApps: [10, 20]\n")
        self.assertEqual(r["apps"], [])
        self.assertIn("one line", r["problems"][0])

        r = cs.read_sls_config("DisableCloud: no\nAdditionalApps: # mine\n  - 10\n")
        self.assertEqual(r["apps"], [])
        self.assertIn("remove what follows", r["problems"][0])

        r = cs.read_sls_config("DisableCloud: no\r\nAdditionalApps:\r\n  - 10\r\n")
        self.assertEqual(r["apps"], [])
        self.assertIn("Windows line endings", r["problems"][0])

    def test_zero_is_no_game_and_not_a_problem(self):
        # Seen on the device: "- 0" in AdditionalApps (the cloud's app 0 is CloudRedirect's account data).
        r = cs.read_sls_config("DisableCloud: no\nAdditionalApps:\n  - 0\n  - 3489700\n  - abc\n")
        self.assertEqual(r["apps"], [3489700])
        self.assertEqual(r["problems"], ["CloudRedirect skips 'abc' in AdditionalApps: not a game number."])

    def test_disable_cloud(self):
        self.assertTrue(cs.read_sls_config("AdditionalApps:\n  - 10\n")["cloud_blocked"])
        self.assertTrue(cs.read_sls_config("DisableCloud: yes\nAdditionalApps:\n  - 10\n")["cloud_blocked"])
        self.assertFalse(cs.read_sls_config("DisableCloud: False\nAdditionalApps:\n  - 10\n")["cloud_blocked"])


LOG = """[10:00:00][INFO] CloudRedirect build 2.6.6
[10:01:00][INFO] [NS-CL] GetAppFileChangelist app=10: INCONCLUSIVE cloud fetch -- serving 3 files
[10:30:00][INFO] [NS] BeginBatch app=10 batchId=1 assignedCN=4 appBuildId=1 uploads=2 deletes=0
[10:30:01][INFO] [NS-UP] CommitFileUpload app=10 file=%WinAppDataLocal%a.sav succeeded=1
[10:30:01][INFO] [NS-UP] CommitFileUpload app=10 file=%WinAppDataLocal%b.sav succeeded=1
[10:30:02][INFO] [NS] CompleteBatch(pub): publish 1/4 succeeded for app 10 at CN=4
[11:00:00][INFO] CloudRedirect build 2.6.6
[11:05:00][INFO] [NS] BeginBatch app=20 batchId=2 assignedCN=2 appBuildId=1 uploads=1 deletes=0
[11:05:03][INFO] [NS] CompleteBatch(pub): all publish attempts exhausted for app 20 (CN=2)
[11:06:00][INFO] [GDrive] curl failed: 60 [SSL peer certificate] verify=20 (GET x)
[11:07:00][INFO] [NS-CL] GetAppFileChangelist app=30: INCONCLUSIVE cloud fetch -- serving 0 files
"""


class Log(unittest.TestCase):
    def test_events_per_game_and_session(self):
        r = cs.parse_log(LOG.encode())
        self.assertEqual(r["sessions"], 2)
        up = r["apps"][10]["upload"]
        self.assertEqual((up["at"], up["result"], up["files"], up["ok_files"], up["session"]), ("10:30", "ok", 2, 2, 1))
        self.assertTrue(r["apps"][10]["start"]["offline"])
        self.assertEqual(r["apps"][20]["upload"]["result"], "failed")
        self.assertEqual(r["apps"][20]["upload"]["why"], "publish")
        self.assertEqual(r["session"]["curl_failures"], 1)
        self.assertEqual(r["session"]["started"], "11:00")
        self.assertIn("SSL peer certificate", r["session"]["curl_last"])
        r = cs.parse_log(b"[09:00:00][INFO] [GDrive] curl failed: 60 (GET https://x)\n")   # the official build
        self.assertEqual(r["session"]["curl_last"], "curl 60 (certificate check failed)")


class CloudCompare(unittest.TestCase):
    def test_content_addressed_and_named_blobs(self):
        files = [{"path": "%d/10/blobs/%s" % (ACCT, SHA_A), "size": 5, "modified_time": 1700000000},
                 {"path": "blobs/SaveGames/b.sav/" + SHA_B.upper(), "size": 7, "modified_time": 1700000100},
                 {"path": "cn.cloudredirect", "size": 1, "modified_time": 1700000200},
                 {"path": "staging/9/blobs/x", "size": 1, "modified_time": 1800000000}]
        r = cs.compare_cloud(files, ACCT, 10, {"a.sav": (SHA_A, 5), "b.sav": (SHA_B, 7), "c.sav": ("c" * 40, 1)})
        self.assertEqual((r["files"], r["bytes"], r["compared"], r["matched"]), (2, 12, 3, 2))
        self.assertEqual(r["missing"], ["c.sav"])
        self.assertEqual(r["newest"], 1700000200)            # staging is not "in the cloud" yet

    def test_cli_output(self):
        self.assertEqual(cs.parse_cli_json('noise\n{"success":true}\n'), {"success": True})
        self.assertIsNone(cs.parse_cli_json("Error: x"))


class Status(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.state = os.path.join(self.home, "state")
        os.makedirs(self.state)
        self.user = FakeUser(self.home)
        steam = os.path.join(self.home, ".local/share/Steam")
        self.put(".local/share/Steam/config/loginusers.vdf",
                 '"users"\n{\n\t"%d"\n\t{\n\t\t"AccountName"\t"x"\n\t\t"MostRecent"\t"1"\n\t}\n}\n' % STEAMID)
        self.put(".local/share/Steam/steamapps/appmanifest_10.acf", '"AppState"\n{\n\t"name"\t"Game Ten"\n}\n')
        self.put(".config/SLSsteam/config.yaml", "DisableCloud: no\nAdditionalApps:\n  - 10\n  - 20\n  - '30'\n")
        self.put(".local/share/CloudRedirect/cloud_redirect.so", "\x7fELF\x02rest")
        self.put(".local/share/CloudRedirect/cloud_redirect_cli", "\x7fELF\x02rest")
        self.put(".config/CloudRedirect/config.json", '{"provider": "gdrive"}')
        self.put(".config/CloudRedirect/cloud_redirect.log", LOG)
        self.manifest(10, {"a.sav": {"sha": SHA_A, "ts": 1, "size": 5}, "b.sav": {"sha": SHA_B, "ts": 1, "size": 7}},
                      age=600)
        self.steam = FakeSteam(steam, libs={"/x/steamclient.so", "/h/cloud_redirect.so"})
        self.c = cs.CloudSaves(self.user, self.state, self.steam)

    def put(self, rel, text):
        p = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def manifest(self, app, data, age=0):
        p = self.put(".config/CloudRedirect/storage/%d/%d/manifest.cloudredirect" % (ACCT, app), json.dumps(data))
        t = time.time() - age
        os.utime(p, (t, t))

    def cli(self, app_ids=("10",), files=None):
        self.user.answers = {
            "auth-status": '{"authenticated":true,"token_path":"x"}',
            "list-remote-app-ids": json.dumps({"success": True, "app_ids": list(app_ids)}),
            "list-remote-app-files": lambda a: json.dumps({"success": True, "complete": True, "files": files or [
                {"path": "%d/10/blobs/%s" % (ACCT, SHA_A), "size": 5, "modified_time": 1700000000},
                {"path": "%d/10/blobs/%s" % (ACCT, SHA_B), "size": 7, "modified_time": 1700000000}]}),
        }

    def wait(self):
        for _ in range(200):
            if not self.c.checking():
                return
            time.sleep(0.01)
        self.fail("cloud check did not finish")

    def game(self, st, app):
        return [g for g in st["games"] if g["appid"] == app][0]

    def test_status_from_log_record_and_config(self):
        st = self.c.state()
        self.assertTrue(st["installed"] and st["loaded"] and st["can_check"])
        self.assertEqual(st["account"], ACCT)
        self.assertEqual(st["provider_label"], "Google Drive")
        g10 = self.game(st, 10)
        self.assertEqual((g10["name"], g10["level"], g10["files"], g10["bytes"]), ("Game Ten", "ok", 2, 12))
        self.assertEqual(g10["last_upload"], {"at": "10:30", "this_session": False, "result": "ok", "files": 2})
        g20 = self.game(st, 20)
        self.assertEqual(g20["level"], "fail")
        self.assertIn("could not be finished", g20["problem"])
        g30 = self.game(st, 30)                       # '30' in quotes: CloudRedirect skips it
        self.assertEqual(g30["level"], "fail")
        self.assertIn("skips this game", g30["problem"])
        self.assertTrue(any("connection failure" in p for p in st["problems"]))

    def test_cloud_check_compares_and_finds_a_missing_game(self):
        self.cli(app_ids=["20"])
        self.assertTrue(self.c.start_check())
        self.wait()
        self.assertNotIn(["delete-remote-app"], [c[:1] for c in self.user.calls])
        st = self.c.state()
        g10 = self.game(st, 10)
        self.assertEqual(g10["level"], "fail")
        self.assertIn("Not in the cloud", g10["problem"])
        self.assertTrue(st["signed_in"])

        self.cli(app_ids=["10"])
        self.c.start_check()
        self.wait()
        g10 = self.game(self.c.state(), 10)
        self.assertEqual(g10["level"], "ok")
        self.assertEqual((g10["cloud"]["matched"], g10["cloud"]["compared"]), (2, 2))

    def test_only_read_only_commands(self):
        self.cli()
        self.c.start_check()
        self.wait()
        used = {c[0] for c in self.user.calls}
        self.assertEqual(used, {"auth-status", "list-remote-app-ids", "list-remote-app-files"})

    def test_after_a_sync_the_cloud_is_asked_once(self):
        self.cli()
        self.c.tick(now=time.time())
        self.wait()
        self.assertEqual([c[0] for c in self.user.calls].count("list-remote-app-files"), 1)
        self.user.calls.clear()
        self.c._tick_at = self.c._auto_after = 0
        self.c.tick(now=time.time())                   # nothing changed: not asked again
        self.wait()
        self.assertEqual(self.user.calls, [])
        self.manifest(10, {"a.sav": {"sha": SHA_A, "size": 5}}, age=0)
        self.c._tick_at = self.c._auto_after = 0
        self.c.tick(now=time.time())                   # changed just now: wait for CloudRedirect to finish
        self.assertEqual(self.user.calls, [])
        self.manifest(10, {"a.sav": {"sha": SHA_A, "size": 5}}, age=200)
        self.c._tick_at = self.c._auto_after = 0
        self.c.tick(now=time.time())
        self.wait()
        self.assertIn(["list-remote-app-files", "gdrive", str(ACCT), "10"], self.user.calls)

    def test_signed_out_and_not_loaded(self):
        self.user.answers = {"auth-status": '{"authenticated":false}'}
        self.c.start_check()
        self.wait()
        self.steam.libs = {"/x/steamclient.so"}
        st = self.c.state()
        self.assertFalse(st["loaded"])
        self.assertTrue(any("not signed in" in p for p in st["problems"]))
        self.assertTrue(any("not loaded" in p for p in st["problems"]))

    def test_arch_mismatch_is_explained(self):
        client = self.put("rt64/steamclient.so", "\x7fELF\x02rest")
        self.put(".local/share/CloudRedirect/cloud_redirect.so", "\x7fELF\x01rest")
        self.steam.libs = {client}
        st = self.c.state()
        self.assertTrue(any("32-bit, but Steam runs as 64-bit" in p for p in st["problems"]))

    def test_alerts_once(self):
        first = self.c.alerts()
        self.assertEqual(sorted(a["appid"] for a in first), [20, 30])
        self.assertEqual(self.c.alerts(), [])
        self.assertEqual(cs.CloudSaves(self.user, self.state, self.steam).alerts(), [])   # remembered
        with open(os.path.join(self.home, ".config/CloudRedirect/cloud_redirect.log"), "a") as f:
            f.write("[12:00:00][INFO] CloudRedirect build 2.6.6\n")                      # Steam restarted
        self.assertEqual(self.c.alerts(), [])


class Handler(http.server.BaseHTTPRequestHandler):
    games = {}
    calls = []

    def log_message(self, *a):
        pass

    def _send(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/status":
            self._send(200, {"peerCount": 1, "peersOnline": 0, "conflicts": {"emu": {}}, "syncPause": {"paused": False}})
        elif self.path == "/api/games":
            self._send(200, self.games)
        elif self.path == "/api/settings":
            self._send(200, {"cloudSync": {"enabled": True, "ready": True, "provider": "google-drive",
                                           "password": "secret"}})
        else:
            self._send(404, {"error": "no"})

    def do_POST(self):
        Handler.calls.append(("POST", self.path))
        if self.path.startswith("/api/cloud/sync-local/"):
            self._send(200, {"uploaded": 2})
        elif self.path.endswith("/sync"):
            self._send(409, {"error": "no online peers", "reason": "offline"})
        else:
            self._send(404, {"error": "no"})

    def do_DELETE(self):
        Handler.calls.append(("DELETE", self.path))
        self._send(200, {"ok": True})


class OpenSave(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        Handler.calls = []
        Handler.games = {
            "emu": {"id": "emu", "name": "Pokemon (Switch)", "savePath": "/home/deck/Emulation/saves",
                    "activeBranch": "main", "branches": {"main": {"snapshots": [
                        {"timestamp": "2026-11-20T10:00:00.000Z"}, {"timestamp": "2026-11-21T14:02:05.000Z"}]}},
                    "lastSyncedWith": {"pc": "2026-11-21T09:00:00Z"}, "savePathMissing": False},
            "sb": {"id": "sb", "name": "Stellar Blade", "appId": "",
                   "savePath": "/home/deck/.local/share/Steam/steamapps/compatdata/3489700/pfx/x"},
            "short": {"id": "short", "name": "A shortcut", "appId": "3123456789",
                      "savePath": "/home/deck/.local/share/Steam/steamapps/compatdata/3123456789/pfx/x"},
        }
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        os.makedirs(os.path.join(self.home, ".opensave"))
        with open(os.path.join(self.home, ".opensave", "daemon.addr"), "w") as f:
            f.write("127.0.0.1:%d\n" % self.srv.server_address[1])
        self.o = cs.OpenSave(FakeUser(self.home))

    def test_steam_app_of(self):
        self.assertEqual(cs.steam_app_of(Handler.games["sb"]), 3489700)
        self.assertIsNone(cs.steam_app_of(Handler.games["emu"]))
        self.assertIsNone(cs.steam_app_of(Handler.games["short"]))     # non-Steam shortcut
        self.assertEqual(cs.steam_app_of({"appId": "10"}), 10)

    def test_state_splits_steam_games_off(self):
        st = self.o.state([3489700])
        self.assertTrue(st["running"])
        self.assertEqual([g["id"] for g in st["games"]], ["short", "emu"])
        emu = [g for g in st["games"] if g["id"] == "emu"][0]
        self.assertEqual(emu["last_snapshot"], calendar.timegm((2026, 11, 21, 14, 2, 5, 0, 0, 0)))
        self.assertTrue(emu["conflict"])
        self.assertEqual([(g["id"], g["cloudredirect"]) for g in st["steam_games"]], [("sb", True)])
        self.assertEqual(st["cloud"], {"enabled": True, "ready": True, "provider": "google-drive"})

    def test_steam_games_are_never_synced_or_backed_up(self):
        self.assertEqual(self.o.backup("sb")["reason"], "steam")
        self.assertEqual(self.o.sync("sb")["reason"], "steam")
        self.assertEqual(Handler.calls, [])
        self.assertTrue(self.o.untrack("sb")["ok"])
        self.assertEqual(Handler.calls, [("DELETE", "/api/games/sb")])
        self.assertFalse(self.o.untrack("emu")["ok"])        # only Steam games are untracked from here

    def test_backup_and_sync_answers(self):
        self.assertEqual(self.o.backup("emu"), {"ok": True, "uploaded": 2})
        self.assertEqual(self.o.sync("emu")["reason"], "offline")
        self.assertFalse(self.o.backup("../x")["ok"])

    def test_not_running(self):
        self.srv.shutdown()
        self.srv.server_close()
        st = self.o.state()
        self.assertFalse(st["running"])
        self.assertFalse(st["installed"])
        self.assertFalse(self.o.start()["ok"])

    def test_address_must_be_loopback(self):
        with open(os.path.join(self.home, ".opensave", "daemon.addr"), "w") as f:
            f.write("example.com:80")
        self.assertEqual(self.o.addr(), "127.0.0.1:8383")


if __name__ == "__main__":
    unittest.main()
