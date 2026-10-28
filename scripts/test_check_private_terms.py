"""Tests for check_private_terms.py, using a stand-in term in a scratch repo."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_private_terms.py")
TERM = "zebra"


class CheckPrivateTerms(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        (self.repo / "keep.txt").write_text(f"an old line about {TERM}\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def check(self, *args: str, terms: str = TERM, stdin: str = "", **env: str):
        run_env = {**os.environ, "PRIVATE_TERMS": terms, "HOME": str(self.repo), **env}
        run_env.pop("GITHUB_ACTIONS", None)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.repo,
            input=stdin,
            capture_output=True,
            text=True,
            env=run_env,
        )
        return result.returncode, result.stdout + result.stderr

    def stage(self, name: str, content: bytes) -> None:
        (self.repo / name).write_bytes(content)
        self.git("add", name)

    def test_an_added_line_is_reported_by_location_not_text(self) -> None:
        self.stage("a.txt", f"fine\nsee {TERM} here\n".encode())
        code, out = self.check("--staged")
        self.assertEqual(code, 1)
        self.assertIn("a.txt:2", out)
        self.assertNotIn(TERM, out)

    def test_a_line_that_starts_with_two_pluses_is_still_content(self) -> None:
        self.stage("a.txt", f"++ {TERM}\nand {TERM} again\n".encode())
        code, out = self.check("--staged")
        self.assertEqual(code, 1)
        self.assertIn("a.txt:1", out)
        self.assertIn("a.txt:2", out)
        self.assertNotIn(TERM, out)

    def test_removing_a_term_is_fine(self) -> None:
        self.stage("keep.txt", b"an old line, now neutral\n")
        self.assertEqual(self.check("--staged")[0], 0)

    def test_only_the_message_git_records_is_checked(self) -> None:
        msg = self.repo / "MSG"
        msg.write_text(
            "Tidy fixtures\n\n"
            f"# On branch {TERM}-cleanup\n"
            "# ------------------------ >8 ------------------------\n"
            f"-an old line about {TERM}\n"
        )
        self.assertEqual(self.check("--message-file", str(msg))[0], 0)
        msg.write_text(f"Mention {TERM} in the subject\n")
        self.assertEqual(self.check("--message-file", str(msg))[0], 1)

    def test_text_that_is_not_utf8_does_not_crash(self) -> None:
        self.stage("latin1.txt", "café\n".encode("latin-1"))
        code, out = self.check("--staged")
        self.assertEqual(code, 0, out)

    def test_an_empty_list_fails_only_where_one_is_required(self) -> None:
        self.assertEqual(self.check("--staged", terms="")[0], 0)
        self.assertEqual(self.check("--staged", terms="", REQUIRE_TERMS="true")[0], 1)


if __name__ == "__main__":
    unittest.main()
