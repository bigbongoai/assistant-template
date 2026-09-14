"""The proxy commits _categories.json by itself after the index page changes
it. Checked against a throwaway git repository, so nothing real is committed.

    python3 _askai/tests/commit_categories_test.py

Each test copies _askai/server.py into a new temporary workspace that is a git
repository. Its post-commit hook names bin/sync, which is how the proxy knows
the workspace commits every change by itself; here the hook only notes that it
ran. The tests call what the page's request calls, and one sends the request.
"""

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True       # no __pycache__ inside the throwaway repository
ASKAI = Path(__file__).resolve().parent.parent

CATEGORIES = {
    "about": "test",
    "sides": [{"id": "work", "name": "Work"}, {"id": "private", "name": "Private"}],
    "categories": [
        {"id": "acme", "name": "Acme", "side": "work", "color": "blue", "holds": "Work for Acme"},
        {"id": "home", "name": "Home", "side": "private", "color": "rose", "holds": "Life at home"},
    ],
    "tasks": {"01.alpha": {"category": "acme"}, "02.beta": {"category": "home", "guess": True}},
}
HOOK = ('#!/bin/sh\n# Stands in for bin/sync: it only notes that the hook ran.\n'
        'echo ran >> "$(git rev-parse --git-dir)/hook-ran"\n')
MOVED = "Categories: moved 01.alpha from Acme to Home\n\nMade on the index page."


class Workspace:
    """A temporary workspace with its own copy of the proxy, loaded as a module."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="askai-commit-"))
        (self.root / "_askai").mkdir()
        shutil.copy(ASKAI / "server.py", self.root / "_askai" / "server.py")
        for folder in ("01.alpha", "02.beta", "03.gamma"):
            (self.root / "tasks" / folder).mkdir(parents=True)
            (self.root / "tasks" / folder / "index.html").write_text(f"<title>{folder}</title>")
        (self.root / "notes.md").write_text("notes\n")
        spec = importlib.util.spec_from_file_location(f"askai_server_{id(self)}",
                                                      self.root / "_askai" / "server.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.server.Handler.log_message = lambda *args: None
        # Written by the proxy's own writer, so an unchanged write is byte for byte the same.
        self.server.write_json_atomic(self.server.CATEGORIES_FILE, CATEGORIES)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")
        hook = self.root / ".git" / "hooks" / "post-commit"
        hook.write_text(HOOK)
        hook.chmod(0o755)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True).stdout

    def change(self, action: str, **data) -> None:
        status, body = self.server.change_categories(action, data)
        assert status == 200 and body.get("ok"), body

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def message(self) -> str:
        return self.git("log", "-1", "--format=%B").strip()

    def files_in_last_commit(self) -> list[str]:
        return self.git("show", "--name-only", "--format=", "HEAD").split()

    def hook_runs(self) -> int:
        ran = self.root / ".git" / "hook-ran"
        return len(ran.read_text().splitlines()) if ran.exists() else 0


class CommitCategories(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = Workspace()
        self.addCleanup(shutil.rmtree, self.ws.root, True)

    # -- the three things asked for ---------------------------------------

    def test_a_change_commits_that_file_alone_with_what_changed(self) -> None:
        start = self.ws.head()
        self.ws.change("move", task="01.alpha", category="home")
        self.assertTrue(self.ws.server.commit_categories())
        self.assertEqual(self.ws.git("rev-parse", "HEAD~1").strip(), start)
        self.assertEqual(self.ws.files_in_last_commit(), ["_categories.json"])
        self.assertEqual(self.ws.message(), MOVED)
        self.assertEqual(self.ws.git("status", "--porcelain"), "")
        self.assertEqual(self.ws.hook_runs(), 1, "the post-commit hook, which runs bin/sync, did not run")

    def test_an_unchanged_write_commits_nothing(self) -> None:
        start = self.ws.head()
        written = self.ws.server.CATEGORIES_FILE.stat().st_mtime_ns
        self.ws.change("move", task="01.alpha", category="acme")      # where it already is
        self.assertNotEqual(self.ws.server.CATEGORIES_FILE.stat().st_mtime_ns, written, "the page did not write")
        self.assertFalse(self.ws.server.commit_categories())
        self.assertEqual(self.ws.head(), start)
        self.assertEqual(self.ws.hook_runs(), 0)

    def test_other_staged_and_unsaved_files_stay_out(self) -> None:
        (self.ws.root / "notes.md").write_text("an unsaved edit\n")
        (self.ws.root / "staged.md").write_text("staged, not committed\n")
        self.ws.git("add", "staged.md")
        self.ws.change("move", task="01.alpha", category="home")
        self.assertTrue(self.ws.server.commit_categories())
        self.assertEqual(self.ws.files_in_last_commit(), ["_categories.json"])
        self.assertEqual(self.ws.git("diff", "--cached", "--name-only").split(), ["staged.md"])
        self.assertEqual(self.ws.git("diff", "--name-only").split(), ["notes.md"])

    # -- the message --------------------------------------------------------

    def test_changes_made_before_the_commit_are_all_named(self) -> None:
        self.ws.change("move", task="01.alpha", category="home")
        self.ws.change("move", task="03.gamma", category="acme", guess=True)
        self.ws.change("update", id="home", name="Household")
        self.assertTrue(self.ws.server.commit_categories())
        self.assertEqual(self.ws.message(), "Categories: 3 changes made on the index page\n\n"
                                            "- renamed category Home to Household\n"
                                            "- moved 01.alpha from Acme to Household\n"
                                            "- filed 03.gamma under Acme, as a guess")
        self.assertFalse(self.ws.server.commit_categories(), "a second commit found something left")

    def test_every_kind_of_change_is_worded(self) -> None:
        changes = self.ws.server.category_changes
        new = json.loads(json.dumps(CATEGORIES))
        new["categories"][0].update(side="private", color="teal", holds="Other work")
        new["categories"].append({"id": "gym", "name": "Gym", "side": "private", "color": "green", "holds": ""})
        new["tasks"]["02.beta"] = {"category": "home"}
        del new["tasks"]["01.alpha"]
        self.assertEqual(changes(CATEGORIES, new), [
            "moved category Acme from Work to Private",
            "recoloured category Acme from blue to teal",
            "changed what goes in category Acme",
            "new category Gym, under Private",
            "moved 01.alpha from Acme back to not sorted",
            "kept 02.beta in Home, no longer a guess",
        ])
        gone = json.loads(json.dumps(new))
        gone["categories"] = [c for c in gone["categories"] if c["id"] != "gym"]
        self.assertEqual(changes(new, gone), ["deleted category Gym"])
        swapped = json.loads(json.dumps(CATEGORIES))
        swapped["categories"].reverse()
        swapped["tasks"]["01.alpha"]["guess"] = True
        self.assertEqual(changes(CATEGORIES, swapped),
                         ["changed the order of the categories", "marked 01.alpha in Acme as a guess"])
        self.assertEqual(self.ws.server.category_changes_message(CATEGORIES, CATEGORIES),
                         "Categories: written again on the index page, with no category or task changed")

    def test_the_first_file_is_committed_too(self) -> None:
        self.ws.git("rm", "-q", "_categories.json")
        self.ws.git("commit", "-q", "-m", "no categories yet")
        self.ws.change("add", name="Paddle", side="private")
        self.assertTrue(self.ws.server.commit_categories())
        self.assertEqual(self.ws.files_in_last_commit(), ["_categories.json"])
        self.assertEqual(self.ws.message(), "Categories: new category Paddle, under Private\n\nMade on the index page.")

    # -- where it does not commit, and when git is busy ---------------------

    def test_nothing_is_committed_where_the_hook_does_not_run_bin_sync(self) -> None:
        (self.ws.root / ".git" / "hooks" / "post-commit").unlink()
        start = self.ws.head()
        self.ws.change("move", task="01.alpha", category="home")
        self.assertFalse(self.ws.server.commit_categories())
        self.assertEqual(self.ws.head(), start)
        self.assertEqual(self.ws.git("status", "--porcelain").strip(), "M _categories.json")

    def test_a_busy_git_is_tried_again_then_left_and_logged(self) -> None:
        self.ws.server.COMMIT_TRY_SECONDS = 1.0
        lock = self.ws.root / ".git" / "index.lock"
        lock.write_text("")
        self.ws.change("move", task="01.alpha", category="home")
        start, began, log = self.ws.head(), time.monotonic(), io.StringIO()
        with contextlib.redirect_stderr(log):
            self.assertFalse(self.ws.server.commit_categories())
        self.assertGreaterEqual(time.monotonic() - began, 1.0, "it gave up without trying again")
        self.assertEqual(self.ws.head(), start)
        self.assertIn("could not commit _categories.json", log.getvalue())
        self.assertIn("index.lock", log.getvalue())
        lock.unlink()
        self.assertTrue(self.ws.server.commit_categories())
        self.assertEqual(self.ws.message(), MOVED)

    def test_a_lock_let_go_within_the_wait_still_commits(self) -> None:
        lock = self.ws.root / ".git" / "index.lock"
        lock.write_text("")
        threading.Timer(1.0, lock.unlink).start()
        self.ws.change("move", task="01.alpha", category="home")
        began = time.monotonic()
        self.assertTrue(self.ws.server.commit_categories())
        self.assertGreaterEqual(time.monotonic() - began, 0.9)
        self.assertEqual(self.ws.files_in_last_commit(), ["_categories.json"])

    def test_the_page_gets_its_answer_while_git_is_busy(self) -> None:
        self.ws.server.COMMIT_TRY_SECONDS = 5.0
        lock = self.ws.root / ".git" / "index.lock"
        lock.write_text("")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.ws.server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_port}/api/categories",
            data=json.dumps({"action": "move", "task": "01.alpha", "category": "home"}).encode(),
            headers={"Content-Type": "application/json"})
        start, began = self.ws.head(), time.monotonic()
        with urllib.request.urlopen(request, timeout=5) as answer:
            body = json.load(answer)
        self.assertLess(time.monotonic() - began, 0.5, "the request waited for git")
        self.assertTrue(body["ok"])
        self.assertEqual(self.ws.head(), start)
        lock.unlink()
        for _ in range(80):
            if self.ws.head() != start:
                break
            time.sleep(0.1)
        self.assertEqual(self.ws.message(), MOVED)
        self.assertEqual(self.ws.files_in_last_commit(), ["_categories.json"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
