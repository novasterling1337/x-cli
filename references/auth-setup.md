# x-cli auth setup

Everything here assumes the skill venv exists (`python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt` in the skill dir) and that commands run as `.venv/bin/python scripts/<script>.py`.

## First-run checklist

1. `cp config.example.json config.json` (defaults are fine, `cookies_file` defaults to `cookies.json`).
2. Get `auth_token` and `ct0` from a browser that is logged into x.com (below).
3. Write `<skill_dir>/cookies.json` as a flat map: `{"auth_token": "...", "ct0": "..."}`.
4. `.venv/bin/python scripts/x_auth.py check` (reports only that the files exist).
5. Prove the session is live with a read that returns identity:
   `.venv/bin/python scripts/x_auth.py whoami` or
   `.venv/bin/python scripts/x_extra.py user-info <any-known-handle>`. Real user
   data means the cookies work.
6. Only after that probe returns a real user, run the actual read or search command.

## Where the two cookies come from

Give the user these routes, cheapest first:

- Chrome / Arc / Edge: DevTools (Cmd+Opt+I) -> Application -> Storage -> Cookies -> `https://x.com` -> copy the Value column for `auth_token` and `ct0`.
- Firefox: DevTools (F12) -> Storage -> Cookies -> `https://x.com` -> same two names.
- Safari: Settings -> Advanced -> Show features for web developers, then Develop -> Show Web Inspector -> Storage -> Cookies.
- Any cookie-export extension ("Cookie-Editor" -> Export as JSON) works, but the export must be reduced to the flat `{"name": "value"}` map before twikit sees it. Do that reduction yourself instead of asking the user to hand-edit.

Do not try to lift the cookies out of the browser's own store. Chrome and Arc encrypt them behind the macOS Keychain, so it turns into an interactive unlock prompt for no benefit. Ask the user.

## Keeping secrets out of the transcript

Offer the user the choice, and state the tradeoff plainly:

- Paste the two values in chat: fastest, but the token then lives in session history and in any logs of it.
- Write the file themselves: `nano ~/.hermes/skills/x-cli/cookies.json`, pasting the one-line flat map. Nothing lands in chat.

Either way, never echo a cookie value back in a reply, and never print cookie contents while debugging. Print names and lengths if you need to prove the file is populated.

## Session hygiene

- `auth_token` is a full account session. It expires on its own schedule and X invalidates it when the user logs out elsewhere or when it is used from a very different IP. Plan for a refresh, do not assume one export lasts forever.
- When a command fails, decide FIRST whether the session is alive, and use `x_auth.py whoami` or `x_extra.py user-info <handle>` for that. That way an expired session is not mistaken for a broken script or a deleted tweet.
- A parse error or `Couldn't get KEY_BYTE indices` is twikit/upstream drift, never an expired cookie (see the command-status section in SKILL.md).
- A read that used to work and now 401/403s is an expired session; a GraphQL `404 {"code":34}` after a query-id refresh is a retired operation.
- Adding a proxy (`"proxy"` in config.json) can trip X's session checks. Only add one when the user asks for it.
- The `x_search` tool is a separate xAI-backed surface with its own credit requirement, so it can be unavailable while cookie auth works fine. Treat it as a complement, never as the guaranteed fallback.
