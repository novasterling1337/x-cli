#!/usr/bin/env python3
"""Smoke-test the x-cli command surface against the live account.

    .venv/bin/python scripts/smoke_test.py                # reads only
    .venv/bin/python scripts/smoke_test.py --tweet <id>   # + tweet / thread / replies
    .venv/bin/python scripts/smoke_test.py --like <id>    # + write path, verified

Run this instead of a hand-rolled shell loop: the sweep needs each command's real
exit code (piping one through head/tail returns the pager's status, not the
command's) and zsh reserves `status` as a read-only variable, so
`for c in ...; do out=$(...); status=$?; done` dies with "zsh: read-only variable:
status" before printing a single line.

Reads only unless --like is passed. --like exercises the write path and then
RE-READS the tweet to assert the server recorded it: a mutation that prints
"Liked tweet ..." only proves the call left the client.
"""

import argparse
import asyncio
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

TIMEOUT = 150
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def run(args):
    """Run one x-cli script; return (status, first meaningful output line)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / args[0]), *args[1:]],
            cwd=SKILL_DIR, capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return FAIL, f"timed out after {TIMEOUT}s"
    output = (proc.stdout + proc.stderr).strip()
    first = next((line for line in output.splitlines() if line.strip()), "(no output)")
    if proc.returncode != 0:
        # surface the real error, not just the traceback header
        error = next(
            (line for line in reversed(output.splitlines())
             if line.strip() and not line.startswith((" ", "Traceback"))),
            first,
        )
        return FAIL, error[:96]
    return PASS, first[:80]


def own_handle():
    """The signed-in handle, so the sweep needs no hardcoded account."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "x_auth.py"), "whoami"],
        cwd=SKILL_DIR, capture_output=True, text=True, timeout=TIMEOUT,
    )
    match = re.search(r"@(\w+)", proc.stdout)
    if not match:
        sys.exit(
            "could not read the signed-in handle from `x_auth.py whoami`:\n"
            + (proc.stdout + proc.stderr).strip()
            + "\nPass --handle <handle> instead."
        )
    return match.group(1)


def check_like(tweet_id):
    """Like a tweet, then read it back and assert the server recorded the like."""
    from x_utils import get_client

    async def main():
        client = await get_client()
        before = await client.get_tweet_by_id(tweet_id)
        if getattr(before, "favorited", False):
            return SKIP, "already liked - unlike it first, or pick another tweet"
        status, line = run(["x_interact.py", "like", tweet_id])
        if status != PASS:
            return FAIL, f"like call failed: {line}"
        after = await client.get_tweet_by_id(tweet_id)
        if getattr(after, "favorited", False):
            return PASS, f"liked and confirmed server-side (favorite_count {after.favorite_count})"
        return FAIL, (
            "like reported success but `favorited` is still false "
            f"(favorite_count {after.favorite_count})"
        )

    return asyncio.run(main())


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--handle", help="handle for account reads (default: signed-in account)")
    parser.add_argument("--tweet", help="tweet id with a thread and replies")
    parser.add_argument(
        "--like", dest="like_tweet",
        help="tweet id to like as a write test (mutates the account)",
    )
    args = parser.parse_args()

    handle = args.handle or own_handle()
    print(f"x-cli smoke test (handle @{handle}, writes {'ON' if args.like_tweet else 'off'})\n")

    checks = [
        ("auth check", ["x_auth.py", "check"]),
        ("auth whoami", ["x_auth.py", "whoami"]),
        ("user timeline", ["x_read.py", "user", handle, "--count", "2"]),
        ("home timeline", ["x_read.py", "timeline", "--count", "2"]),
        ("for you", ["x_read.py", "foryou", "--count", "2"]),
        ("mentions", ["x_read.py", "mentions", "--count", "2"]),
        ("highlights", ["x_read.py", "highlights", handle, "--count", "2"]),
        ("search users", ["x_read.py", "search-user", handle, "--count", "2"]),
        ("search tweets", ["x_search.py", f"from:{handle}", "--count", "2"]),
        ("user info", ["x_extra.py", "user-info", handle]),
        ("followers", ["x_extra.py", "followers", handle, "--count", "2"]),
        ("following", ["x_extra.py", "following", handle, "--count", "2"]),
        ("trends", ["x_extra.py", "trends"]),
        ("bookmarks", ["x_extra.py", "bookmarks", "--count", "2"]),
        ("notifications", ["x_extra.py", "notifications", "--count", "2"]),
        ("dm inbox", ["x_dm.py", "inbox", "--count", "2"]),
        ("post dry-run", ["x_post.py", "tweet", "smoke test", "--dry-run"]),
    ]
    if args.tweet:
        checks += [
            ("tweet", ["x_read.py", "tweet", args.tweet]),
            ("thread", ["x_read.py", "thread", args.tweet]),
            ("replies", ["x_read.py", "replies", args.tweet, "--count", "2"]),
        ]

    results = []
    for label, command in checks:
        status, detail = run(command)
        results.append((label, status, detail))
        print(f"{label:<16} {status:<5} {detail}")

    if args.like_tweet:
        status, detail = check_like(args.like_tweet)
        results.append(("like (write)", status, detail))
        print(f"{'like (write)':<16} {status:<5} {detail}")

    failed = [label for label, status, _ in results if status == FAIL]
    skipped = [label for label, status, _ in results if status == SKIP]
    passed = len(results) - len(failed) - len(skipped)

    print(f"\n{passed} passed, {len(failed)} failed" + (f", {len(skipped)} skipped" if skipped else ""))
    if failed:
        print("failed: " + ", ".join(failed))
        print("A failure here is an expired session, a retired operation, or a shim regression: "
              "see 'When a command fails anyway' in SKILL.md and references/twikit-drift-repair.md.")
        sys.exit(1)


if __name__ == "__main__":
    main()
