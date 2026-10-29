# Posting through the official paid X API (vs the cookie session)

The cookie/twikit path is subject to X's browser-session gates (`226` anti-automation,
`344` write quota — see `references/x-write-refusals.md`). The official API trades those
for documented rate limits and a per-request price, and its self-serve restrictions
decide which post containers are possible at all. Read this before recommending "use the
official API for writes" — the answer is usually yes for standalone posts and comments,
and no for quotes.

## Prices (pay-per-usage, prepaid credits, no subscription tiers)

- **Post: Create — $0.015 per request.**
- **Post: Create (with URL) — $0.200 per request.** ANY URL anywhere in the text, 13x
  the base price. Embedding a quoted post's URL in the text to imitate a quote lands on
  this tier, which is the opposite of the saving it looks like.
- **Post: Create (summoned) — $0.010 per request** (a reply the original author
  summoned the account into).
- **User Interaction: Create — $0.015** (like/follow); **Interaction: Delete — $0.010**.
- **Reads — $0.005/post, $0.010/user, $0.010 followers/following**, with "Owned Reads"
  (your own posts/mentions/bookmarks/followers) at $0.001 per resource. Reads dedupe
  within a UTC day; **writes do not**. Keeping reads on x-cli/twikit therefore makes the
  write-only adoption cost nothing on the read side.
- **Media is billed on top:** each uploaded media object counts as a Post: Create in
  addition to the final `POST /2/tweets` (confirmed by X staff in the developer forum,
  still absent from the pricing page) — a 4-image post is roughly 5 × $0.015.
- Shape at ~2 posts/day: ~60 posts/month ≈ **$0.90**. The same volume with a link in
  every post: ≈ **$12/month**. The link is what costs money, not the post.

Check the live table instead of trusting a copied number:
`docs.x.com/x-api/getting-started/pricing`, with current rates in `console.x.com`.

## Self-serve (pay-per-use) restrictions — these decide the design

- **Quote posts are Enterprise-only.** `quote_tweet_id` requires an Enterprise plan and
  is not available on pay-per-use at all; developers also report 403 when quoting an
  account that has not summoned them. A quote container therefore cannot move to the
  self-serve API — the only fallbacks are the $0.20 URL-in-text post or staying on the
  cookie path.
- **Replies only when summoned:** the original post's author must have @mentioned or
  quoted the replying account. Whether replying to your OWN post satisfies this is
  **undocumented** — test it with one cheap write before building any comment feature
  on it.
- **Max 1 cashtag per post** on self-serve; more is rejected.
- **Rate limits** (user context): 200 POSTs / 15 min, 50 DELETEs / 15 min, plus 300
  requests / 3 hours including posts. Orders of magnitude above a personal posting
  cadence, which is the point.
- **Source label:** posts created through the API carry your app's name as the source
  label in the timeline; cookie-path posts do not. State this tradeoff when proposing
  the switch — it is visible on every post.

## There is no batched thread write

- The API exposes exactly two write endpoints: `POST /2/tweets` and
  `DELETE /2/tweets/:id`. A thread is N ordinary posts chained by
  `reply.in_reply_to_tweet_id`.
- The internal GraphQL surface is the same: the live client bundle exposes `CreateTweet`
  and `CreateNoteTweet` and no thread or batch operation, and the UI's batch composer
  fires one `CreateTweet` per post (with a `batch_compose` flag on each).
- Consequence: batching can never reduce write-gate pressure. The gates count
  publications, not HTTP requests — two posts in a thread are two writes however they
  are packaged. When someone proposes "send the post and its comment in one request",
  the answer is that no such request exists and it would not help if it did.

## Choosing a backend for writes

- **Standalone posts and self-replies on volume → official API.** Documented limits
  instead of `226`/`344`, pennies per post.
- **Quote containers → cookie/twikit path** (Enterprise-only on self-serve), or accept
  the $0.20 URL post, or post them plain with the source link dropped.
- **Reading → keep x-cli/twikit**; API reads are billed per resource.
- **After credentials exist, settle the unknowns with three tiny writes:** one
  standalone, one self-reply under your own post, one quote. Under $0.05 total, and it
  answers the two undocumented questions (self-reply permission, `quote_tweet_id` on
  this account) instead of guessing.
- Setup belongs to the user, not the agent: developer account, app inside a Project,
  OAuth 2.0 PKCE or OAuth 1.0a user context, credits purchased in the Developer
  Console (a one-time free-credit incentive applies). `xurl` is the official CLI and can
  drive the write path; it is a separate tool from this skill's scripts.
