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

### The write backend (second interpreter, REQUIRED for posting)

twikit 2.3.3 **cannot post at all** — it cannot build an `X-Client-Transaction-Id`
(`Couldn't get KEY_BYTE indices`) and X enforces that header on writes only, which is why
reads work perfectly while every mutation is refused. The fix is twifork 2.4.0, but it
installs a module ALSO named `twikit`, so it cannot live in `.venv` without clobbering the
pinned 2.3.3 the read path and `x_compat.py` depend on. Use a second interpreter:

```bash
cd ~/.hermes/skills/x-cli
.venv/bin/python -m venv .venv-write
.venv-write/bin/pip install "twifork[impersonate]"
.venv-write/bin/python scripts/x_write_twifork.py whoami   # -> {"screen_name": ...}
```

`scripts/x_post.py` detects `.venv-write` and delegates every write to
`scripts/x_write_twifork.py`; with no `.venv-write` present it falls back to the old
twikit path, so a host that skips this step behaves exactly as before. `--dry-run` shows
which backend would send. `.venv-write/` is gitignored.

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
python scripts/x_search.py "hermes agent" --product Top   # what traveled, not just what's new
```
`--product` is `Latest` (default) or `Top`. This matters: `Top` returns the high-engagement
tweets in a niche, `Latest` returns whatever was just posted, most of it with zero likes.

### Post (`x_post.py`) — confirm with user first! Never post, reply, DM, or delete on your own initiative, and never infer consent from a read request.

Writes are sent by `scripts/x_write_twifork.py` under `.venv-write` (twifork 2.4.0 +
`impersonate="chrome124"`); see Setup. Same commands, same flags:

**Quote the text in SINGLE quotes in a shell.** `--dry-run` prints the exact string that
would be sent — check it. A double-quoted `"...under $10..."` reaches X as `under 0`,
because the shell expands `$1` and silently eats the digit. That is a publish-time bug with
no error attached to it.
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

**Before proposing the official paid API as the fix for a refused write**, read
`references/x-api-official-posting.md`. It is per-request priced ($0.015 a post, $0.200
if the text contains a URL anywhere), quote posts are Enterprise-only on self-serve,
replies are only permitted when the account was summoned, and API posts carry your
app's source label. Standalone posts and comments are the containers it can actually
take over; quotes are not.

### Drafting post copy (quotes, replies, originals)

When asked for variations of a post, the deliverable is drafts the user can pick, not prose:

- **Read the target post first** (`x_read.py tweet`, falling back to `thread`), and draft
  against its actual text. Drafting from the URL's presumed vibe produces copy that
  argues with a post nobody wrote.
- **One angle per variation, and name the angle** in the reply (verify-the-claim,
  contrarian, personal, implication, one-liner). Two drafts making the same point is one
  draft with extra steps.
- **Count characters with a tool and print the count beside each draft.** 280 applies to
  the body; a quoted post does not consume it, so quote-tweet copy can use the full 280.
- **Never invent facts, numbers, quotes, or personal history** to make a draft land.
  First-person claims the user did not supply are things they must own — flag which
  drafts assert something about them so they can cut or edit it.
- **Voice:** direct, specific, sharp; no hashtags, no emoji spam, no corporate or
  thought-leadership register. A draft with no real position is not worth offering.
- **Plain beats lyrical.** Short declarative sentences, concrete specifics, ordinary
  words. No metaphor, no simile, no rhetorical flourish, no em-dash cadences. When this
  user says "less prosaic", the fix is cutting the imagery — not the length, not the
  opinion. A flat statement or a one-line joke beats a clever construction, and a
  metaphor in a tweet reads as effort where the user wanted a reaction.
- **When the user supplies a format, produce variations IN that format.** A paste like
  `Me: "..."` / `<name>: "..."` is the requested shape of the deliverable, not a theme
  to write prose about: keep speaker labels, quote marks and line order identical across
  every variation, and vary the punchline only.
- **Say which variation is structurally strongest, and why, in one line each.** The pick
  is part of the deliverable; five equal drafts with no judgment pushes the choice back
  onto the user.
- **Drafting is free; publishing never is.** Present the drafts and stop. Posting,
  quoting, replying or DMing one requires the user naming the draft.
- **Scheduling an approved draft** for a posting window instead of publishing inline:
  `references/miles-board-scheduling.md` — the board's task-note contract, the
  slot table, and the arming gate that silently swallows the post when it is off.
  A note filed for a later window is a PUBLISH path, not a draft: when the user asks
  for options without naming one, file it in the Backlog column with `Option` unset
  and only set `todo` after they name a letter.
- **Read the target tweet before drafting against it** (`x_read.py tweet <url-or-id>
  --json`) — a quote draft is written from the source's actual text, and the source's
  claim is not yours to amplify unchecked. When the user's own wording overstates what
  the source supports, offer the narrower version as one of the options and say which
  drafts inherit the overreach, instead of silently rewriting their voice.

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

### JSON fields (`--json`)
One object per line, from `format_tweet` in `scripts/x_utils.py`:
`id, user, name, text, created_at, url, retweet_count, favorite_count,
reply_count, quote_count, bookmark_count, view_count, media, reply_to`.

Engagement counts come from the twikit Tweet object. twikit hands `view_count` back
as a numeric STRING; `tweet_to_data` coerces it to int, so `--json` emits one type on
both the twikit and the raw-payload path. It is absent for some older tweets — treat a
missing value as unknown, not zero. **If a consumer reports one of these fields as
unavailable, read `format_tweet` before believing it:** the counts live on the
object and this mapping is the only thing exposing them, so an omission here looks
exactly like a platform limitation to everything downstream.

**`--json` framing is not uniform — parse defensively.** `x_read.py` and
`x_search.py` emit one object per line (streamable); `x_extra.py user-info` prints
a single pretty-printed object across many lines. A line-scanning parser gets the
first and silently returns nothing for the second, so try `json.loads` on the whole
stdout first and fall back to per-line. Reads also print human notices (`No replies
found.`) on the same stream — skip any line that is not a JSON object.

**`pinned_tweet_ids` is a STUB, not data.** `x_compat.py`'s `_USER_LEGACY_DEFAULTS`
hardcodes `'pinned_tweet_ids_str': []`, so every user object reports zero pins whether
or not the account has one, and `UserTweets` pin entries are dropped by the parser.
NEVER infer "this account has no pinned tweet" from an empty `pinned_tweet_ids` — that
claim is always false-able. Either ask the account owner, or read the profile in a
logged-in browser. Verified failure: a profile audit reported "no pin" for an account
that had one pinned, and the wrong verdict drove the top recommendation.
Photo/avatar and banner ARE real: `profile_image_url` and `profile_banner_url` come
through intact, and the banner URL's path segment is the upload timestamp
(`/profile_banners/<user_id>/<unix_ts>`), which is the only way to date a stale header.

Treat these key names as a contract: bundles and wrappers consume them, and a
renamed or dropped key breaks them with no error at all.

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

### Sharing one install across Hermes profiles

A named agent profile gets X access by symlinking, never copying:

```bash
ln -s ~/.hermes/skills/x-cli ~/.hermes/profiles/<slug>/skills/x-cli
```

One venv, one `cookies.json`, one rotation point. A copy forks the live session
credential and the two then drift. Both resolvers used by consuming bundles
(`<HERMES_HOME>/skills/x-cli`, then `~/.hermes/skills/x-cli`) hit the same
directory through the link, so a profile's reads and writes are the SAME account
as the main one — say that out loud when wiring it, and keep the per-post
approval gate intact.

Verify THROUGH that profile's home, because the point is its resolution order,
not yours:

```bash
cd ~/.hermes/profiles/<slug>/skills/x-cli && .venv/bin/python scripts/x_auth.py whoami
# write path, no side effect: the bundle's own poster must answer mode=xcli
cd <bundle> && echo '{"kind":"post","draft_text":"routing check","dry_run":true}' \
  | env HERMES_HOME=~/.hermes/profiles/<slug> ./.venv/bin/python scripts/x_cli_poster.py post
```

Availability is not enough on its own: a profile can ship a second X skill (an
API-key CLI, a scraper) whose friendly description wins the routing while its own
credentials are unset, so the call dead-ends and reads as "X is broken". Prove
which backend answered (`read_client()` type, `active_backend()`) and give that
profile a standing rule naming x-cli — full procedure: the `hermes-agent` skill's
`installing-skill-bundles` reference, Step 7.

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

Do NOT reach for a real `X-Client-Transaction-Id` as a first move: reads accept the
placeholder indefinitely, the original derivation algorithm is gone from the bundle,
and deriving a replacement is a reverse-engineering project. The one place it stays a
live suspect is a WRITE that keeps getting refused while reads work (see item 5) —
check whether the bundle list still serves `ondemand.s` before spending more than a
few minutes on it.

4. `KeyError: 'user_results'` from twikit's `tweet_from_data`. X varies the payload
   shape between identical requests (author block withheld, visibility wrapper), so
   `get_tweet_by_id` succeeds on one call and dies on the next for the SAME tweet.
   Always read through `scripts/x_tweet_fetch.py` (`fetch_tweet_data`,
   `get_tweet_resilient`), which retries and then parses the raw `TweetDetail`
   payload. Do not patch twikit inside `.venv` — the next `pip install -r
   requirements.txt` wipes it — and do not add a new bare `client.get_tweet_by_id`
   call to a command.

5. A WRITE is refused while every read works. First confirm the backend: `.venv-write/bin/python
scripts/x_write_twifork.py whoami` must answer, and `x_post.py --dry-run` must say "via
twifork" — on twikit 2.3.3 alone, writes cannot work and never will. X answers the mutation with HTTP 200 and
a numeric `errors[0].code`; the code is the classifier, the message prose is not.
`385` means the gate accepted the write and only the target was bad; `226` means the
anti-automation gate is armed on that write path (measured: quotes refused while a
plain write still reached 385); `344` means a write quota is gone, including a rolling
limiter tripped by several attempts in a few minutes. Diagnose by copying the
`CreateTweet` variables with an impossible `reply_to` so nothing can publish — run
`scripts/x_write_probe.py` (once, never in a loop, since each probe feeds the same
gate). Before changing the schedule to fix a `226` (random jitter, "posts at the same
minute daily"), read the recorded publish timestamps — a first-attempt refusal in a
fresh window cannot be caused by second-scale regularity, and the cheap-cadence
reasoning is in the reference's "Before blaming the schedule". Full code table, ordering,
and the scheduler rules that follow from it (park on
226/344/429/32, one attempt a day on a code with no policy, never spend a per-task
retry budget on a session gate, retry a silent drop only across ticks):
`references/x-write-refusals.md`.

## Keeping it working

- `scripts/smoke_test.py` — runs the whole command surface and prints PASS/FAIL
  per command (`.venv/bin/python scripts/smoke_test.py --tweet <id>`, plus
  `--like <id>` to exercise and verify the write path). Run it after ANY change to
  `x_compat.py`, `x_utils.py`, or a script's argument handling: shared changes
  regress unrelated commands, so a fix is not done until the whole list is green.
  A BARE run is read-only (17 checks; the post check is `--dry-run`), so run it
  without asking for approval. Only `--like <id>` mutates the account — leave that
  one out unless the user has approved liking a specific tweet.
- `references/twikit-drift-repair.md` — how to find the operation that replaced a
  retired one, probe it raw, locate a moved payload field, and decide between
  normalizing and reimplementing.
- `references/x-write-refusals.md` + `scripts/x_write_probe.py` — classify a refused
  post by X's numeric code, and probe the write gate without any chance of publishing.
- `references/x-api-official-posting.md` — what the official paid API costs per post,
  its self-serve restrictions (quote is Enterprise-only, replies need a summon), and
  why no batched thread write exists in either the API or the GraphQL surface.
- `references/twikit-fork-landscape.md` + `scripts/probe_txid_handshake.py` — whether the
  installed twikit build can WRITE at all (probe it, never infer from reads working),
  which maintained forks exist and which to skip, and when swapping the base library
  beats maintaining the shim. Read this before telling the user a library is abandoned
  or recommending a fork: verify from the GitHub/PyPI APIs, and trust the PyPI
  `upload_time` over the tag date.

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

