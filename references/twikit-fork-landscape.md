# twikit, its forks, and when to replace the base library

When a twikit-backed install misbehaves, the question that decides everything is whether
the *base library* is still viable. Answer it with data, not with the README badge and
not with reputation.

## Verify maintenance from the APIs, not the page

```bash
curl -s https://api.github.com/repos/<owner>/<repo>            # pushed_at, stargazers_count, archived, open_issues_count
curl -s https://api.github.com/repos/<owner>/<repo>/releases?per_page=1   # tag_name, published_at
curl -s https://pypi.org/pypi/<package>/json                   # info.version, releases[<v>][0].upload_time
```

- **Read the PyPI `upload_time`, not the GitHub tag date.** A repo can tag a release and
  never publish it, and the installed distribution is what you actually run.
- **A repo whose API returns 404 while PyPI still serves versions is unverifiable source.**
  Do not adopt it, even when it installs and imports cleanly — you cannot read what you
  would be running.
- **Last commit outranks stars.** A very popular repo with a months-old last commit and a
  year-old release is abandoned in practice; a small repo that committed this week is
  maintained. Report both numbers and let the user see the asymmetry.
- Check whether the project is actually `archived` before calling it dead — "no releases"
  and "not archived" often coexist and mean "unmaintained", which is a different claim.
  Make the specific claim the evidence supports.

## Candidate shapes

- **Drop-in fork** — same import name (`twikit`), fixed internals. Verify by installing in a
  throwaway venv and asserting `import twikit` exposes `Client` and a version string. This
  is the only fork shape that does not force a rewrite of existing call sites.
- **Different-API scraper** — fine for reads, frequently useless for the write path. Before
  proposing one as a posting fix, confirm it has a create/post call at all. (Bulk scrapers
  built around an account pool and a local store are read-only by design; they are not a
  posting fix, however actively maintained they are.)
- **Skip** — no PyPI release (git-install only), near-zero stars, or a 404 source repo.
  Say why, in that order, instead of listing them as equivalent options.

## The write-path question is answered by probe, not reputation

The `X-Client-Transaction-Id` handshake is what separates a build that can WRITE from one
that can only READ. Run `scripts/probe_txid_handshake.py` against a candidate before
recommending it. Three distinct outcomes, and they mean different things:

| Output | Meaning |
| --- | --- |
| `Couldn't get KEY_BYTE indices` | Packaged parser is stale; the handshake cannot complete; writes are dead. Reads may still pass on the lenient path — which is exactly why "reads work" is not evidence of health. |
| `InvalidSession` / `logged-out page shell` | Handshake code is healthy and merely has no session. This is the pass result — confirm with a real cookie file. |
| A transaction id string | Fully healthy. |

X enforces the transaction header **selectively**: reads tolerate a placeholder or a
stale key, writes are strictly checked. A library that reads perfectly while every
mutation is refused, 404s, or trips the anti-automation gate is showing this signature —
do not send yourself looking for a bug in the mutation payload.

## twifork's handshake fetches x.com WITH the API Bearer header — fix it before judging the cookies

`ClientTransaction.init(session, headers)` performs the HTML fetch of `https://x.com/` using
the header dict it is handed, and `Client` hands it `_base_headers`. That dict carries
`authorization: Bearer <guest token>` (plus `content-type: application/json`), and x.com's
web router answers **401 with a 0-byte body** when that header is present alongside live
login cookies. The handshake then raises `InvalidSession` — "cookies are missing, expired
or rejected" — which is a FALSE diagnosis: `client.user()` on the same client returns the
account fine.

Measured on twifork 2.4.0 with a live session, same cookies, same IP:

| request | result |
| --- | --- |
| `GET https://x.com/` with `_base_headers` | 401, 0 bytes, no manifest |
| same, minus `authorization` | **200, 316,908 bytes, manifest present** |
| same, minus `content-type` only | 401 |
| UA + `Accept-Language` only | 200 |

So the offending header is `authorization` alone. Strip it (and `content-type`) from the
headers passed to the HTML fetch, keep them for the GraphQL calls that require them:

```python
STRIP = {"authorization", "content-type"}
orig = T.ClientTransaction.init
async def init(self, session, headers):
    clean = {k: v for k, v in (headers or {}).items() if k.lower() not in STRIP}
    return await orig(self, session, clean)
T.ClientTransaction.init = init
```

With that patch, twifork 2.4.0 + `impersonate="chrome124"` + `{auth_token, ct0}` produced a
real transaction id and `CreateTweet` reached the gate, answering **385** (bogus reply
target refused, gate OPEN) instead of 226. Do not report "cookies are stale" from an
`InvalidSession` on this package without checking `client.user()` first.

Related: `set_cookies` on twifork 2.4.0 takes a positional dict (`set_cookies(cookies)`), not
kwargs — `set_cookies(**cookies)` raises `TypeError: unexpected keyword argument`.

## Version-drift pitfalls when writing your own probe

- The handshake object is `client.client_transaction`; notes and older snippets say
  `_client_transaction` and will AttributeError.
- `Client.__init__` kwargs differ per fork — `impersonate=` exists only where curl_cffi is
  bundled. Intersect `inspect.signature(Client.__init__).parameters` with the kwargs you
  want instead of hardcoding them, and fall back to no-impersonate if construction fails.
- `ClientTransaction.init(http, headers)` takes two positional args; `client._base_headers`
  is the header set to pass.
- Treat "handshake completed" as the primary signal and wrap id generation in try/except —
  a fork can rename the generation call, and a rename must not read as a failure.
- `set_cookies` accepts either keyword form or a dict depending on version; try kwargs,
  fall back to the dict.

## Maintain the shim or swap the library?

- If the shim already carries a working fix for the current frontend, a base-library swap
  is NOT an upgrade — it re-opens regressions the shim has closed. Weigh the fork only
  when the shim's approach has stopped working for **writes**.
- Swapping the base library means re-validating the compat shim and the whole smoke test.
  Keep the pin; an unpinned base library is the failure mode, not the fix.
- When writes keep failing on a healthy library, the honest options are (a) keep working
  the web-session path with browser TLS impersonation, cookies exported from the same
  IP that posts, and human pacing, or (b) move writes to the official API —
  `references/x-api-official-posting.md`. Unofficial writes always carry the
  anti-automation-gate risk (#226) and a maintained fork cannot remove it.
- State that tradeoff plainly to the user with cost per post; do not present "upgrade the
  library" as if it eliminates a platform-level gate it cannot touch.
