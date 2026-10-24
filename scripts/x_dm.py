#!/usr/bin/env python3
"""
x-cli dm — Send and read Direct Messages.

Usage:
  python x_dm.py send <username> "message text"
  python x_dm.py inbox [--count N]
"""

import argparse
import json
from datetime import datetime, timezone

from x_compat import get_dm_inbox
from x_utils import get_client, run, normalize_argv


async def cmd_send(args):
    client = await get_client()
    user = await client.get_user_by_screen_name(args.username.lstrip("@"))
    await client.send_dm(user.id, args.text)
    print(f"✅ DM sent to @{user.screen_name}: {args.text[:50]}...")


async def cmd_inbox(args):
    client = await get_client()
    conversations = await get_dm_inbox(client, args.count)
    if not conversations:
        print("No conversations found.")
        return
    if args.json:
        print(json.dumps(conversations, ensure_ascii=False))
        return
    for conv in conversations:
        participants = ", ".join(f"@{p}" for p in conv["participants"] if p)
        when = ""
        if conv.get("timestamp"):
            when = datetime.fromtimestamp(
                conv["timestamp"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
        muted = " (muted)" if conv.get("muted") else ""
        print(f"💬 {participants}{muted} {when}")
        if conv.get("text"):
            print(f"   @{conv['sender']}: {conv['text']}")
        print("─" * 40)


def main():
    parser = argparse.ArgumentParser(description="x-cli dm — Direct Messages")
    parser.add_argument("--json", action="store_true", help="JSON output")

    sub = parser.add_subparsers(dest="command", required=True)

    p_send = sub.add_parser("send", help="Send a DM")
    p_send.add_argument("username", help="Recipient username")
    p_send.add_argument("text", help="Message text")

    p_inbox = sub.add_parser("inbox", help="Read DM inbox")
    p_inbox.add_argument("--count", type=int, default=10)

    args = parser.parse_args(normalize_argv())

    if args.command == "send":
        run(cmd_send(args))
    elif args.command == "inbox":
        run(cmd_inbox(args))


if __name__ == "__main__":
    main()
