#!/usr/bin/env python3
"""
x-cli post — Post tweets, replies, and quotes on X/Twitter.

Usage:
  python x_post.py tweet "Hello world!"
  python x_post.py reply <tweet-id-or-url> "Nice analysis!"
  python x_post.py quote <tweet-id-or-url> "Adding context..."

Options:
  --json    Output posted tweet as JSON
  --dry-run Preview without posting
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

from x_utils import get_client, run, normalize_argv
from x_tweet_fetch import fetch_tweet_data

# Exit 3 = the write was refused or could not be confirmed. Distinct from a
# usage error (2) so callers never retry a refusal as if it were transient.
EXIT_UNCONFIRMED = 3

# --- twifork write backend -------------------------------------------------
# twikit 2.3.3 cannot build an X-Client-Transaction-Id at all (stale ondemand.s
# parser) and X enforces that header on writes only, so reads can look healthy
# while every mutation is refused. twifork 2.4.0 fixes the handshake, but it
# installs a module ALSO named `twikit` and would collide with the pinned 2.3.3
# the read path depends on. Hence a second interpreter: `.venv-write`.
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
WRITE_PYTHON = SKILL_DIR / ".venv-write" / "bin" / "python"
WRITE_BACKEND = SCRIPT_DIR / "x_write_twifork.py"


def delegate_write(argv: list[str]) -> None:
    """Hand a write to the twifork backend when it is installed.

    Falls through to the twikit 2.3.3 path when `.venv-write` is absent, so a
    host that never ran the extra setup step keeps working exactly as before.
    """
    if not (WRITE_PYTHON.exists() and WRITE_BACKEND.exists()):
        return
    proc = subprocess.run([str(WRITE_PYTHON), str(WRITE_BACKEND), *argv])
    raise SystemExit(proc.returncode)


def extract_tweet_id(url_or_id: str) -> str:
    match = re.search(r"/status/(\d+)", url_or_id)
    return match.group(1) if match else url_or_id


def _refuse(reason: str, code=None, ambiguous: bool = False) -> "NoReturn":
    """Report a write that X refused or answered without a tweet, then exit.

    `create_tweet` answers a rate-limited or silently-dropped write with
    `{"data": {"create_tweet": {"tweet_results": {}}}}` and NO `errors`, so
    twikit parses `{}` into None. Indexing `result.id` then raised
    AttributeError, which reads as a client bug instead of "X refused the post".
    """
    payload = {"error": reason}
    if code is not None:
        payload["code"] = code
    if ambiguous:
        payload["ambiguous"] = True
    print(json.dumps(payload), file=sys.stderr)
    raise SystemExit(EXIT_UNCONFIRMED)


async def _create(client, **kwargs):
    """create_tweet, with refusals turned into a legible error instead of a crash.

    A None result is AMBIGUOUS, not a failure: X answered 200 with an empty
    tweet_results. Never retry it blindly — read the account back first, the
    tweet may exist.
    """
    from twikit.errors import CouldNotTweet

    try:
        result = await client.create_tweet(**kwargs)
    except CouldNotTweet as exc:
        message = str(exc)
        code = 344 if "(344)" in message else None
        _refuse(f"X refused the write: {message}", code=code)
    if result is None:
        _refuse("X returned an empty tweet_results — the write is UNCONFIRMED, "
                "not necessarily failed. Read the account back before retrying; "
                "a blind retry can duplicate the post.", ambiguous=True)
    return result


async def cmd_tweet(args):
    client = await get_client()

    media_ids = args.media if hasattr(args, 'media') and args.media else None

    if args.dry_run:
        print(f"🔍 DRY RUN — would post:\n\n{args.text}\n\n({len(args.text)} chars)")
        if media_ids:
            print(f"📎 Media: {', '.join(media_ids)}")
        return

    result = await _create(client, text=args.text, media_ids=media_ids)
    print(f"✅ Tweet posted: https://x.com/i/status/{result.id}" if not args.json
          else json.dumps({"id": result.id, "url": f"https://x.com/i/status/{result.id}"}))


async def cmd_reply(args):
    client = await get_client()
    tweet_id = extract_tweet_id(args.target)

    if args.dry_run:
        print(f"🔍 DRY RUN — would reply to {tweet_id}:\n\n{args.text}")
        return

    result = await _create(client, text=args.text, reply_to=tweet_id)
    print(f"✅ Reply posted: https://x.com/i/status/{result.id}" if not args.json
          else json.dumps({"id": result.id, "reply_to": tweet_id}))


async def cmd_quote(args):
    client = await get_client()
    tweet_id = extract_tweet_id(args.target)
    # Same payload-variance bug as x_read: a bare get_tweet_by_id raises
    # KeyError on some reads. All this needs is the author handle for the URL.
    try:
        data = await fetch_tweet_data(client, tweet_id)
    except RuntimeError as e:
        print(f"❌ cannot resolve quoted tweet: {e}", file=sys.stderr)
        raise SystemExit(2)
    author = data.get("user")
    quote_url = (
        f"https://x.com/{author}/status/{tweet_id}"
        if author and author != "unknown"
        else f"https://x.com/i/status/{tweet_id}"
    )

    if args.dry_run:
        print(f"🔍 DRY RUN — would quote {quote_url}:\n\n{args.text}")
        return

    result = await _create(client, text=args.text, attachment_url=quote_url)
    print(f"✅ Quote posted: https://x.com/i/status/{result.id}" if not args.json
          else json.dumps({"id": result.id, "quoted": tweet_id}))


def main():
    parser = argparse.ArgumentParser(description="x-cli post — Post to X/Twitter")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")

    sub = parser.add_subparsers(dest="command", required=True)

    p_tweet = sub.add_parser("tweet", help="Post a new tweet")
    p_tweet.add_argument("text", help="Tweet text")
    p_tweet.add_argument("--media", nargs="+", help="Media IDs (from x_extra.py upload)")

    p_reply = sub.add_parser("reply", help="Reply to a tweet")
    p_reply.add_argument("target", help="Tweet URL or ID to reply to")
    p_reply.add_argument("text", help="Reply text")

    p_quote = sub.add_parser("quote", help="Quote a tweet")
    p_quote.add_argument("target", help="Tweet URL or ID to quote")
    p_quote.add_argument("text", help="Quote text")

    args = parser.parse_args(normalize_argv(global_flags=("--json", "--dry-run")))

    # Writes go through twifork when the second interpreter exists; the read
    # path and this module stay on the pinned twikit 2.3.3.
    delegate_write(normalize_argv(global_flags=("--json", "--dry-run")))

    if args.command == "tweet":
        run(cmd_tweet(args))
    elif args.command == "reply":
        run(cmd_reply(args))
    elif args.command == "quote":
        run(cmd_quote(args))


if __name__ == "__main__":
    main()
