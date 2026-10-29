#!/usr/bin/env python3
"""
x-cli write backend — twifork + browser TLS impersonation.

Runs under the SEPARATE `.venv-write` interpreter, not the skill's `.venv`.
Reason: twifork installs a module ALSO named `twikit`, so installing it beside
twikit 2.3.3 collides on the same package directory and breaks the read path
(scripts/x_compat.py patches 2.3.3's parsers specifically). Two interpreters,
one shared cookies.json.

Why this exists at all: twikit 2.3.3 cannot build an X-Client-Transaction-Id
(the packaged ondemand.s parser is stale) and X enforces that header on writes
only — which is exactly the "reads work, posting never does" signature.

Usage:
  x_write_twifork.py tweet "text" [--media ID...]
  x_write_twifork.py reply <tweet-id-or-url> "text"
  x_write_twifork.py quote <tweet-id-or-url> "text"
  x_write_twifork.py delete <tweet-id-or-url>
  x_write_twifork.py whoami

Global: --json, --dry-run

Exit: 0 ok | 2 usage | 3 refused/unconfirmed | 4 auth/backend unavailable
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
COOKIES_PATH = SKILL_DIR / "cookies.json"

EXIT_REFUSED = 3
EXIT_BACKEND = 4

# The handshake's HTML fetch must NOT carry the GraphQL bearer: with live login
# cookies, x.com answers 401 with a 0-byte body and twifork then blames the
# cookies ("InvalidSession"). Strip it and the page returns 200 with the
# webpack manifest. Verified 2026-10-29 against twifork 2.4.0.
STRIP_FOR_HTML = {"authorization", "content-type"}


def patch_handshake_headers() -> None:
    from twikit.x_client_transaction import transaction as T

    original = T.ClientTransaction.init
    if getattr(original, "_xcli_patched", False):
        return

    async def init(self, session, headers):
        clean = {k: v for k, v in (headers or {}).items()
                 if k.lower() not in STRIP_FOR_HTML}
        return await original(self, session, clean)

    init._xcli_patched = True
    T.ClientTransaction.init = init


def extract_tweet_id(value: str) -> str:
    m = re.search(r"/status/(\d+)", value or "")
    return m.group(1) if m else (value or "")


async def build_client():
    """Impersonated client with cookies, handshake primed. Returns Client."""
    from twikit.client.client import Client

    patch_handshake_headers()
    if not COOKIES_PATH.exists():
        print(json.dumps({"error": f"no cookies at {COOKIES_PATH}"}), file=sys.stderr)
        raise SystemExit(EXIT_BACKEND)
    cookies = json.loads(COOKIES_PATH.read_text())
    if not isinstance(cookies, dict):
        print(json.dumps({"error": "cookies.json is not a flat name/value map"}),
              file=sys.stderr)
        raise SystemExit(EXIT_BACKEND)

    try:
        client = Client("en-US", impersonate="chrome124")
    except Exception as exc:
        print(f"note: impersonate unavailable ({type(exc).__name__}: {exc}); "
              f"continuing without browser TLS", file=sys.stderr)
        client = Client("en-US")

    client.set_cookies(cookies)          # positional: kwargs raise TypeError on 2.4.0
    await client.client_transaction.init(client.http, client._base_headers)
    return client


def _code_from(message: str) -> int | None:
    """X's numeric refusal code, out of twikit's exception text.

    twikit renders the code as a trailing parenthetical — "...(226)" — but the
    wording around it varies, so take the LAST 2-3 digit parenthetical rather
    than anchoring to the end of the string. The miles poster parks a job on
    this number; a None here means the retry ladder cannot tell 226 from 344.
    """
    found = re.findall(r"\((\d{2,3})\)", message or "")
    if found:
        return int(found[-1])
    m = re.search(r"'code':\s*(\d+)", message or "")
    return int(m.group(1)) if m else None


async def cmd_write(args) -> int:
    client = await build_client()

    if args.command == "whoami":
        me = await client.user()
        print(json.dumps({"screen_name": me.screen_name, "id": me.id}))
        return 0

    if args.command == "delete":
        tid = extract_tweet_id(args.target)
        if args.dry_run:
            print(f"DRY RUN — would delete {tid}")
            return 0
        await client.delete_tweet(tid)
        print(json.dumps({"deleted": tid}))
        return 0

    kwargs: dict = {"text": args.text}
    if args.command == "reply":
        kwargs["reply_to"] = extract_tweet_id(args.target)
    elif args.command == "quote":
        tid = extract_tweet_id(args.target)
        author = None
        try:
            tw = await client.get_tweet_by_id(tid)
            author = getattr(getattr(tw, "user", None), "screen_name", None)
        except Exception:
            pass
        kwargs["attachment_url"] = (f"https://x.com/{author}/status/{tid}" if author
                                    else f"https://x.com/i/status/{tid}")
        if args.json:
            print(f"quote target: {kwargs['attachment_url']}", file=sys.stderr)
    if args.media:
        kwargs["media_ids"] = args.media

    if args.dry_run:
        print(f"DRY RUN ({args.command}) — would send via twifork:\n\n{args.text}\n\n"
              f"({len(args.text)} chars)")
        for k, v in kwargs.items():
            if k != "text":
                print(f"  {k}: {v}")
        return 0

    from twikit.errors import TwitterException

    try:
        result = await client.create_tweet(**kwargs)
    except TwitterException as exc:
        # The base class, not just CouldNotTweet: a rate-limit (429 -> 88/344) or
        # an auth refusal arrives as a sibling type, and the miles poster's
        # retry ladder needs the numeric code from any of them.
        msg = str(exc)
        code = _code_from(msg)
        print(json.dumps({"error": msg, "code": code, "backend": "twifork"}), file=sys.stderr)
        return EXIT_REFUSED

    if result is None:
        print(json.dumps({
            "error": "X returned an empty tweet_results — UNCONFIRMED, not necessarily "
                     "failed. Read the account back before retrying; a blind retry can "
                     "duplicate the post.",
            "ambiguous": True, "backend": "twifork"}), file=sys.stderr)
        return EXIT_REFUSED

    url = f"https://x.com/i/status/{result.id}"
    print(json.dumps({"id": result.id, "url": url, "backend": "twifork"}) if args.json
          else f"✅ {args.command} posted: {url}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("tweet"); t.add_argument("text")
    t.add_argument("--media", nargs="+")
    for name in ("reply", "quote"):
        s = sub.add_parser(name)
        s.add_argument("target")
        s.add_argument("text")
    d = sub.add_parser("delete"); d.add_argument("target")
    sub.add_parser("whoami")

    args = p.parse_args()
    if not hasattr(args, "media"):
        args.media = None
    try:
        return asyncio.run(cmd_write(args))
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}", "backend": "twifork"}),
              file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
