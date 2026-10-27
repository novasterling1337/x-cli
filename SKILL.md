---
name: x-cli
description: Full-featured X/Twitter toolkit — read, search, post, interact, DMs, lists, polls, trends. Cookie auth, proxy support, no API keys needed.
homepage: https://github.com/ignsoftwarellc/x-cli
metadata: {"clawdbot":{"emoji":"𝕏","requires":{"python":">=3.10","pip":["twikit"]}}}
---

# x-cli

Full-featured X/Twitter toolkit for OpenClaw agents. Powered by [twikit](https://github.com/d60/twikit) — no API keys required, cookie-based auth.

## When to Use

Use for anything that touches X/Twitter on behalf of this user's account: reading a specific tweet or thread, a user's latest tweets, home or For You timeline, mentions, replies, bookmarks, notifications, trends, followers, user search, keyword or operator search, plus the write side (post, reply, quote, like, retweet, bookmark, follow, DM). Also use it when a request names an `@handle` and wants its recent posting activity.

Not for authenticated X access you do not have: if `cookies.json` is missing, say so and ask the user (see Auth) instead of substituting a web search or a scrape.

## Setup

Get the skill onto the machine one of two ways:

- **From the repo (preferred: complete, and updatable with `git pull`):**
  ```bash
  git clone https://github.com/novasterling1337/x-cli ~/.hermes/skills/x-cli
  ```
- **Through the Hermes hub** (installs into `<HERMES_HOME>/skills/x-cli`) — pin a commit SHA, not `main`:
  ```bash
  hermes skills install https://raw.githubusercontent.com/novasterling1337/x-cli/<sha>/SKILL.md
  ```
  Two traps, both seen on a real install: only files under `references/ templates/ scripts/ assets/ examples/` that this SKILL.md names EXPLICITLY are copied, so `scripts/x_utils.py` arrives only because Setup names it and `config.example.json` / `README.md` / `LICENSE` never do; and a branch-tip URL (`/main/SKILL.md`) can serve a STALE cached SKILL.md for minutes after a push — the fetch gets `x-cache: HIT` while `curl` on the same URL gets the new bytes, which is how a 13-file install with no `x_utils.py` happens. Pin the SHA, then `ls scripts/x_utils.py` to confirm.

Then, from the skill directory:

```bash
cd ~/.hermes/skills/x-cli
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python scripts/x_auth.py check
```

`python3` must be >= 3.10 (twikit's floor; some macOS systems are older). The pinned
twikit 2.3.3 installs and runs on CPython 3.11 through 3.14 — verified on 3.11.15 and
3.14.4.

`config.json` is OPTIONAL — only a proxy or credential login needs it; `cookies.json`
alone is a complete install (a missing config.json used to abort every command, which
made the hub install path unusable). `config.example.json` in the repo is the template
when you do want one; it is NOT needed to run anything.

Install into the skill's own venv so the host interpreter stays untouched, then run EVERY script with that venv's python. A bare `python scripts/...` picks up the host `python3`, and every script imports twikit through `x_utils`, so it dies with `ModuleNotFoundError: No module named 'twikit'` before doing anything.

Every script needs its siblings on the import path, and CPython only adds the *script's*
own directory — so invoke them as `scripts/<name>.py` from the skill root (or any cwd),
never by copying a single script somewhere else.

Substitute `.venv/bin/python` for `python` in every command below (or `source .venv/bin/activate` once per shell).

### Auth

Credentials live in `cookies.json` beside SKILL.md (path configurable via `cookies_file`). Format is a flat name/value map, nothing else:

```json
{"auth_token": "...", "ct0": "..."}
```

twikit 2.x `set_cookies` passes the parsed JSON straight to `httpx.Cookies.update`, so the Cookie-Editor export shape (an array of `{name, value, domain, ...}` objects) is NOT accepted. `auth_token` and `ct0` are the two that matter.

- Prefer cookies over username/password: `config.json` stores a password in plaintext, and twikit's login flow trips X CAPTCHAs.
- Never hunt the user's local browser cookie stores on your own. Chrome/Arc cookies are Keychain-encrypted on macOS and reading them needs an interactive unlock. Ask the user to paste the two values. Extraction steps per browser are in `references/auth-setup.md`.
- `x_auth.py check` only reports whether `config.json` and the cookie file EXIST; its "check" is not a liveness probe. `x_auth.py whoami` does work (it now reads the user id through the GraphQL `Viewer` query), and so does `.venv/bin/python scripts/x_extra.py user-info <known-handle>` - either returning real data means the cookies are alive.
- Cookies are a live account session, so treat them as expiring: when a read fails, re-run that GraphQL probe before concluding anything about the script or the target account.

Full auth recipe, including what to do when a task arrives before any of this exists: `references/auth-setup.md`.

## Commands

### Read (`x_read.py`)
```bash
python scripts/x_read.py tweet <url-or-id>              # Read a tweet
python scripts/x_read.py user <username> --count 5       # User's tweets
python scripts/x_read.py timeline --count 20             # Home timeline (Following)
python scripts/x_read.py foryou --count 20               # For You timeline
python scripts/x_read.py thread <url-or-id>              # Read thread
python scripts/x_read.py replies <url-or-id> --count 20  # Replies to a tweet
python scripts/x_read.py mentions --count 10             # Your mentions
python scripts/x_read.py highlights <username>           # User's highlights
python scripts/x_read.py search-user "query" --count 10  # Search users
```

### Search (`x_search.py`)
```bash
python scripts/x_search.py "query" --count 10
python scripts/x_search.py "from:zerohedge gold" --count 5
```

### Post (`x_post.py`) — confirm with user first! Never post, reply, DM, or delete on your own initiative, and never infer consent from a read request.
```bash
python scripts/x_post.py tweet "text"                    # Post tweet
python scripts/x_post.py tweet "text" --media ID1 ID2    # With media
python scripts/x_post.py tweet "text" --dry-run           # Preview only
python scripts/x_post.py reply <id> "text"                # Reply
python scripts/x_post.py quote <id> "text"                # Quote tweet
```

A write is only done when the SERVER agrees. After any mutation (post, reply,
quote, like, retweet, bookmark, follow, DM), read the target back
(`x_read.py tweet <id> --json`, or the parsed tweet's `favorited` / `retweeted` /
`favorite_count`) and check the value changed. A mutation printing
`✅ Liked tweet ...` only proves the request left the client.

### Interact (`x_interact.py`)
```bash
python scripts/x_interact.py like <tweet>        # Like
python scripts/x_interact.py unlike <tweet>      # Unlike
python scripts/x_interact.py retweet <tweet>     # Retweet
python scripts/x_interact.py unretweet <tweet>   # Undo retweet
python scripts/x_interact.py bookmark <tweet>    # Bookmark
python scripts/x_interact.py unbookmark <tweet>  # Remove bookmark
python scripts/x_interact.py follow <username>   # Follow
python scripts/x_interact.py unfollow <username> # Unfollow
python scripts/x_interact.py delete <tweet>      # Delete tweet
python scripts/x_interact.py mute <username>     # Mute
python scripts/x_interact.py unmute <username>   # Unmute
python scripts/x_interact.py block <username>    # Block
python scripts/x_interact.py unblock <username>  # Unblock
```

### DMs (`x_dm.py`)
```bash
python scripts/x_dm.py send <username> "message"  # Send DM
python scripts/x_dm.py inbox --count 10            # Read inbox
```

### Extra (`x_extra.py`)
```bash
python scripts/x_extra.py trends                              # Trending
python scripts/x_extra.py trends --category news               # Category trends
python scripts/x_extra.py bookmarks --count 10                 # List bookmarks
python scripts/x_extra.py notifications --count 10             # Notifications
python scripts/x_extra.py user-info <username>                 # User profile
python scripts/x_extra.py followers <username> --count 20      # Followers
python scripts/x_extra.py following <username> --count 20      # Following
python scripts/x_extra.py upload <filepath>                    # Upload media
python scripts/x_extra.py schedule <timestamp> "text"          # Schedule tweet
python scripts/x_extra.py poll "A" "B" "C" --duration 1440    # Create poll
python scripts/x_extra.py list-create "name" --private         # Create list
python scripts/x_extra.py list-add <list-id> <username>        # Add to list
python scripts/x_extra.py list-remove <list-id> <username>     # Remove from list
python scripts/x_extra.py list-tweets <list-id> --count 20     # List tweets
```

### Auth (`x_auth.py`)
```bash
python scripts/x_auth.py check    # Check auth status
python scripts/x_auth.py whoami   # Current user
python scripts/x_auth.py login    # Login (uses config.json)
```

## Output
All commands: plain text by default, `--json` for structured JSON. Global flags
work before OR after the subcommand (`x_read.py user mariodian --json` and
`x_post.py tweet "hi" --dry-run` both parse), so quote the documented forms as-is.

### Media & Reply Context
- Tweets with images/videos include media URLs in output (`🖼️` / `🎥`)
- Replies include `↩️ Reply to:` link to the original tweet
- Agent can fetch media URLs with `web_fetch` and analyze with vision

## twikit compatibility shim

`scripts/x_compat.py` monkeypatches twikit at import time and is imported by
`x_utils.py` before any `Client` is constructed. It is REQUIRED on the current
x.com frontend: without it every command dies with
`Exception: Couldn't get KEY_BYTE indices`. Five things:

1. `X-Client-Transaction-Id` derivation. twikit looks for an `ondemand.s` webpack
   mapping in the x.com HTML; X no longer ships it. X accepts GraphQL requests
   with a placeholder id (including `FavoriteTweet`), so the derivation is skipped.
2. Live GraphQL query ids. twikit's hardcoded `queryId`s 404 (`code: 34`).
   `refresh_query_ids()` re-reads the pairs from X's client bundle, cached 24h in
   `.endpoint_ids.json`, and is called from `get_client()`. Refreshing is what
   made search, followers/following and tweets work again.
3. Payload normalizers. Refreshed ids return the newer model (`core`/`avatar`, no
   `legacy`), which `User.__init__`/`Tweet.__init__` reject. The shim synthesizes
   the legacy object and pads every indexed key, so old and new shapes both parse.
4. GET-to-POST fallback. `SearchTimeline` answers 404 to GET and 200 to POST; a
   `NotFound` on a GraphQL GET is retried as POST.
5. `Client.user_id` via the GraphQL `Viewer` query instead of the retired v1.1
   `account/settings.json` (this is what un-broke `whoami`).

## Command status (verified against the live account)

| Command | State |
| --- | --- |
| `x_auth.py check`, `whoami` | works |
| `x_read.py tweet/user/timeline/foryou/thread/replies/mentions/highlights/search-user` | works |
| `x_search.py` | works (via the POST fallback) |
| `x_extra.py user-info/followers/following/trends/bookmarks/notifications` | works |
| `x_dm.py inbox` | works (via v1.1 `dm/inbox_initial_state.json`) |
| `x_interact.py like` and other writes | `like` verified end to end: `favorite_count` 0 -> 1 and `favorited: true` on re-read. Other writes follow the same GraphQL mutation path but are unexercised, and posting/DMing/deleting still needs explicit user consent |

Three commands are implemented differently from what their names imply, because
twikit had no working path:

- `tweet`/`thread`/`replies` fetch through `scripts/x_tweet_fetch.py`, not
  `client.get_tweet_by_id` directly. twikit's `tweet_from_data` indexes
  `core.user_results` unconditionally, and X varies that shape between identical
  requests (author block withheld / nested visibility wrapper), so a bare call
  raises `KeyError: 'user_results'` on some reads of a tweet that read fine a
  minute earlier. `fetch_tweet_data()` retries, then parses the raw
  `TweetDetail` payload into the same dict schema (`x_utils.tweet_to_data`), so
  output and `--json` keys are identical on both paths.
- `replies`/`thread` drain the `Result` attached to the tweet (`tweet.replies`
  + `Result.next()`); twikit 2.3.3 has no `client.get_tweet_replies`.
- `mentions` searches `@me -from:me` instead of `get_notifications("Mentions")`,
  which X answers empty while mentions clearly exist.
- `trends` uses GraphQL `ExplorePage` (falling back to `ExploreSidebar`) instead
  of the retired v1.1 `guide.json`, whose 404 made twikit retry itself into a
  `RecursionError`. X no longer sends per-trend tweet counts, so trends show the
  name plus domain context (e.g. `Pentagon [Politics · Trending]`).

## Installing on another machine

The repo is the source of truth, so install from it instead of copying files around:

```bash
git clone https://github.com/novasterling1337/x-cli ~/.hermes/skills/x-cli
cd ~/.hermes/skills/x-cli
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
cp <your-cookies.json> .                          # auth_token + ct0, see Auth
.venv/bin/python scripts/x_auth.py whoami
.venv/bin/python scripts/smoke_test.py            # 17 read-only checks
```

Updating that host: `git -C ~/.hermes/skills/x-cli pull`. `cookies.json`, `config.json`,
`.venv/` and `.endpoint_ids.json` are all gitignored, so a pull never touches the session
or the local environment. `cookies.json` is a live account session, not a config file:
wherever it lands, treat it as a credential.

Pin twikit: the shim in `x_compat.py` targets 2.3.3's parsers, and
`scripts/requirements.txt` enforces it. Without Homebrew/pyenv, a uv-managed interpreter
works: on macOS that is usually
`~/.local/share/uv/python/cpython-3.1x-macos-aarch64-none/bin/python3.1x` (whatever the
system `python3` is, it must be >= 3.10).

Installed hosts: this Mac, and `nova@macmini` (uv CPython 3.11.15).

## When a command fails anyway

Everything above works today, so a failure now means one of these, in order:

1. Expired session. Cookies are a live login; a 401/403 on a command that used to
   work means re-auth, not a bug. Confirm with `x_extra.py user-info <handle>`.
2. A rotated operation. If a GraphQL call returns `404 {"errors":[{"code":34}]}`
   after a successful `refresh_query_ids()`, X retired that operation itself and
   the endpoint needs re-discovery from the live bundle (see the shim's data
   source: `/i/api/graphql/<id>/<Operation>` pairs in `main.*.js`).
3. v1.1 endpoints that X still serves can be user-agent sensitive: `dm/inbox_
   initial_state.json` answers 404 to twikit's user agent and 200 to a browser
   one, with identical cookies.

Do NOT reach for a real `X-Client-Transaction-Id`: X still accepts the
placeholder on the operations in use (including mutations), and the original
derivation algorithm is gone from the bundle, so it would be a
reverse-engineering project for no gain.

## Keeping it working

- `scripts/smoke_test.py` — runs the whole command surface and prints PASS/FAIL
  per command (`.venv/bin/python scripts/smoke_test.py --tweet <id>`, plus
  `--like <id>` to exercise and verify the write path). Run it after ANY change to
  `x_compat.py`, `x_utils.py`, or a script's argument handling: shared changes
  regress unrelated commands, so a fix is not done until the whole list is green.
- `references/twikit-drift-repair.md` — how to find the operation that replaced a
  retired one, probe it raw, locate a moved payload field, and decide between
  normalizing and reimplementing.

## Proxy (optional)
Set `"proxy": "http://user:pass@host:port"` in config.json.

## This install is a git working copy

`~/.hermes/skills/x-cli` is a clone of `novasterling1337/x-cli` — a maintained fork of
`ignsoftwarellc/x-cli` (kept as the `upstream` remote). It is the canonical source: edit
here, verify with `scripts/smoke_test.py`, then commit and push. `README.md` documents the
fork's changes relative to upstream, and the repo is public so any other Hermes host can
clone it.

Nothing in Hermes rewrites THIS copy: the skill is not in `.bundled_manifest` (so
`hermes update` never re-seeds it) and it is not in the hub's `lock.json`, with
`hermes skills list --source hub` not listing it either (18 hub-installed skills, none of
them x-cli), so `hermes skills check` / `update` ignore it. Where it IS hub-installed (a
fresh `hermes skills install` on another host writes a lock entry with a `content_hash`),
`hermes skills update` skips skills whose local content no longer matches that hash —
which a `cookies.json` or `.venv/` in the directory immediately makes true — and the only
way past it is `--force`, which rmtree-replaces the directory and would take `.git` with
it. So on every host: `git pull`, or reinstall from a new pinned SHA.

`cookies.json` is a live X session and is gitignored, along with `config.json` and the
per-host `.endpoint_ids.json`. Never `git add -f` them, and never let a cookie value reach
a commit, an issue, or a chat reply.

