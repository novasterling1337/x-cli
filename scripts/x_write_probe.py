#!/usr/bin/env python3
"""Probe whether X's write gate accepts a mutation, without publishing anything.

Sends the real `CreateTweet` mutation with an impossible `reply_to` (tweet id 1),
so X must reject the reply target and no tweet can land whatever the gate says.
What comes back names the layer that refused:

    385  the gate is OPEN — only the bogus reply was refused. A real failure was
         about the target or the text.
    226  account/session anti-automation gate is armed on this write path (quotes
         get it while plain writes can still reach 385). A scheduled post will
         fail again if it retries now.
    344  write quota exhausted (daily cap, or a rolling limiter tripped by
         repeated attempts in the last few minutes). Wait, do not retry.

Run ONCE per diagnosis. Every probe is a write attempt and feeds the same gate:
repeating it escalates the refusal it is measuring.

Usage:
    .venv/bin/python scripts/x_write_probe.py
    .venv/bin/python scripts/x_write_probe.py --quote <tweet-url-or-id>
    .venv/bin/python scripts/x_write_probe.py --quiet     # exit code only

Exit: 0 gate open, 3 code 226, 4 code 344, 5 other refusal, 1 error/no answer.
"""
import argparse
import asyncio
import json
import re
import sys

from x_utils import get_client

BOGUS_REPLY = "1"  # cannot exist; keeps the probe from ever publishing

VERDICTS = {
    385: (0, "gate OPEN — only the bogus reply was refused"),
    226: (3, "anti-automation gate armed — do not retry now"),
    344: (4, "write quota exhausted — wait, do not retry"),
}


def tweet_id(value: str) -> str:
    match = re.search(r"/status/(\d+)", value or "")
    return match.group(1) if match else (value or "")


async def probe(quote: str | None) -> tuple[int, dict]:
    client = await get_client()
    attachment = (f"https://x.com/i/status/{tweet_id(quote)}" if quote else None)
    resp, _ = await client.gql.create_tweet(
        False, "probe", [], None, BOGUS_REPLY, attachment,
        None, False, None, None, None,
    )
    return 0, resp or {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quote", help="also send attachment_url for this tweet")
    ap.add_argument("--quiet", action="store_true", help="print nothing but the code")
    args = ap.parse_args()

    try:
        _, resp = asyncio.run(probe(args.quote))
    except Exception as exc:                       # network, auth, twikit parse
        print(f"probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    errors = resp.get("errors") or []
    if not errors:
        # No error object at all: the write path answered without refusing the
        # bogus reply, which should be impossible. Report it rather than guess.
        print("no errors returned — unexpected response:\n" + json.dumps(resp)[:800],
              file=sys.stderr)
        return 1

    code = errors[0].get("code")
    message = str(errors[0].get("message") or "")[:120]
    exit_code, verdict = VERDICTS.get(code, (5, "other refusal — read the message"))
    print(f"code {code}: {verdict}")
    if not args.quiet:
        print(f"message: {message}")
        if exit_code == 0:
            print("a real write should be attempted now; a probe cannot publish.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
