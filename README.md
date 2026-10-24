# 𝕏 X-CLI

**X/Twitter toolkit for AI agents — no API key, no developer account, just cookies.**

Read tweets, search, post, interact, manage lists, upload media, send DMs — all from
the command line. Powered by [twikit](https://github.com/d60/twikit).

> **This is a maintained fork of [ignsoftwarellc/x-cli](https://github.com/ignsoftwarellc/x-cli).**
> Upstream has not been touched since its single initial commit (2026-02-19) and no
> longer works against x.com — see [What this fork changes](#-what-this-fork-changes).

---

## ⚡ Why X-CLI?

| Feature | X-CLI | Twitter API v2 | Bird CLI |
|---------|-------|---------------|----------|
| **Cost** | Free | $100+/mo | Free |
| **API Key** | Not needed | Required | Not needed |
| **Auth** | Cookie-based | OAuth 2.0 | Cookie-based |
| **Server/VPS** | ✅ Works | ✅ Works | ⚠️ Needs browser |
| **Proxy** | ✅ Built-in | N/A | ❌ No |
| **Language** | Python | Any | Node.js |

---

## 🧩 What this fork changes

Upstream died because twikit (last release 2.3.3, itself unmaintained) assumes an
x.com frontend and GraphQL API that no longer exist. Every breakage below is
twikit-side — the cookies are fine. The fork adds `scripts/x_compat.py`, a shim that
is imported by `x_utils.py` before any client is built, and repairs the commands
that had no working path at all:

1. **`X-Client-Transaction-Id` derivation no longer fatal.** twikit scrapes a webpack
   mapping out of the x.com homepage that X stopped shipping, so *every* command died
   with `Couldn't get KEY_BYTE indices`. X accepts GraphQL requests with a placeholder
   id (verified against `UserByScreenName`, `Viewer` and the `FavoriteTweet`
   mutation), so the derivation is skipped.
2. **GraphQL query ids refreshed from X's live bundle.** twikit's hardcoded ids answer
   `404 {"errors":[{"code":34}]}`, which is what killed search, followers/following
   and TweetDetail. `refresh_query_ids()` re-reads the pairs from the client bundle,
   cached 24h in `.endpoint_ids.json`, and is called from `get_client()`.
3. **Payload normalizers.** Refreshed ids return the newer profile model (`core`,
   `avatar`, no `legacy` object) which twikit's `User`/`Tweet` parsers reject. The shim
   synthesizes the legacy shape and pads every indexed key, so old and new payloads
   both parse.
4. **GET→POST fallback.** `SearchTimeline` answers 404 to GET and 200 to POST; a
   `NotFound` on a GraphQL GET is retried as POST. This is what makes search work.
5. **`whoami` un-broken.** twikit reads the user id from the retired v1.1
   `account/settings.json`; the shim takes it from the GraphQL `Viewer` query instead.
6. **Rewritten commands** (twikit had no working path):
   - `replies` / `thread` — twikit 2.3.x has no `get_tweet_replies`; they drain the
     tweet's attached reply `Result` and page it via `Result.next()`.
   - `mentions` — `get_notifications("Mentions")` answers empty on the retired v1.1
     endpoint; searches `@me -from:me` instead.
   - `trends` — GraphQL `ExplorePage` instead of the retired v1.1 `guide.json`, whose
     404 made twikit retry itself into a `RecursionError`.
   - `dm inbox` — v1.1 `dm/inbox_initial_state.json`, decoded into
     participants / last message / timestamp / muted, with `--json` support.
   - `notifications` — renders timestamp, actor, message and tweet link instead of a
     raw object repr.
7. **`--json` (and `x_post.py --dry-run`) accepted after the subcommand**, i.e. both
   `x_search.py "query" --json` and the documented `x_post.py tweet "hi" --dry-run`.
8. **`scripts/smoke_test.py`** — exercises the whole command surface against the live
   account and prints PASS/FAIL per command (read-only unless `--like` is passed, which
   also verifies the mutation server-side).

---

## 📦 Installation

### As a Hermes skill (agent use)

```bash
git clone https://github.com/novasterling1337/x-cli ~/.hermes/skills/x-cli
cd ~/.hermes/skills/x-cli

python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
```

This is the recommended path: the clone is complete and updatable in place with
`git pull` (your `cookies.json`, `config.json`, `.venv/` and `.endpoint_ids.json` are
gitignored, so pulling never touches them).

Hermes can also install it through the hub — pin the commit, not `main`:

```bash
hermes skills install https://raw.githubusercontent.com/novasterling1337/x-cli/<sha>/SKILL.md
```

That route copies only the files `SKILL.md` names explicitly, and only from
`references/ templates/ scripts/ assets/ examples/` — so `config.example.json`,
`README.md` and `LICENSE` do not come along, and `scripts/x_utils.py` does only because
`SKILL.md` names it. A branch-tip URL (`/main/SKILL.md`) can additionally serve a stale
cached copy of `SKILL.md` for minutes after a push, which produces an install with no
`scripts/x_utils.py` and an immediate `ModuleNotFoundError`. After any hub install, check
`ls scripts/x_utils.py`; if it is missing, use the clone above.

### Standalone (any directory)

```bash
git clone https://github.com/novasterling1337/x-cli.git
cd x-cli
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
```

### Both paths

Python **≥ 3.10** is required (twikit's floor). The pinned twikit 2.3.3 installs and runs
on CPython 3.11 through 3.14 — tested on 3.11.15 and 3.14.4. Without Homebrew/pyenv, a
uv-managed interpreter works.

`config.json` is **optional**: it exists for a proxy or credential login, and a
`cookies.json` alone is a complete install. Copy `config.example.json` only if you want to
set a proxy or store credentials.

Run every script with that venv's python — a bare `python scripts/x_read.py` picks up the
host interpreter and dies with `ModuleNotFoundError: No module named 'twikit'`. Either use
`.venv/bin/python` or `source .venv/bin/activate` once per shell, and invoke scripts as
`scripts/<name>.py` from the project root: they import sibling modules, so a lone script
copied elsewhere will not run.

Smoke-test the install end to end (read-only against your own account):

```bash
.venv/bin/python scripts/smoke_test.py     # 17 checks, PASS/FAIL per command
```

---

## 🔐 Authentication

X-CLI authenticates with your browser's X session cookies. `cookies.json` lives next to
`config.json` and is a **flat name/value map** — nothing else:

```json
{"auth_token": "...", "ct0": "..."}
```

`auth_token` and `ct0` are the two that matter. A Cookie-Editor export (an array of
`{name, value, domain, ...}` objects) is **not** accepted — twikit passes the parsed JSON
straight to `httpx.Cookies.update`.

```bash
.venv/bin/python scripts/x_auth.py whoami    # @your_handle + follower counts
```

`x_auth.py check` only reports whether `config.json` and the cookie file exist — it is not
a liveness probe. `whoami` and `x_extra.py user-info <handle>` are.

Notes:

- Treat `cookies.json` as a **live session**, not a static key: when a read fails, re-run
  `whoami` before blaming the script.
- `config.json` can carry `x_username` / `x_password`, but that stores a password in
  plaintext and twikit's login flow trips X CAPTCHAs. Cookies are the supported path.
- **Never commit `cookies.json` or `config.json`** — both are in `.gitignore`, and
  `cookies.json` is a full account takeover if leaked. Chrome/Arc cookie stores are
  Keychain-encrypted on macOS and need an interactive unlock, so paste the two values or
  write the file yourself.

---

## 📖 Commands

All commands take `--json` for structured output, and the flag is accepted before or after
the subcommand.

### 📰 Read (`x_read.py`)
```bash
python scripts/x_read.py tweet https://x.com/user/status/123456   # single tweet
python scripts/x_read.py user jack --count 5                      # a user's tweets
python scripts/x_read.py timeline --count 20                      # home timeline (Following)
python scripts/x_read.py foryou --count 20                        # For You timeline
python scripts/x_read.py thread https://x.com/user/status/123456  # full thread
python scripts/x_read.py replies https://x.com/user/status/123456 --count 20
python scripts/x_read.py mentions --count 10                      # your mentions
python scripts/x_read.py highlights elonmusk --count 5
python scripts/x_read.py search-user "space engineer" --count 10
```

### 🔎 Search (`x_search.py`)
```bash
python scripts/x_search.py "artificial intelligence" --count 10
python scripts/x_search.py "from:zerohedge gold" --count 5
python scripts/x_search.py "#OpenSource min_faves:100"
python scripts/x_search.py "yapay zeka lang:tr" --count 10
```

### ✏️ Post (`x_post.py`)

**Confirm with the account owner before any write.** Never post, reply, DM, delete, or
follow on your own initiative, and never infer consent from a read request.

```bash
python scripts/x_post.py tweet "Hello from X-CLI! 🚀"
python scripts/x_post.py tweet "Draft tweet" --dry-run               # preview only
python scripts/x_extra.py upload photo.jpg                           # -> media id
python scripts/x_post.py tweet "Check this out!" --media abc123
python scripts/x_post.py reply https://x.com/user/status/123 "Great analysis!"
python scripts/x_post.py quote https://x.com/user/status/123 "Adding context..."
```

A write is only done when the **server** agrees. After any mutation, read the target back
(`x_read.py tweet <id> --json`, or the parsed tweet's `favorited` / `retweeted` /
`favorite_count`) and check the value changed — a `✅ Liked tweet …` line only proves the
request left the client.

### 💬 Interact (`x_interact.py`)
```bash
python scripts/x_interact.py like|unlike|retweet|unretweet|bookmark|unbookmark <tweet>
python scripts/x_interact.py follow|unfollow|mute|unmute|block|unblock <username>
python scripts/x_interact.py delete <tweet>
```

### 📩 DMs (`x_dm.py`)
```bash
python scripts/x_dm.py send elonmusk "Hey, great tweet!"
python scripts/x_dm.py inbox --count 10
```

### 🧰 Extra (`x_extra.py`)
```bash
python scripts/x_extra.py trends                              # also --category news
python scripts/x_extra.py bookmarks --count 10
python scripts/x_extra.py notifications --count 10
python scripts/x_extra.py user-info elonmusk
python scripts/x_extra.py followers elonmusk --count 20
python scripts/x_extra.py following elonmusk --count 20
python scripts/x_extra.py upload path/to/image.jpg
python scripts/x_extra.py schedule 1740000000 "Scheduled tweet!"
python scripts/x_extra.py poll "Option A" "Option B" "Option C" --duration 1440
python scripts/x_extra.py list-create "Tech News" --private
python scripts/x_extra.py list-add 12345 jack
python scripts/x_extra.py list-remove 12345 jack
python scripts/x_extra.py list-tweets 12345 --count 20
```

### 🔑 Auth (`x_auth.py`)
```bash
python scripts/x_auth.py check     # files present, NOT a liveness check
python scripts/x_auth.py whoami    # current user (real GraphQL probe)
python scripts/x_auth.py login     # credentials from config.json (CAPTCHA-prone)
```

### 📊 JSON output
```bash
python scripts/x_read.py user jack --count 3 --json
```
```json
{
  "id": "123",
  "user": "jack",
  "text": "Exciting new update coming soon!",
  "favorite_count": 500,
  "media": [{"url": "https://pbs.twimg.com/media/abc.jpg", "type": "photo", "alt_text": null}],
  "reply_to": null
}
```

---

## 👁️ Media & vision

Tweets with media expose their URLs (`🖼️` / `🎥`), and replies carry a `↩️ Reply to:` link
to the parent:

```
@NASA (NASA)
Perseverance rover captures new Mars panorama 🔴
❤️ 5200  🔁 1800  🔗 https://x.com/NASA/status/123
🖼️ https://pbs.twimg.com/media/abc123.jpg
↩️ Reply to: https://x.com/i/status/456
```

An agent can fetch the media URL, analyze it with vision (charts, infographics,
screenshots), and reply with context.

---

## 🩺 Command status

Verified against a live account, 2026-10-24:

| Command | State |
| --- | --- |
| `x_auth.py check`, `whoami` | works |
| `x_read.py tweet/user/timeline/foryou/thread/replies/mentions/highlights/search-user` | works |
| `x_search.py` | works (via the POST fallback) |
| `x_extra.py user-info/followers/following/trends/bookmarks/notifications` | works |
| `x_dm.py inbox` | works (via v1.1 `dm/inbox_initial_state.json`) |
| `x_interact.py like` | verified end to end: `favorite_count` 0 → 1, `favorited: true` on re-read |
| other writes (post / DM / delete / follow / …) | same GraphQL mutation path, unexercised here |

### When a command fails anyway

Everything above works today, so a failure now means one of these, in order:

1. **Expired session.** Cookies are a live login; a 401/403 on a command that used to work
   means re-auth, not a bug. Confirm with `x_extra.py user-info <handle>`.
2. **A rotated operation.** If a GraphQL call still returns
   `404 {"errors":[{"code":34}]}` after a successful `refresh_query_ids()`, X retired that
   operation itself and the endpoint needs re-discovery from the live bundle
   (`/i/api/graphql/<id>/<Operation>` pairs in `main.*.js`).
3. **User-agent sensitivity.** v1.1 endpoints X still serves can 404 for twikit's UA and
   200 for a browser one, with identical cookies.

Don't chase a "real" `X-Client-Transaction-Id`: X still accepts the placeholder on the
operations in use, and the original derivation algorithm is gone from the bundle.

### Keeping it working

```bash
.venv/bin/python scripts/smoke_test.py                 # 17 read-only checks
.venv/bin/python scripts/smoke_test.py --tweet <id>    # + tweet / thread / replies
.venv/bin/python scripts/smoke_test.py --like <id>     # + write path, verified
```

Run it after **any** change to `x_compat.py`, `x_utils.py`, or a script's argument
handling — shared changes regress unrelated commands, so a fix isn't done until the whole
list is green. `references/twikit-drift-repair.md` documents how to find the operation
that replaced a retired one, probe it raw, and decide between normalizing and
reimplementing.

---

## 🌐 Proxy (optional)

```json
{ "proxy": "http://username:password@host:port" }
```

Recommended on VPS/datacenter IPs. Not required — without it X-CLI connects directly.

---

## ⚠️ Disclaimer

X-CLI drives X/Twitter's private web GraphQL endpoints through twikit. This is **not** an
official API and X can change it at any time — expect breakage without notice. Cookie
auth means the tool holds a live session for whatever account you point it at: use a
dedicated low-risk account, keep `cookies.json` out of git and out of chat, and require
explicit confirmation before any account-changing command.

## 📜 License

MIT — free to use, modify, and distribute. See [LICENSE](LICENSE).

## 🙏 Credits

- [IGN Software LLC](https://github.com/ignsoftwarellc) — original x-cli
- [twikit](https://github.com/d60/twikit) — Python X/Twitter API wrapper
