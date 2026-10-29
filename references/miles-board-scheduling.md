# Scheduling a post through the miles board

Publishing inline (`x_post.py quote ...`) posts NOW. When the user wants a post to land
in a posting window instead — or asks for options to approve before anything goes out —
the post becomes a task note on a board that a no-agent cron job drains. The selection
logic is deterministic Python in `~/.hermes/profiles/miles/scripts/x-task-poster.py`;
do not hand-roll scheduling, and do not write the note by guessing the schema — read
this file.

`~/.hermes/profiles/miles/skills/social-media/x-task-poster/SKILL.md` is the source of
truth for the poster's internals (option parsing, `## Follow-up` comments, refusal
parking, window arithmetic, verification). Read it when a publish misbehaves. Do NOT
edit that skill from the default profile — it belongs to `miles`.

## Where things live

- Vault: fast-note-sync `Development` (the global task store), reached through the FNS
  MCP (`mcp__fns__*`), never by reading `~/Documents`. Project note:
  `Projects/X- mariodian/X- mariodian.md`; tasks: `Projects/X- mariodian/_tasks/<slug>.md`.
- Poster: `~/.hermes/profiles/miles/scripts/x-task-poster.py`, cron every 15 minutes,
  `no_agent`. One post per tick, inside the task's `Time` window, then the task is
  marked `done`. A no-op tick costs nothing, so a missed tick inside a 60-minute window
  is simply retried.
- State: `~/.hermes/profiles/miles/state/x-task-poster.json`.

## Task note contract

The select fields decide WHAT publishes; the body only supplies the text.

```yaml
pm-task: true
projectId: "[[X- mariodian|X: mariodian]]"
id: "4xq7m2wj8t3rk1zt"        # any unique 16-char lowercase alphanumeric id
pm-task: true                 # and no note without it; the first gate in the scanner
type: task                    # anything else is ignored (option drafts are subtasks)
status: todo                  # "todo" == approved. Backlog/done/cancelled are inert
priority: high                # urgent/critical/p0 > high/p1 > medium/normal
due: "2026-10-27"             # the SEND date — due AFTER today = deferred, not published;
                              # empty = eligible now. `start` is never read by the poster,
                              # and a note with only `start` set is deferred with a reason
customFields:
  8fbvirqimvpetmvh: "A"                              # Option   (A-E, required to resolve)
  8877hzwvmvpfl60e: "ET Peak (22:30-23:30)"          # Time     (board slot label)
  kht323p8mvpesu9e: "quote"                          # Container (standalone|quote)
  akg5djgxmvqv9qac: "https://x.com/<author>/status/<id>"  # Source URL: heads the target chain
```

`Source URL` is the board-visible field and WINS over the legacy keys (`x-quote-url` →
`x-parent-url` → `x-reply-url`). Write both for a hand-filed note: the field is what the
board shows and edits, the key is the rollback path for notes filed before the field
existed. A `Container: quote` task with no resolvable `x.com/<user>/status/<id>` target is
a hard refusal — it stays in To do and publishes nothing.

Field ids are read from the project note's `customFields` at run time; those four are the
fallbacks baked into the script, so a freshly minted board keeps working.

Body:

```markdown
## Options

### A · 221 chars
<the exact text to publish; newlines are preserved>

### B · 234 chars
...
```

`### <letter>` headings are the parse boundary: text runs until the next heading or a
`---` line. Put a standalone `---` line after the options and keep the approval/footer
prose below it. The `· <n> chars` suffix is decoration, not a length check — count it with
a tool and stay under 280 (a quoted post's card does not consume the limit).

## Slots (local Asia/Taipei minutes-of-day)

| Label | Local TW | Reads as |
| --- | --- | --- |
| `PT evening + APAC (09:00-10:30)` | 09:00-10:30 | PT 18:00 / APAC 09:00 |
| `Europe morning (16:30-17:30)` | 16:30-17:30 | CET 09:30 |
| `ET morning + CET afternoon (20:30-21:30)` | 20:30-21:30 | ET 08:30 / CET 14:30 |
| `ET Peak (22:30-23:30)` | 22:30-23:30 | ET 10:30 |

`ASAP` is the fifth board option: no window, publishes on the next tick; it still respects
`due`. "The next window" is the first of the four whose start is later than the current
local clock; after the last one, it is tomorrow's first. Read `date` — never infer it.

**Do not translate "ET Peak" into an ET clock time when confirming with the user.** The
window is stored and enforced in local TW time; state both ("16:30 CST = 09:30 CET") or
the user hears the wrong time of day.

## Path A — file options for a later pick (nothing goes out yet)

1. **Read the target tweet first**:
   ```bash
   cd ~/.hermes/skills/x-cli && ./.venv/bin/python scripts/x_read.py tweet <id> --json
   ```
   Confirm it exists and draft against its actual text and date. `x_meta.py` in the miles
   scripts dir is the reader that also returns the tweet a reply quotes, when the context
   is a reply chain.
2. **Draft the options** per the umbrella's drafting rules; name the angle of each.
3. **File the note into Backlog** — `status: status-b5mzu4` — with `Container`, `Time` and
   `Source URL` filled and **`Option` left unset**. The poster refuses it with "no Option
   value set", which is exactly right for an unapproved draft. Do not pre-fill `A` to be
   helpful: a filled field row reads on the board as a decision nobody made.
4. **Register it on the project note** by rewriting the whole note: append the wikilink to
   `taskIds` and a `- [ ]` line under `## Tasks`, then `mcp__fns__note_create_or_update`.
   The project note carries a `customFields:` list of mappings that drives the board; a
   whole-content rewrite preserves it, and the comment-driven `note_patch_frontmatter`
   re-serializes the frontmatter instead.
5. **Verify the parse** (see below) and report the window plus what is still missing
   ("reply with a letter and it publishes at 16:30").

## Path B — release it once the user names a letter

1. `mcp__fns__note_get` the note, set `customFields[Option]` to the chosen letter and
   `status: todo`, and save the WHOLE content back over the same path. Do not use
   `note_patch_frontmatter` for this: it re-sorts the frontmatter and rewrites `parentId:`
   as `null`.
2. Re-run `board-resolve.py` and require a line for the task with no `REFUSED` reason.
3. Check the arming gate and that no OTHER `todo` task is sitting in the same window, then
   report the local clock time and its equivalent in the slot's region.

## The arming gate

`armed` lives in the state file, not on the task. With it off, the cron ticks every 15
minutes, prints nothing, and the post silently never happens — a green
`last_status: ok` means "ran", not "published".

```bash
cd ~/.hermes/profiles/miles/scripts
HERMES_HOME=~/.hermes/profiles/miles python3 x-task-poster.py --arm
```

It is GLOBAL, not per task: arming means every `todo` task that enters a window from now
on publishes. Before arming on the user's behalf, list the board and confirm no other
`todo` task is waiting in a window — otherwise their unrelated draft goes out too. Say
this out loud when reporting, and disarm (`--disarm`) or move the other tasks back to a
non-ready status if the user only wanted one post.

## Verifying without publishing

`--now` and `--json` are NOT dry runs against the live state. `--now` FORCES a window
open that the wall clock has not reached, and the live state carries `armed: true`, so a
"preview" run reaches the publisher and writes to the account for real. Probe with a
FRESH scratch state, which starts unarmed with an empty `posted` map:

```bash
S=$(mktemp -d)/s.json
cd ~/.hermes/profiles/miles/scripts
HERMES_HOME=~/.hermes/profiles/miles python3 x-task-poster.py --state "$S" --now 16:45 --json
```

Never `cp` the live state to a scratch path "to see the real plan": the copy carries
`armed: true` and the `attempts` map with it, so it publishes.

`board-resolve.py` is the cheap post-filing check — it walks every column including
Backlog and cancelled, prints each note's container/kind/option/time/target, and why a
note is REFUSED:

```bash
cd ~/.hermes/profiles/miles
HERMES_HOME=~/.hermes/profiles/miles python3 skills/social-media/x-task-poster/scripts/board-resolve.py
```

Without `HERMES_HOME=~/.hermes/profiles/miles` it looks for the poster under
`~/.hermes/scripts/` and exits with `poster not found at ...` — that message is the
missing env var, not a missing script. Every miles-side command needs the same prefix.

## Verifying a post actually published

`x-task-poster` marks the note `done` and appends `completed:`. Read the note back and,
independently, read the posted tweet with `x_read.py tweet <new id> --json` — the same
"server agrees" rule as any other write in the x-cli skill.

## Do not "de-regularise" the schedule to fix a `226`

A refusal that says the request looks automated invites a jitter fix ("the cron posts at
the same minute daily, add a 30-120s random delay"). Check the recorded publish times in
`state/x-task-poster.json` (`posted.<path>.at`) before designing it: ticks land at
varying seconds already, the slot label is a window not a send time, and a first-attempt
refusal in a fresh window is not caused by clock regularity. A timing change, if one is
wanted, is a seeded random offset INSIDE the window (per task per day), never a
sub-two-minute delay. Cadence fixes that do work are volume ones — a per-day write cap
and a minimum gap between writes. Reasoning and the quote-vs-plain lever:
`references/x-write-refusals.md`, "Before blaming the schedule".

## When a task stops publishing

A green tick and a delivered task note are different things. Work the failure from the
tick output outward, and do not diagnose it by running the poster again inside its
window — every run is a write attempt to X.

1. **Read the tick, not the job status.** `~/.hermes/profiles/miles/cron/output/
   f4397c319514/<stamp>.md` carries the publisher's verdict with the numeric code
   (`"code": 226`) and the note text. Classify by that code — table and probe in
   `references/x-write-refusals.md`.
2. **Read the state before touching it.** `state/x-task-poster.json` carries `blocked`
   (`until`, GLOBAL, and its horizon follows the refusal code: `226` -> +60 min, a FIRST
   `344`/`429` -> +45 min re-test inside the same window, a repeat `344`/`429` same UTC
   day or a `32` -> the next UTC midnight), `last_refusal` (code + UTC date, what makes a
   re-test count as a repeat and therefore escalate), and `attempts` (per task path:
   `count`, `last_at`). `blocked` is global; `attempts` is per task.
3. **A session-gate refusal is not a payload failure.** `attempts` counts refusals too,
   and `retry_gate` treats a record younger than 24h with `count >= MAX_ATTEMPTS` as
   `exhausted`. So three refusals inside one window can hold a perfectly good task past
   its NEXT window and cost a day. Drop that task's `attempts` entry (read the JSON,
   `pop` the path, write via `os.replace`) and leave the note alone — the note was
   never the problem, and the job-wide `blocked` already gives X its cooldown.
4. **Prove the note still parses** with a fresh scratch state (`--now <slot time>
   --json`, see above): container, option, `target_url` from the `Source URL` field,
   char counts, and an empty `warnings` list. That run must be unarmed and mostly
   cannot publish.
5. **Prove the parked path** by running the poster live: it should print
   `paused: X refused writes until ... — no LLM call made` and exit 0. That is the
   correct fixed behaviour, not a failure.
6. **Report the next attempt honestly**: the task's own `Time` slot on a later day,
   unless the user asks for an out-of-slot publish. Say what would have been different
   with the fix and what is still X's call.

## Publishing one immediately, when the user says so

A parked job refuses `--post` too, so an approved "post it now" is a state edit followed
by one run, in this order:

```bash
cd ~/.hermes/profiles/miles/state && cp -p x-task-poster.json x-task-poster.json.bak-$(date +%Y%m%d-%H%M)
python3 - <<'EOF'
import json
p = 'x-task-poster.json'
s = json.load(open(p))
for k in ('blocked', 'last_refusal', 'attempts'):
    s.pop(k, None)
json.dump(s, open(p, 'w'), indent=2, ensure_ascii=False)
EOF
cd ../scripts && HERMES_HOME=~/.hermes/profiles/miles python3 x-task-poster.py --ignore-time --post --executor direct
```

- `--ignore-time` is what lets a task publish outside its `Time` window; `--post` implies
  armed, so no `--arm`, and it does not imply (or bypass) `blocked`.
- `--executor direct` publishes from Python with no LLM turn — the right choice for a
  one-off out-of-window publish.
- Clear `blocked`, `last_refusal` AND that task's `attempts` entry: a stale attempt record
  delays the write by the retry gate even when the park is gone.
- `posted: verified <id> (<url>)` is the publisher's own verdict. Confirm independently
  with `x_read.py tweet <id> --json` and compare the text before reporting a URL.

## Follow-up comments are their own queue

A `## Follow-up` comment is never fired in the same turn as its post. X answers the
SECOND write of a burst with `226` (a post and its reply three seconds apart measure as
one burst), so an immediate comment fails every time and spends the retry budget on
refusals that cannot clear at that distance.

- The queue lives in state under `pending_followups`: one entry per task path with
  `attempts`, `at`, `last_error`, plus the `post_url` the comment belongs under.
- `followup_wait_left()` holds an entry until `FOLLOWUP_RETRY_GAP_MINUTES` (25) of quiet
  have elapsed since its last attempt; `FOLLOWUP_MAX_ATTEMPTS` (3) caps the lifetime, and
  `--retry-followups` overrides both by hand.
- The held line prints to STDOUT precisely so it lands in the cron record. A run log
  that says only "nothing to post — no ready task" is not evidence that no comment was
  queued: read `pending_followups` in the state file before concluding anything.
- A comment that runs out of attempts stays queued and is not retried; dropping it for
  good is a state edit (`pending_followups`), and the post's record keeps its URL either
  way.
