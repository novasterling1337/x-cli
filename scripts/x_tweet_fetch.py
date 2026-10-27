"""Resilient single-tweet fetch for x_read.

Why this module exists: twikit parses every TweetDetail entry through
`twikit.tweet.tweet_from_data`, which indexes `tweet_data['core']['user_results']`
unconditionally. X varies the payload shape between otherwise identical
requests — the author block is sometimes withheld, the tweet sometimes nests
under `TweetWithVisibilityResults`, and `core` sometimes arrives without a
`user_results` key at all. When that happens `tweet_from_data` raises KeyError
inside `get_tweet_by_id` and the whole command dies, even though the tweet text
and counts are sitting right there in the response.

Two layers of defence, in order:

1. RETRY. The shape varies run to run, so a repeat request often parses.
2. RAW PARSE. Fetch TweetDetail through the same authenticated client and build
   the output dict ourselves, tolerating a missing author block.

The raw parser emits exactly the dict schema `x_utils.tweet_to_data` produces,
so callers render it with the same formatter (no field parity loss).
"""

import asyncio

_TWEET_TYPENAMES = ("Tweet", "TweetWithVisibilityResults")


def _walk_tweet_results(obj, out=None):
    """Collect every tweet result dict anywhere in the payload."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        if obj.get("__typename") in _TWEET_TYPENAMES and (
            "legacy" in obj or "tweet" in obj
        ):
            out.append(obj)
        for value in obj.values():
            _walk_tweet_results(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _walk_tweet_results(value, out)
    return out


def _find_user(obj, rest_id):
    """Return the user result dict with this rest_id, wherever it sits."""
    if isinstance(obj, dict):
        if obj.get("rest_id") == rest_id and "core" in obj:
            return obj
        for value in obj.values():
            found = _find_user(value, rest_id)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_user(value, rest_id)
            if found:
                return found
    return None


def _best_video(match):
    """Highest-bitrate mp4 from a video_info block, as twikit's formatter does."""
    variants = (match.get("video_info") or {}).get("variants", [])
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
    if not mp4s:
        return None
    return max(mp4s, key=lambda v: v.get("bitrate", 0)).get("url")


def tweet_from_payload(payload, tweet_id):
    """Build the standard tweet dict from a raw TweetDetail payload.

    Returns None when the tweet is genuinely absent (deleted, withheld, or an
    error-only response) so callers can report a real failure instead of
    printing an empty shell.
    """
    tweet_id = str(tweet_id)
    root = None
    for candidate in _walk_tweet_results(payload):
        inner = candidate.get("tweet", candidate)
        if str(inner.get("rest_id") or candidate.get("rest_id")) == tweet_id:
            root = candidate
            break
    if root is None:
        return None

    inner = root.get("tweet", root)
    legacy = inner.get("legacy") or {}

    # Long posts ship the full body under note_tweet; legacy.full_text is the
    # truncated 280-char version with a t.co tail.
    text = legacy.get("full_text") or ""
    note = (
        (inner.get("note_tweet") or {}).get("note_tweet_results", {}).get("result", {})
    )
    if note.get("text"):
        text = note["text"]

    # Author: normally core.user_results.result, but that is exactly the block
    # that goes missing. Fall back to the user's own rest_id, then to the
    # owner id on legacy — never invent a handle.
    screen_name = name = None
    user_result = (inner.get("core") or {}).get("user_results", {}).get("result") or {}
    user_core = user_result.get("core") or {}
    screen_name = user_core.get("screen_name")
    name = user_core.get("name")
    if not screen_name:
        owner_id = legacy.get("user_id_str") or user_result.get("rest_id")
        owner = _find_user(payload, owner_id) if owner_id else None
        if owner:
            owner_core = owner.get("core") or {}
            screen_name = owner_core.get("screen_name")
            name = owner_core.get("name")

    media = []
    for match in (legacy.get("extended_entities") or {}).get("media", []):
        kind = match.get("type") or "photo"
        media.append(
            {
                "url": match.get("media_url_https") or match.get("url"),
                "type": kind,
                "alt_text": match.get("ext_alt_text"),
            }
        )
        if kind in ("video", "animated_gif"):
            video_url = _best_video(match)
            if video_url:
                media.append({"url": video_url, "type": "video", "alt_text": None})

    views = inner.get("views") or {}
    view_count = views.get("count")
    if isinstance(view_count, str) and view_count.isdigit():
        view_count = int(view_count)

    return {
        "id": str(inner.get("rest_id") or tweet_id),
        "user": screen_name or "unknown",
        "name": name or "unknown",
        "text": text,
        "created_at": legacy.get("created_at"),
        "url": f"https://x.com/{screen_name}/status/{tweet_id}" if screen_name else None,
        "retweet_count": legacy.get("retweet_count", 0),
        "favorite_count": legacy.get("favorite_count", 0),
        "reply_count": legacy.get("reply_count"),
        "quote_count": legacy.get("quote_count"),
        "bookmark_count": legacy.get("bookmark_count"),
        "view_count": view_count,
        "media": media or None,
        "reply_to": legacy.get("in_reply_to_status_id_str"),
    }


async def get_tweet_resilient(client, tweet_id, attempts=3):
    """twikit `get_tweet_by_id` with retries; None if every attempt fails."""
    for attempt in range(attempts):
        try:
            return await client.get_tweet_by_id(str(tweet_id))
        except Exception:
            if attempt < attempts - 1:
                await asyncio.sleep(1 + attempt)
    return None


async def fetch_raw_payload(client, tweet_id):
    response, _ = await client.gql.tweet_detail(str(tweet_id))
    return response


async def fetch_tweet_data(client, tweet_id, attempts=3):
    """Dict for one tweet: twikit first, raw TweetDetail parse as fallback.

    Raises RuntimeError when both paths fail, so the CLI exits loudly rather
    than printing a plausible-looking empty tweet.
    """
    from x_utils import tweet_to_data

    tweet = await get_tweet_resilient(client, tweet_id, attempts=attempts)
    if tweet is not None:
        return tweet_to_data(tweet)

    try:
        payload = await fetch_raw_payload(client, tweet_id)
    except Exception as e:
        raise RuntimeError(f"tweet {tweet_id} unreadable: {type(e).__name__}: {e}")
    data = tweet_from_payload(payload, tweet_id)
    if data is None:
        raise RuntimeError(
            f"tweet {tweet_id} absent from payload (deleted, withheld, or "
            f"error response)"
        )
    return data
