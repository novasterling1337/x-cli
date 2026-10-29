# When X refuses a write: refusal codes, and whose fault it is

A refused post is one of three different things, and they need different responses:
our payload is bad, the account/session is gated, or a quota is exhausted. X reports
all three through the same GraphQL mutation with the same HTTP 200, so the numeric
`code` inside `errors[0]` is the only reliable classifier. Read the code, never the
sentence — the sentence is X's prose and twikit's exception class, the code is data.

## The codes that matter

| code | message shape | what it actually means |
| --- | --- | --- |
| `385` | "cannot reply to a Tweet that is deleted or not visible" | The write REACHED validation. The gate accepted the request; only the target was bad. This is the negative control that proves the session can write. |
| `226` | "This request looks like it might be automated" | Account/session gate on the write path. Not payload-specific: it answers every quote (`attachment_url`) even one quoting our own tweet with a one-word body, while a plain write from the same client still reaches `385`. It also fires on the SECOND write of a burst: measured 2026-10-29, a post landed at 02:55:26 UTC and its follow-up comment was refused `226` three seconds later. Anything that posts a comment under a fresh post must therefore QUEUE it with a ~30 min floor and land it on a later run, never write it in the run that published the post. |
| `344` | "reached your daily limit for sending Tweets and messages" | Real daily cap OR a short rolling limiter tripped by repeated attempts in a few minutes. Do not assume "daily" means it resets at midnight — several refusals inside ten minutes produce it. Measured 2026-10-29: refused `344` at 01:01 UTC with one prior post in 24h, and `x_write_probe.py` answered `385` (gate open) at 02:44 UTC the same night. A `344` that lifts inside two hours was never a daily cap — so a scheduler must re-test it inside the posting window (45-60 min) instead of parking until UTC midnight, and only escalate to the long park on a second `344` in the same UTC day. |
| `32` | bad/missing auth | Session. Re-auth. |
| `429` | rate limiter | Back off; resets on its own. |
| `186` / `187` | too long / duplicate status | Payload. The text is wrong; retrying identical bytes cannot fix it. |
| HTTP 200, `tweet_results: {}`, no `errors` | nothing | Silent drop. The write was not accepted and X deliberately gives no reason. Treat as unconfirmed — read the account back before any retry. |

## Probe the write gate without being able to publish

`scripts/x_write_probe.py` (in this skill) sends the real `CreateTweet` mutation with
an impossible `reply_to` (tweet id `1`) plus an optional `attachment_url`, so X **must**
reject the request and nothing can ever land. What comes back identifies the layer:

```bash
cd ~/.hermes/skills/x-cli
.venv/bin/python scripts/x_write_probe.py                      # plain write
.venv/bin/python scripts/x_write_probe.py --quote <tweet-url>  # quote write
```

`385` → the gate is open and the last real failure was about the target or payload.
`226` → quotes are gated right now; a scheduled post will fail again if it retries now.
`344` → a write quota is exhausted; wait, do not retry.

**Run it once per diagnosis, not in a loop, and never as a pre-flight before every
publish.** Each probe is a write attempt and feeds the same gate: in a measured run a
quote probe answered `385`, and after a handful of probes every quote variant — the
real target, another tweet by the same author, an unrelated third party, our own
tweet — answered `226`. Probing escalates the refusal it is measuring, and a probe
spaced minutes apart still counts.

## Diagnosing in the right order

1. **Reads first.** `x_read.py tweet <id> --json` — a working read proves cookies are
alive and the GraphQL query ids resolve, so it removes session-expiry and rotated-id
theories in one call.
2. **Query id drift is checked, not assumed.** `Endpoint.CREATE_TWEET` after
   `get_client()` is the refreshed id, and it differs from both twikit's baked id and
   the cached pair; all of them reached `create_tweet` in the measured run. Drift in
   `.endpoint_ids.json` is not the explanation for a refusal that carries an
   operation-specific code.
3. **Probe once** (above) and classify by code.
4. **Read the account back** to confirm the tweet is absent before declaring anything
   about what landed — for a quote, the source tweet's `quote_count` is an independent
   second witness.

## Before blaming the schedule

"It looks automated because it fires at the same minute every day" is the most natural
theory and almost always the wrong one. Check it against recorded send times before
designing anything:

1. **Read the actual publish timestamps**, not the schedule. A window-based scheduler
   stores each publish time (e.g. a `posted` map of `path -> {url, at}` in its state
   JSON), and a board label like `ET Peak (22:30-23:30)` is a *window*, not a send
   time. Ticks land at varying seconds anyway (dispatch lateness of 30-90s is normal),
   so operators regularly see "same time daily" where the data shows 23:08, 00:30,
   09:00, 16:46.
2. **A first-attempt refusal in a fresh window cannot be caused by jitter.** If the
   failing write was the first of the day's window with no failed history behind it,
   delaying it 30-120s produces the same refusal 30-120s later. Ask what the *previous*
   successful write was and how long before the refusal it landed — that gap, or the
   day's total volume, is the cadence signal, not the clock minute.
3. **Second-scale jitter is not a lever.** X classifies cadence at minute/hour scale,
   and randomising within 2 minutes only moves a request inside noise the scheduler
   already produces. If a timing change is genuinely wanted, make it window-scale and
   deterministic per task per day (a random offset inside the posting window, seeded on
   task id + date so retries do not wander), never a fixed sub-two-minute delay.
4. **Check that the guard you are blaming was actually running.** When an implemented
   park or cap visibly did not hold, compare the script's mtime / `git log` against the
   failure timestamps: a limit written *after* the failures cannot have been in effect,
   and "the park is broken" sends the debugging into the wrong file.

The lever that does exist on the `226` path is container choice, not timing: it gates
`attachment_url` writes while plain writes from the same session still reach `385`. So
the recovery move for a quote task is to publish the same body as a standalone with the
source URL in the text (or hold it and post it plain in the next window) instead of
losing the post. Confirm the plain path is open with one plain `x_write_probe.py` run
first, and treat it as a hypothesis until a plain republish of a refused quote actually
lands — do not report it to the user as a proven fix.

## What a scheduler must do with these codes

- **Never write a post and its comment in one run.** The reply is queued against the
  landed URL with a first-attempt floor (~30 min) and sent by a later tick, so it can
  never ride the same burst as the tweet. Two gates then apply and the longer wins: the
  floor, and `last_attempt + retry gap` for a refused comment. Budget the attempts, not
  the ticks — a comment refused twice inside the floor window has spent nothing useful.
- **Park the job on the first `226`, `344`, `429` or `32`.** They are properties of the
  account at that moment, so retrying before they lift cannot succeed, and repeating a
  refused write is the exact pattern the gate punishes. A retry loop turns one refusal
  into a longer one. Parking means "stop retrying now", not "stop for the day": a
  `226` re-tests after ~60 min and a first `344`/`429` after ~45 min, because those
  windows are short enough to land inside the same posting slot; a second `344`/`429`
  in the same UTC day, and any `32`, keep the park to UTC midnight.
- **Never spend a per-task retry budget on them.** A task that failed three times to a
  session gate is not a task that failed three times on bad bytes; clearing that stale
  attempt record (rather than editing the note) is what gets the post out at the next
  window instead of a day later.
- **Do not treat `385`-class refusals as account-wide.** They kill the target, not the
  job, so parking every other approved post for the day is the wrong response — but see
  the next rule, which is what actually bounds them.
- **An unclassifiable numeric code gets ONE attempt per day, not a retry budget.** A code
  you have no rule for is still a refusal, and the codes X actually sends (`385` dead
  target, `186` too long, `187` duplicate) never clear ten minutes later, so a
  three-attempt budget on a 10-minute gap just re-sends identical bytes at the filter.
  Implement it as a field on the task's attempt record (e.g. `refusal_code`) that holds
  the task for the rest of the day whatever the gap or the count says. Clear that field
  on a failure carrying NO code, or a later transport blip inherits a dead payload's
  freeze and the task never retries again.
- **Take the code from a field, not from prose.** Have the publisher write
  `{"error", "code", "ambiguous"}` to stderr and read `code`; fall back to literal
  matching only when there is no numeric code at all. A numeric code that is not in the
  policy set must not short-circuit to "retry" before the prose fallback runs, and a
  `\b344\b`-style regex matches any line number or byte count that happens to contain
  the digits — which parks posting for a day over a stray number.
- **Notify once per task per day when a hold fires,** not once per tick: a hold that
  repeats the same message every 15 minutes trains the operator to ignore it.
- **On a silent drop (`empty tweet_results`), retry across ticks with a real gap, never
  inside the same turn,** and cap the attempts per task per day.
- **Cap volume per day and space writes out by tens of minutes.** Three writes inside
  half an hour, or a failure retried on the next tick twice, is the burst pattern the
  gate escalates (it goes `226` -> `226` -> silent drop). A per-day write cap plus a
  minimum gap between any two writes buys more safety than any amount of jitter.

## The placeholder transaction id

`x_compat.py` sends a fixed placeholder `X-Client-Transaction-Id` because the original
`ondemand.s` derivation source is no longer served. Reads tolerate it forever; writes
are where it becomes a suspect, and quote writes are the most reliably refused. Do
not spend an incident trying to derive a real id — check whether the bundle list
still contains `ondemand.s` (the shim scrapes `main.`/`vendor.`/`ondemand.`) and if it
is absent, say so and stop. The gate decays with time and with silence, not with
better camouflage invented under pressure.
