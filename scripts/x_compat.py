"""
Compatibility shim for twikit against current x.com.

twikit 2.3.3 (latest release, unmaintained since Feb 2025) assumes an x.com
frontend and GraphQL API that no longer exist. Every breakage below is
twikit-side; the cookies are fine. Four of them are worked around here:

1. X-Client-Transaction-Id derivation is fatal for EVERY command.
   twikit scrapes the x.com home page for a `"ondemand.s":"<hash>"` webpack
   mapping, downloads that chunk and regex-es KEY_BYTE indices out of it. X no
   longer ships that mapping (`vendor.*.js` / `main.*.js` only), so
   ClientTransaction.init() raises `Couldn't get KEY_BYTE indices` on the first
   request. X accepts GraphQL requests with a missing or bogus transaction id
   (checked against UserByScreenName, Viewer and the FavoriteTweet mutation:
   normal answers for no header, random base64, and numeric values), so the
   derivation is skipped and a placeholder is sent.

2. Stale GraphQL query ids 404 retired operations.
   twikit hardcodes `queryId/operationName` pairs that X rotates; dead ones
   answer `404 {"errors":[{"code":34}]}`, which is what killed search,
   followers/following and the TweetDetail commands. refresh_query_ids()
   re-reads the pairs from X's live client bundle, cached 24h in
   .endpoint_ids.json. Called from x_utils.get_client().

3. Payload shapes moved on under twikit's parsers.
   Refreshed query ids return the newer profile model (`core`, `avatar`,
   `relationship_counts`, ... and NO `legacy` object), while
   `User.__init__`/`Tweet.__init__` subscript `legacy[...]` directly. The
   normalizers synthesize the legacy object from the new shape and pad every key
   twikit indexes with a default, so old and new payloads both parse. Without
   this, refreshing query ids regresses endpoints that work on stale ids.

4. `x_auth.py whoami`/`check` walked the retired v1.1 `account/settings.json`.
   twikit's `Client.user_id` uses it; user_id_via_viewer() takes the same id
   from the GraphQL `Viewer` query, and Client.user_id is patched to prefer it.

A 404/403 that survives a successful query-id refresh means X retired the
operation itself; nothing here can fix that.
"""

import json
import re
import time
from pathlib import Path

from twikit.tweet import Tweet
from twikit.user import User
from twikit.x_client_transaction.transaction import ClientTransaction

SCRIPT_DIR = Path(__file__).parent
CACHE_PATH = SCRIPT_DIR.parent / ".endpoint_ids.json"
CACHE_TTL = 24 * 60 * 60

# Base64url-ish placeholder, deliberately not a real transaction id.
_PLACEHOLDER_TID = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_QUERY_ID_PATTERNS = (
    re.compile(r'queryId:"([\w-]+)",operationName:"([\w-]+)"'),
    re.compile(r'operationName:"([\w-]+)",queryId:"([\w-]+)"'),
)

# legacy key -> (container in the new payload or None, key inside it)
_USER_LEGACY_MAP = {
    'created_at': ('core', 'created_at'),
    'name': ('core', 'name'),
    'screen_name': ('core', 'screen_name'),
    'description': ('profile_bio', 'description'),
    'entities': ('profile_bio', 'entities'),
    'location': ('location', 'location'),
    'profile_image_url_https': ('avatar', 'image_url'),
    'profile_banner_url': ('banner', 'image_url'),
    'verified': ('verification', 'verified'),
    'possibly_sensitive': (None, 'possibly_sensitive'),
    'url': ('website', 'url'),
    'protected': ('privacy', 'protected'),
    'followers_count': ('relationship_counts', 'followers'),
    'fast_followers_count': ('relationship_counts', 'followers'),
    'normal_followers_count': ('relationship_counts', 'followers'),
    'friends_count': ('relationship_counts', 'following'),
    'statuses_count': ('tweet_counts', 'tweets'),
    'media_count': ('tweet_counts', 'media_tweets'),
    'favourites_count': ('action_counts', 'favorites_count'),
}

# legacy keys twikit indexes that the new payload never carries: constants are
# enough to build the object. follower counts fall back to followers_count.
_USER_LEGACY_DEFAULTS = {
    'can_dm': True,
    'can_media_tag': True,
    'default_profile': False,
    'default_profile_image': False,
    'has_custom_timelines': False,
    'is_translator': False,
    'translator_type': 'none',
    'want_retweets': True,
    'listed_count': 0,
    'withheld_in_countries': [],
    'pinned_tweet_ids_str': [],
}

_TWEET_LEGACY_DEFAULTS = {
    'binding_values': {},
    'entities': {},
    'favorite_count': 0,
    'favorited': False,
    'full_text': '',
    'is_quote_status': False,
    'lang': '',
    'reply_count': 0,
    'retweet_count': 0,
    'retweeted_status_result': {},
}


def _dig(data, container, key):
    if container is None:
        return data.get(key)
    inner = data.get(container)
    return inner.get(key) if isinstance(inner, dict) else None


def _normalize_user_data(data):
    """Give twikit's User parser a `legacy` object whatever shape arrived."""
    if not isinstance(data, dict):
        return data

    legacy = data.get('legacy')
    if not isinstance(legacy, dict):
        legacy = {}
        data['legacy'] = legacy

    for key, (container, source) in _USER_LEGACY_MAP.items():
        if legacy.get(key) is None:
            value = _dig(data, container, source)
            if value is not None:
                legacy[key] = value
    for key, default in _USER_LEGACY_DEFAULTS.items():
        if legacy.get(key) is None:
            legacy[key] = default

    # Counts twikit subscripts but that the new payload may still be missing.
    followers = legacy.get('followers_count')
    for key in ('fast_followers_count', 'normal_followers_count'):
        if legacy.get(key) is None:
            legacy[key] = followers or 0
    for key in ('listed_count',):
        if legacy.get(key) is None:
            legacy[key] = 0

    # Containers twikit subscripts one level deeper than it guards.
    entities = legacy.get('entities')
    if not isinstance(entities, dict):
        entities = {}
        legacy['entities'] = entities
    for container in ('description', 'url'):
        value = entities.get(container)
        if not isinstance(value, dict):
            value = {}
            entities[container] = value
        value.setdefault('urls', [])

    # Belt and braces: no key twikit indexes may be missing.
    for key in list(_USER_LEGACY_MAP) + list(_USER_LEGACY_DEFAULTS):
        if legacy.get(key) is None:
            legacy[key] = 0 if key.endswith(('_count', '_count_str')) else None
    return data


def _normalize_tweet_data(data):
    """Pad the Tweet payload the same way (X still sends `legacy` here)."""
    if not isinstance(data, dict):
        return data
    legacy = data.get('legacy')
    if not isinstance(legacy, dict):
        legacy = {}
        data['legacy'] = legacy
    text = data.get('text')
    for key, default in _TWEET_LEGACY_DEFAULTS.items():
        if legacy.get(key) is None:
            legacy[key] = text if (key == 'full_text' and text) else default
    return data


def _iter_entry_lists(node, out):
    if isinstance(node, dict):
        entries = node.get('entries')
        if isinstance(entries, list):
            out.append(entries)
        for value in node.values():
            _iter_entry_lists(value, out)
    elif isinstance(node, list):
        for value in node:
            _iter_entry_lists(value, out)
    return out


def _normalize_tweet_detail(response):
    """Make timeline entries look the way twikit's walk expects.

    Two shape drifts, both of which KeyError inside
    `Client.get_tweet_by_id`: cursor entries now carry their token at
    `content.value` instead of `content.itemContent.value`, and some entries
    park their payload under `item` rather than `content`.
    """
    if not isinstance(response, dict):
        return response
    for entries in _iter_entry_lists(response, []):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if 'content' not in entry and isinstance(entry.get('item'), dict):
                entry['content'] = entry['item']
            content = entry.get('content')
            if isinstance(content, dict) and 'itemContent' not in content:
                items = content.get('items')
                if isinstance(items, list):
                    continue
                if 'value' in content:
                    content['itemContent'] = {
                        'value': content['value'],
                        'cursorType': content.get('cursorType') or '',
                        'entryType': content.get('entryType') or '',
                    }
    return response


def _scrape_query_ids(cookies: dict | None = None) -> dict:
    """Read every queryId/operationName pair out of X's live client bundle.

    x.com only serves the full app shell (with the client-web script tags) to a
    logged-in session; anonymous requests get a ~40KB stub, so cookies matter.
    """
    import httpx

    headers = {'User-Agent': _UA, 'Accept-Language': 'en-US,en;q=0.9'}
    pairs: dict[str, str] = {}
    with httpx.Client(headers=headers, cookies=cookies or {}, timeout=25,
                      follow_redirects=True) as client:
        html = client.get('https://x.com/').text
        srcs = set(re.findall(
            r'src="(https://abs\.twimg\.com/responsive-web/client-web/[^"]+\.js)"', html))
        wanted = [s for s in srcs if any(k in s for k in ('main.', 'vendor.', 'ondemand.'))]
        for src in wanted:
            bundle = client.get(src).text
            for index, pattern in enumerate(_QUERY_ID_PATTERNS):
                for first, second in pattern.findall(bundle):
                    if index == 0:
                        pairs[second] = first    # queryId first, operationName second
                    else:
                        pairs[first] = second    # operationName first
    return pairs


def _cached_query_ids(force: bool = False, cookies: dict | None = None) -> tuple[dict, str]:
    """Return (pairs, status). Refreshes at most once per CACHE_TTL."""
    if not force and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text())
            if time.time() - cached.get('fetched_at', 0) < CACHE_TTL:
                return cached.get('pairs', {}), 'cached'
        except (ValueError, OSError):
            pass
    try:
        pairs = _scrape_query_ids(cookies=cookies)
    except Exception as exc:                                    # network hiccup
        if CACHE_PATH.exists():
            try:
                return json.loads(CACHE_PATH.read_text()).get('pairs', {}), f'stale ({exc})'
            except (ValueError, OSError):
                pass
        return {}, f'failed ({exc})'
    if pairs:
        try:
            CACHE_PATH.write_text(json.dumps({'fetched_at': time.time(), 'pairs': pairs}))
        except OSError:
            pass
        return pairs, 'fetched'
    return {}, 'empty'


def refresh_query_ids(force: bool = False, cookies: dict | None = None,
                      verbose: bool = False) -> int:
    """Rewrite twikit's Endpoint constants with the live query ids. Returns count."""
    from twikit.client.gql import Endpoint

    pairs, status = _cached_query_ids(force=force, cookies=cookies)
    if not pairs:
        if verbose:
            print(f'⚠️  Could not refresh GraphQL query ids ({status})', flush=True)
        return 0

    updated, missing = 0, []
    for name, value in list(vars(Endpoint).items()):
        if not isinstance(value, str):
            continue
        match = re.search(r'/graphql/([\w-]+)/([\w-]+)$', value)
        if not match:
            continue
        query_id, operation = match.groups()
        live = pairs.get(operation)
        if live:
            if live != query_id:
                setattr(Endpoint, name, value.replace(query_id, live, 1))
                updated += 1
        else:
            missing.append(operation)

    if verbose:
        detail = f' ({len(missing)} absent from bundle)' if missing else ''
        print(f'🔄 GraphQL query ids: {updated} refreshed, source={status}{detail}', flush=True)
    return updated


def _viewer_url() -> str | None:
    pairs, _ = _cached_query_ids()
    query_id = pairs.get('Viewer')
    if not query_id:
        return None
    return f'https://x.com/i/api/graphql/{query_id}/Viewer'


async def user_id_via_viewer(client) -> str:
    """Authenticated user id via the GraphQL Viewer query (no v1.1 endpoint)."""
    url = _viewer_url()
    if not url:
        raise RuntimeError('Viewer query id not available')
    data, _ = await client.gql.gql_get(url, {'withCommunitiesMemberships': False}, None)
    viewer = ((data or {}).get('data') or {}).get('viewer') or {}
    result = (viewer.get('user_results') or {}).get('result') or {}
    user_id = result.get('rest_id') or result.get('id')
    if not user_id:
        raise RuntimeError('Viewer returned no user id')
    return user_id


def apply_patches() -> None:
    """Idempotently patch twikit's transaction client and payload parsers."""
    if not getattr(ClientTransaction, "_x_cli_compat_patched", False):
        async def _init(self, session, headers):
            # Truthy sentinel so Client.request() does not re-run init every call.
            self.home_page_response = object()

        def _generate_transaction_id(self, *args, **kwargs):
            return _PLACEHOLDER_TID

        ClientTransaction.init = _init
        ClientTransaction.generate_transaction_id = _generate_transaction_id
        ClientTransaction._x_cli_compat_patched = True

    if not getattr(User, "_x_cli_compat_patched", False):
        _original_user_init = User.__init__

        def _user_init(self, *args, **kwargs):
            if len(args) >= 2:
                args = (args[0], _normalize_user_data(args[1]), *args[2:])
            elif 'data' in kwargs:
                kwargs['data'] = _normalize_user_data(kwargs['data'])
            return _original_user_init(self, *args, **kwargs)

        User.__init__ = _user_init
        User._x_cli_compat_patched = True

    if not getattr(Tweet, "_x_cli_compat_patched", False):
        _original_tweet_init = Tweet.__init__

        def _tweet_init(self, *args, **kwargs):
            if len(args) >= 2:
                args = (args[0], _normalize_tweet_data(args[1]), *args[2:])
            elif 'data' in kwargs:
                kwargs['data'] = _normalize_tweet_data(kwargs['data'])
            return _original_tweet_init(self, *args, **kwargs)

        Tweet.__init__ = _tweet_init
        Tweet._x_cli_compat_patched = True

    _patch_client_user_id()
    _patch_tweet_detail()
    _patch_gql_get_post_fallback()
    _patch_get_trends()


def _find_trend_nodes(node, out=None):
    """Collect the trend items out of an ExploreSidebar timeline response.

    Current payloads put them at `item.itemContent` with snake_case metadata
    (`trend_metadata.domain_context`); older ones used camelCase
    (`trendMetadata.domainContext`). Both are accepted.
    """
    if out is None:
        out = []
    if isinstance(node, dict):
        if 'name' in node and ('trend_metadata' in node or 'trendMetadata' in node):
            out.append(node)
        for value in node.values():
            _find_trend_nodes(value, out)
    elif isinstance(node, list):
        for value in node:
            _find_trend_nodes(value, out)
    return out


class _Trend:
    """Minimal stand-in for twikit's Trend, which parses the retired v1.1 shape."""

    def __init__(self, data: dict):
        metadata = data.get('trend_metadata') or data.get('trendMetadata') or {}
        self.name = data.get('name')
        self.tweets_count = metadata.get('meta_description') or metadata.get('metaDescription')
        self.domain_context = metadata.get('domain_context') or metadata.get('domainContext')
        self.grouped_trends = [t.get('name') for t in (data.get('groupedTrends') or [])]

    def __repr__(self) -> str:
        return f'<Trend name="{self.name}">'


def _patch_get_trends() -> None:
    """Client.get_trends via GraphQL ExploreSidebar.

    twikit reads trends from the v1.1 `guide.json`, which X retired; it then
    retries itself forever and dies with `RecursionError`. The web client gets
    the same list from the ExploreSidebar GraphQL operation.
    """
    from twikit import Client
    from twikit.constants import FEATURES

    if getattr(Client, "_x_cli_compat_trends_patched", False):
        return

    async def _get_trends(self, category: str = 'trending', count: int = 20,
                          retry: bool = True, additional_request_params: dict | None = None):
        pairs, _ = _cached_query_ids()
        query_id = pairs.get('ExploreSidebar')
        if not query_id:
            raise RuntimeError('ExploreSidebar query id unavailable')
        known = ('trending', 'for-you', 'news', 'sports', 'entertainment')
        timeline_id = category.lower() if category and category.lower() in known else 'trends'
        # ExplorePage carries the full list; ExploreSidebar is a shorter fallback
        trends = []
        for operation in ('ExplorePage', 'ExploreSidebar'):
            operation_id = pairs.get(operation)
            if not operation_id:
                continue
            try:
                data, _ = await self.gql.gql_post(
                    f'https://x.com/i/api/graphql/{operation_id}/{operation}',
                    {'timeline_id': timeline_id}, FEATURES)
            except Exception:
                continue
            trends = [_Trend(node) for node in _find_trend_nodes(data)]
            if trends:
                break
        return trends[:count]

    Client.get_trends = _get_trends
    Client._x_cli_compat_trends_patched = True


def _patch_gql_get_post_fallback() -> None:
    """Retry GET-only GraphQL calls as POST.

    X moved several operations (SearchTimeline, Followers, ...) to POST-only:
    the same URL still answers `GET -> 404` with an empty body while
    `POST {variables, features, queryId}` returns the timeline. twikit calls them
    with GET, so every one of those operations looked retired.
    """
    from twikit.client.gql import GQLClient, get_query_id
    from twikit.errors import NotFound

    if getattr(GQLClient, "_x_cli_compat_post_fallback_patched", False):
        return
    _original_gql_get = GQLClient.gql_get

    async def _gql_get(self, url, variables, features=None, headers=None,
                       extra_params=None, **kwargs):
        try:
            return await _original_gql_get(self, url, variables, features,
                                           headers, extra_params, **kwargs)
        except NotFound:
            data = {'variables': variables, 'queryId': get_query_id(url)}
            if features is not None:
                data['features'] = features
            if extra_params:
                data |= extra_params
            if headers is None:
                headers = self.base._base_headers
            return await self.base.post(url, json=data, headers=headers, **kwargs)

    GQLClient.gql_get = _gql_get
    GQLClient._x_cli_compat_post_fallback_patched = True


def _patch_tweet_detail() -> None:
    """Normalize TweetDetail entries before twikit's walk over them."""
    from twikit.client.gql import GQLClient

    if getattr(GQLClient, "_x_cli_compat_tweet_detail_patched", False):
        return
    _original_tweet_detail = GQLClient.tweet_detail

    async def _tweet_detail(self, tweet_id, cursor=None, *args, **kwargs):
        response, raw = await _original_tweet_detail(self, tweet_id, cursor, *args, **kwargs)
        return _normalize_tweet_detail(response), raw

    GQLClient.tweet_detail = _tweet_detail
    GQLClient._x_cli_compat_tweet_detail_patched = True


def _patch_client_user_id() -> None:
    """Client.user_id via GraphQL Viewer, falling back to twikit's v1.1 path."""
    from twikit import Client

    if getattr(Client, "_x_cli_compat_user_id_patched", False):
        return
    _original_user_id = Client.user_id

    async def _user_id(self):
        if self._user_id is not None:
            return self._user_id
        try:
            self._user_id = await user_id_via_viewer(self)
        except Exception:
            self._user_id = await _original_user_id(self)
        return self._user_id

    Client.user_id = _user_id
    Client._x_cli_compat_user_id_patched = True


async def get_dm_inbox(client, count: int = 10) -> list[dict]:
    """Read the DM inbox.

    twikit has no inbox listing at all (`get_dm_history` needs a user_id and
    `v11.dm_conversation` needs a conversation id), so this calls the v1.1
    `dm/inbox_initial_state.json` directly — it is the one DM endpoint X still
    serves. `entries` holds every recent message; the newest per conversation is
    matched against the `conversations`/`users` maps for participants and text.
    """
    from twikit.constants import TOKEN

    cookies = client.http.cookies
    response = await client.http.get(
        'https://x.com/i/api/1.1/dm/inbox_initial_state.json',
        headers={
            'authorization': f'Bearer {TOKEN}',
            'x-csrf-token': cookies.get('ct0', ''),
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'en',
            # X 404s this v1.1 endpoint for non-browser user agents (twikit
            # sends its own); the session cookies alone are not enough.
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            ),
        },
        timeout=30,
    )
    response.raise_for_status()
    state = response.json().get('inbox_initial_state') or {}
    users = state.get('users') or {}

    def screen_name(user_id) -> str:
        entry = users.get(str(user_id)) or {}
        return entry.get('screen_name') or str(user_id)

    last_message: dict = {}
    for entry in state.get('entries') or []:
        message = entry.get('message') or {}
        data = message.get('message_data') or {}
        conversation_id = message.get('conversation_id')
        if not conversation_id or not data.get('text'):
            continue
        timestamp = int(data.get('time') or message.get('time') or 0)
        current = last_message.get(conversation_id)
        if current is None or timestamp > current['timestamp']:
            last_message[conversation_id] = {
                'text': data.get('text'),
                'timestamp': timestamp,
                'sender': screen_name(data.get('sender_id')),
            }

    conversations = []
    for conversation_id, conversation in (state.get('conversations') or {}).items():
        message = last_message.get(conversation_id, {})
        conversations.append({
            'conversation_id': conversation_id,
            'participants': [screen_name(p.get('user_id'))
                             for p in conversation.get('participants') or []],
            'sender': message.get('sender'),
            'text': message.get('text'),
            'timestamp': message.get('timestamp'),
            'muted': conversation.get('muted'),
        })

    conversations.sort(key=lambda c: c.get('timestamp') or 0, reverse=True)
    return conversations[:count]
