#!/usr/bin/env python3
"""Refuse text that mentions things a maintainer's employer would keep private.

This repo is public, and the people working on it use it at their day jobs, so
examples and notes drift in from work: a ticket number, an internal hostname, a
product bug used as test data. The terms to look for can't live in the repo,
because the list would publish them. They come from, in order:

  PRIVATE_TERMS                      environment variable (CI reads a secret)
  ~/.config/acq/private-terms        a local file, one regex per line

Each line is a case-insensitive Python regex; blank lines and lines starting
with # are ignored. With no terms configured the check passes, so contributors
without a list aren't blocked.

Findings name where a match is, never the matched text, because CI logs on a
public repo are public too.

  check_private_terms.py --staged            added lines in the git index
  check_private_terms.py --diff A..B         added lines in a commit range
  check_private_terms.py --messages A..B     commit messages in a range
  check_private_terms.py --message-file F    one commit message (commit-msg hook)
  check_private_terms.py --text NAME         stdin, reported as NAME
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

TERMS_FILE = Path.home() / ".config" / "acq" / "private-terms"


def load_patterns() -> list[re.Pattern[str]]:
    raw = os.environ.get("PRIVATE_TERMS") or (
        TERMS_FILE.read_text(encoding="utf-8", errors="replace") if TERMS_FILE.exists() else ""
    )
    lines = [line.strip() for line in raw.splitlines()]
    return [re.compile(line, re.IGNORECASE) for line in lines if line and not line.startswith("#")]


def git(*args: str) -> str:
    # Replace undecodable bytes rather than crash: a non-UTF-8 file would
    # otherwise block the commit with a traceback instead of a finding.
    return subprocess.run(["git", *args], check=True, capture_output=True, encoding="utf-8", errors="replace").stdout


def added_lines(diff: str):
    """Yield (path, line number, text) for every added line of a unified diff.

    "+++ " names a file only in a file's header, before its first hunk. Inside
    a hunk it is an added line that itself starts with "++ ", and reading it as
    a header would both skip it and report its text as a path.
    """
    path, lineno, in_header = "?", 0, False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_header = True
        elif in_header and line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@"):
            in_header = False
            lineno = int(re.search(r"\+(\d+)", line).group(1))
        elif in_header:
            continue
        elif line.startswith("+"):
            yield path, lineno, line[1:]
            lineno += 1
        elif not line.startswith("-"):
            lineno += 1


def commit_message(raw: str) -> str:
    """The message git will record: without its comment lines or the verbose diff.

    The commit-msg hook sees the file before git strips it, including the
    branch name, staged paths and, with `git commit -v`, the whole diff below
    the scissors line, removed lines too.
    """
    kept = []
    for line in raw.splitlines():
        if re.match(r"^# -+ >8 -+$", line):
            break
        if not line.startswith("#"):
            kept.append(line)
    return "\n".join(kept)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--diff")
    ap.add_argument("--messages")
    ap.add_argument("--message-file")
    ap.add_argument("--text")
    args = ap.parse_args()

    patterns = load_patterns()
    if not patterns:
        # In CI an empty list usually means the secret didn't arrive, and a
        # green check would claim something was checked. Fork PRs never get
        # secrets, so they only warn; elsewhere the workflow sets REQUIRE_TERMS.
        if os.environ.get("REQUIRE_TERMS") == "true":
            print("check_private_terms: PRIVATE_TERMS is empty, so nothing was checked.")
            return 1
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::warning::check_private_terms: no terms available (expected on fork PRs); nothing was checked.")
        print("check_private_terms: no terms configured; skipping.")
        return 0

    def hit(text: str) -> bool:
        return any(p.search(text) for p in patterns)

    findings: list[str] = []
    diff_spec = ["--cached"] if args.staged else [args.diff] if args.diff else None
    if diff_spec:
        diff = git("diff", "--unified=0", "--no-color", "--no-ext-diff", *diff_spec)
        findings += [f"{path}:{n}" for path, n, text in added_lines(diff) if hit(text)]
    if args.messages:
        for sha in git("rev-list", args.messages).split():
            if hit(git("log", "-1", "--format=%B", sha)):
                findings.append(f"commit message of {sha[:12]}")
    if args.message_file and hit(commit_message(Path(args.message_file).read_text(encoding="utf-8", errors="replace"))):
        findings.append("this commit message")
    if args.text and hit(sys.stdin.read()):
        findings.append(args.text)

    if findings:
        print("These mention something on the private-terms list (text not shown, on purpose):")
        for f in findings:
            print(f"  {f}")
        print("This is a public repo; use neutral examples instead. See AGENTS.md.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
