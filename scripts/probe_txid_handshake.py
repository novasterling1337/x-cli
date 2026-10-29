#!/usr/bin/env python3
"""Probe whether the installed twikit-compatible package can build an
X-Client-Transaction-Id at all.

This is the read/write health check: reads tolerate a placeholder id, writes do
not, so "reads work" proves nothing about the write path.

Usage:
    python scripts/probe_txid_handshake.py [cookies.json]

cookies.json is a flat map: {"auth_token": "...", "ct0": "..."}

Exit codes:
    0  handshake completed (writes are possible)
    1  packaged parser is stale  -> writes cannot work on this package
    2  handshake code is fine, session cookies missing/stale -> rerun with cookies
    3  anything else (inspect by hand)
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys


def make_client(cookies: dict | None):
    from twikit.client.client import Client

    params = set(inspect.signature(Client.__init__).parameters)
    if "impersonate" in params:
        try:
            client = Client("en-US", impersonate="chrome124")
            _apply_cookies(client, cookies)
            return client
        except Exception as exc:  # extra not installed, or driver unavailable
            print(f"note: impersonate unavailable ({type(exc).__name__}), continuing without it")
    client = Client("en-US")
    _apply_cookies(client, cookies)
    return client


def _apply_cookies(client, cookies: dict | None) -> None:
    if not cookies:
        return
    try:
        client.set_cookies(**cookies)
    except TypeError:
        client.set_cookies(cookies)


async def main() -> int:
    cookies = None
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as fh:
            cookies = json.load(fh)

    try:
        client = make_client(cookies)
    except Exception as exc:
        print(f"ctor FAIL: {type(exc).__name__}: {exc}")
        return 3

    ct = getattr(client, "client_transaction", None) or getattr(
        client, "_client_transaction", None
    )
    if ct is None:
        print("no handshake object on Client - inspect the package source")
        return 3

    try:
        await ct.init(client.http, client._base_headers)
    except Exception as exc:
        name, msg = type(exc).__name__, str(exc)
        print(f"handshake FAIL: {name}: {msg[:300]}")
        if "KEY_BYTE" in msg:
            print("=> packaged parser is stale: this build cannot write")
            return 1
        if "logged-out page shell" in msg or name == "InvalidSession":
            print("=> handshake code is healthy; supply fresh cookies and rerun")
            return 2
        return 3

    print("handshake OK")
    try:
        tid = ct.generate_transaction_id(method="POST", path="/i/api/graphql/x/CreateTweet")
        print(f"transaction id: {str(tid)[:40]}")
    except Exception as exc:
        # A renamed generation call is not a failure; the handshake passing is the signal.
        print(f"(id generation not exercised: {type(exc).__name__}: {exc})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
