# Repairing twikit drift against live x.com

`x_compat.py` is the only file that should ever grow when X changes. Work in this
order: identify which layer moved, probe it raw, then either normalize the payload
for twikit's parser or write a thin replacement on `Client`.

## 1. Identify the layer

| Symptom | Layer | Where to look |
| --- | --- | --- |
| `Couldn't get KEY_BYTE indices` on EVERY command | client-transaction-id | already patched: derivation skipped under a placeholder id |
| GraphQL `404 {"errors":[{"code":34}]}` | stale query id | `refresh_query_ids()` / `.endpoint_ids.json` |
| GraphQL 404 that survives a fresh query id | retired operation | find the replacement op in the bundle (step 2) |
| `KeyError: 'legacy'` / `'urls'` / missing field on a parsed object | payload shape | normalizers in `x_compat.py` |
| `404` on a `/i/api/1.1/...` path with valid cookies | user agent or retirement | step 4 |
| `RecursionError`, infinite retry | twikit retrying a dead endpoint | read the twikit method; it usually recurses when the response has no entries |
| A `Result`/attribute `AttributeError` in a script | script bug, not drift | twikit's API changed; check the class in `.venv/.../twikit/` |

## 2. Read the live operation ids out of X's client bundle

The bundle is the source of truth for `queryId`/`operationName` pairs:

```python
import re, httpx
html = httpx.get("https://x.com/", headers={"User-Agent": "Mozilla/5.0"}).text
bundle_url = re.search(r'(https://abs\.twimg\.com/[^"]*main\.[a-z0-9]+\.js)', html).group(1)
bundle = httpx.get(bundle_url).text
pairs = dict((op, qid) for qid, op in re.findall(r'queryId:"([\w-]+)",operationName:"([\w-]+)"', bundle))
print({op: qid for op, qid in pairs.items() if 'Trend' in op or 'Explore' in op})
```

Then grep the bundle for `operationName:"..."` to find an operation whose *name*
matches the data you want, instead of guessing at the old endpoint's replacement.

## 3. Probe the candidate operation raw, before writing any code

Sending the request yourself separates "X changed" from "twikit misparses":

```python
from twikit.constants import TOKEN
variables = {"timeline_id": "trends"}
features = {k: FEATURES[k] for k in FEATURES}  # from twikit.constants
headers = {
    "authorization": f"Bearer {TOKEN}",
    "x-csrf-token": cookies["ct0"],
    "x-twitter-auth-type": "OAuth2Session",
    "x-twitter-active-user": "yes",
    "x-twitter-client-language": "en",
    "content-type": "application/json",
}
httpx.post(f"https://x.com/i/api/graphql/{query_id}/{operation}",
           headers=headers, cookies=cookies,
           json={"variables": variables, "features": features, "queryId": query_id})
```

- Try GET **and** POST: some operations answer `404` to GET and `200` to POST with
  identical payloads (`SearchTimeline`). The shim already retries a GraphQL GET as
  POST on `NotFound`, so prefer adding operations to the existing fallback path.
- A `200` with a plausible body means the operation is live and twikit's parser or a
  stale id was the problem. A `400` naming a missing variable means your `variables`
  dict is wrong, which is progress, not a wall.
- Do NOT chase a real `X-Client-Transaction-Id`. X accepts the placeholder on the
  operations in use, including mutations; the derivation inputs are gone from the
  bundle.

## 4. Locating a moved field

Don't guess the new JSON path. Walk it:

```python
def walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("name", "trend_metadata", "trendMetadata"):
                print(path + "/" + key, type(value).__name__, str(value)[:120])
            walk(value, path + "/" + key)
    elif isinstance(node, list):
        for i, value in enumerate(node[:3]):
            walk(value, path + f"[{i}]")
```

X renames keys as it pleases: `trendMetadata` became `trend_metadata`, and
`domainContext` became `domain_context`, in the same frontend that kept
`itemContent` and `entryId`. Match the *content* of a value, not the key you expect.

## 5. Then choose: normalize or reimplement

- **Normalize** when twikit's class is right and only subscripts fail (synthesize the
  missing `legacy` object, pad indexed keys). Cheapest, keeps every twikit feature.
- **Reimplement on `Client`** when twikit's approach is dead: swap the endpoint
  (`_patch_get_trends`), drain a `Result` the script misuses, or fetch a v1.1 path
  directly (`get_dm_inbox`). Keep the same method name so the CLI scripts stay valid.
- A v1.1 path that still returns `200` to a hand-rolled request but `404`s through
  twikit is usually a **user-agent** rejection. Send a browser `User-Agent` and retry
  before concluding the endpoint is retired.

## 6. Verify the whole surface, not just the command you fixed

Shared changes regress other commands. A global query-id refresh produced the modern
payload shape and broke every endpoint that still returned legacy-shaped data, until
the normalizers padded both. After any edit to `x_compat.py`, `x_utils.py`, or a
script's argument handling:

```bash
.venv/bin/python scripts/smoke_test.py --tweet <id>
```

That runs every command and reports PASS/FAIL per command. A fix is not done until
the whole list is green.
