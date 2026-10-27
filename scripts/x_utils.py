"""
x-cli shared utilities — config loading, client init, output formatting.
"""

import asyncio
import json
import sys
from pathlib import Path
from twikit import Client

# Must run before any Client is constructed: works around twikit's broken
# X-Client-Transaction-Id derivation against the current x.com frontend.
from x_compat import apply_patches, refresh_query_ids

apply_patches()

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_PATH = SKILL_DIR / "config.json"


def load_config() -> dict:
    """Config is OPTIONAL: every key has a default, so cookies.json alone is a
    complete install. Missing config.json must not kill every command."""
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH) as f:
        return json.load(f)


async def get_client(config: dict = None) -> Client:
    if config is None:
        config = load_config()

    cookies_path = SKILL_DIR / config.get("cookies_file", "cookies.json")

    # twikit's hardcoded GraphQL query ids go stale and 404; refresh them from
    # X's live bundle (cached 24h, needs the session cookies, non-fatal).
    if cookies_path.exists():
        try:
            with open(cookies_path) as f:
                cookies = json.load(f)
            refresh_query_ids(cookies=cookies if isinstance(cookies, dict) else None)
        except (ValueError, OSError):
            pass
        except Exception:
            pass

    proxy = config.get("proxy")
    lang = config.get("language", "en-US")
    client = Client(lang, proxy=proxy) if proxy else Client(lang)

    if cookies_path.exists():
        client.load_cookies(str(cookies_path))
    elif config.get("x_username") and config.get("x_password"):
        await client.login(
            auth_info_1=config["x_username"],
            auth_info_2=config.get("x_email", config["x_username"]),
            password=config["x_password"],
            cookies_file=str(cookies_path)
        )
    else:
        print("❌ No cookies.json and no login credentials in config.json", file=sys.stderr)
        sys.exit(1)

    return client


def _as_int(value):
    """int when the value is an integer or an all-digit string, else unchanged."""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def tweet_to_data(tweet) -> dict:
    """Normalise a twikit Tweet into the dict every formatter/backend shares."""

    # Extract media URLs
    media_urls = []
    if hasattr(tweet, "media") and tweet.media:
        for m in tweet.media:
            url = getattr(m, "media_url_https", None) or getattr(m, "url", None)
            if url:
                media_urls.append({
                    "url": url,
                    "type": getattr(m, "type", "photo"),
                    "alt_text": getattr(m, "ext_alt_text", None),
                })
            # Video: get highest quality variant
            if hasattr(m, "video_info") and m.video_info:
                variants = m.video_info.get("variants", [])
                mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
                if mp4s:
                    best = max(mp4s, key=lambda v: v.get("bitrate", 0))
                    media_urls.append({"url": best["url"], "type": "video", "alt_text": None})

    # Extract reply context. twikit exposes the parent id as `in_reply_to`
    # (a string); there is no `in_reply_to_tweet_id` attribute on its Tweet, so
    # the old getattr always returned None and EVERY reply looked like an
    # original post to machine readers. `reply_to` on the object is a lazily
    # cached list of parent Tweet objects, not an id, so it cannot be used here.
    reply_to = getattr(tweet, "in_reply_to", None)
    if reply_to is not None:
        reply_to = str(reply_to)

    data = {
        "id": tweet.id,
        "user": tweet.user.screen_name if tweet.user else "unknown",
        "name": tweet.user.name if tweet.user else "unknown",
        "text": tweet.text,
        "created_at": str(tweet.created_at) if hasattr(tweet, "created_at") else None,
        "url": f"https://x.com/{tweet.user.screen_name}/status/{tweet.id}" if tweet.user else None,
        "retweet_count": getattr(tweet, "retweet_count", 0),
        "favorite_count": getattr(tweet, "favorite_count", 0),
        # Present on the Tweet object but never emitted before, which is why
        # machine readers saw replies/views as unavailable. `view_count` is
        # sometimes absent (older tweets, some payloads): emit None, not 0.
        "reply_count": getattr(tweet, "reply_count", None),
        "quote_count": getattr(tweet, "quote_count", None),
        "bookmark_count": getattr(tweet, "bookmark_count", None),
        # twikit hands back view_count as a numeric STRING while count fields
        # are ints; normalise so JSON consumers see one type on both the twikit
        # and raw-payload paths.
        "view_count": _as_int(getattr(tweet, "view_count", None)),
        "media": media_urls if media_urls else None,
        "reply_to": reply_to,
    }
    return data


def format_tweet(tweet, json_mode=False) -> str:
    return format_tweet_data(tweet_to_data(tweet), json_mode)


def format_tweet_data(data: dict, json_mode=False) -> str:
    """Render a normalised tweet dict (twikit Tweet or raw payload parse)."""
    if json_mode:
        return json.dumps(data, ensure_ascii=False)

    text = data.get("text") or ""
    lines = [
        f"@{data.get('user', 'unknown')} ({data.get('name', 'unknown')})",
        f"{text}",
        f"❤️ {data.get('favorite_count', 0)}  🔁 {data.get('retweet_count', 0)}  🔗 {data.get('url')}",
    ]
    if data.get("created_at"):
        lines.insert(0, f"📅 {data['created_at']}")
    reply_to = data.get("reply_to")
    if reply_to:
        lines.append(f"↩️ Reply to: https://x.com/i/status/{reply_to}")
    media_urls = data.get("media") or []
    if media_urls:
        for m in media_urls:
            emoji = "🖼️" if m["type"] == "photo" else "🎥" if m["type"] == "video" else "📎"
            alt = f' — "{m["alt_text"]}"' if m["alt_text"] else ""
            lines.append(f"{emoji} {m['url']}{alt}")
    return "\n".join(lines)


def run(coro):
    """Run async function."""
    asyncio.run(coro)


def normalize_argv(argv=None, global_flags=("--json",)):
    """Move top-level flags in front of the subcommand.

    argparse binds `--json` (and x_post's `--dry-run`) to the top-level parser, so
    the documented `x_post.py tweet "hi" --dry-run` and the natural
    `x_read.py user mariodian --count 3 --json` both fail with "unrecognized
    arguments". Reordering the flags fixes both positions.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    flags = [a for a in argv if a in global_flags]
    return flags + [a for a in argv if a not in global_flags]
