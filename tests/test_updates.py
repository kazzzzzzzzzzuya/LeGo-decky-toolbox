import unittest

import helpers  # noqa: F401  (sets up sys.path)

from lgo_toolbox import updates

REL = lambda tag, pre=False, draft=False, zip_name="legion-go-toolbox.zip", digest="sha256:" + "a" * 64: {
    "tag_name": tag, "prerelease": pre, "draft": draft, "published_at": "2026-11-15T10:00:00Z", "body": "notes",
    "assets": [{"name": zip_name, "browser_download_url": "https://x/%s.zip" % tag, "digest": digest},
               {"name": "Legion-Go-Toolbox-Manual.pdf", "browser_download_url": "https://x/m.pdf"}]}


class Releases(unittest.TestCase):
    def test_newest_first_and_only_real_releases(self):
        r = updates.parse([REL("v2.8.0"), REL("v2.10.0"), REL("v2.9.0"), REL("v3.0.0", pre=True),
                           REL("v3.1.0", draft=True), REL("v2.7.1", zip_name="other.zip"), REL("nightly"),
                           "junk", REL("v2.6.0", digest="")], "2.9.0")
        self.assertTrue(r["ok"])
        self.assertEqual([x["version"] for x in r["releases"]], ["2.10.0", "2.9.0", "2.8.0", "2.6.0"])
        self.assertEqual((r["latest"], r["newer"]), ("2.10.0", True))      # 10 > 9, not text order
        self.assertEqual(r["releases"][0]["sha256"], "a" * 64)
        self.assertEqual(r["releases"][-1]["sha256"], "")

    def test_up_to_date_and_nothing_found(self):
        self.assertFalse(updates.parse([REL("v2.9.0")], "2.9.0")["newer"])
        self.assertFalse(updates.parse([], "2.9.0")["ok"])
        self.assertFalse(updates.parse({"message": "rate limited"}, "2.9.0")["ok"])

    def test_answers_are_kept_for_a_while_and_errors_reported(self):
        calls, now = [], [0.0]

        def fetch():
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("offline")
            return [REL("v2.10.0")]

        u = updates.Updates("2.9.0", fetch_fn=fetch, clock=lambda: now[0])
        self.assertTrue(u.check()["newer"])
        self.assertTrue(u.check()["newer"])
        self.assertEqual(len(calls), 1)                  # cached
        now[0] += updates.TTL_S + 1
        u.check()
        self.assertEqual(len(calls), 2)
        r = u.check(force=True)
        self.assertEqual((r["ok"], r["error"]), (False, "offline"))


if __name__ == "__main__":
    unittest.main()
