"""Post new Springer Nature articles to their Telegram channels.

This runs as a cron job, not a daemon: the bot registers no update handlers
and only ever sends, so there is nothing to poll for. One invocation queries a
rolling window, posts what it has not posted before, and exits.

The run cadence doubles as pacing. Each run posts at most MAX_POSTS_PER_CHANNEL
per channel, so a burst spreads over the following runs instead of arriving all
at once, and no queue or scheduler is needed to achieve it.
"""

import argparse
import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import httpx
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import AIORateLimiter, ExtBot

from config import (
    SPRINGER_API_KEY,
    BOT_API_KEY,
    USER_CHAT_ID
)

from Vars import (
    JID,
    SPRINGER_URL,
    JCHANNEL,
    HEADERS
)

from post import article_type, preview_for, render_post
from store import FileSeenStore, SeenStore

logger = logging.getLogger(__name__)

# Journals whose channels take every article type; all others are filtered to reviews.
UNFILTERED_JOURNALS = ('NatureGenetics', 'NatureMachineIntelligence')
# Springer's `articletype:` constraint is premium-only and 403s on the basic
# plan, so the type filter runs here against the `genre` every record carries.
REVIEW_ARTICLE_TYPES = frozenset({'Review Article', 'Perspective'})
# Re-querying a window rather than a single day catches articles Springer
# indexes late. Dedup on DOI makes the overlap between runs harmless.
LOOKBACK_WINDOW = timedelta(days=7)
REQUEST_TIMEOUT = 30
# Springer caps meta/v2 at 25 records per request on the basic plan (100 on premium).
PAGE_SIZE = 25
# A journal never publishes this much in a day; the cap only stops a runaway loop
# if the API ever keeps returning full pages.
MAX_PAGES = 20
# Springer intermittently answers a valid request with 401 and then succeeds on
# an immediate retry with the same key, so 401 is treated as transient here.
RETRY_STATUSES = frozenset({401, 408, 429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
RETRY_BACKOFF = 1.0
# Per channel, per run. With runs every 3 hours this drip-feeds a busy day
# while still clearing far more than the ~4 articles/day the feeds produce.
MAX_POSTS_PER_CHANNEL = 3
DEFAULT_SEEN_PATH = Path(__file__).resolve().parent / 'seen.json'


class RedactSecret(logging.Filter):
    """Scrubs credentials from every log record passing through a logger.

    Both of this bot's secrets travel inside request URLs that httpx logs at
    INFO: Springer takes its key as a query parameter, and the Telegram token
    is a path segment of every api.telegram.org call. Relying on log levels to
    hide them is one config change away from publishing them to CI logs.
    """

    def __init__(self, *secrets: str):
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(secret in message for secret in self.secrets):
            for secret in self.secrets:
                message = message.replace(secret, '<redacted>')
            record.msg = message
            record.args = ()
        return True


def describe_http_error(error: httpx.HTTPError) -> str:
    """
    Action: summarise a request failure without echoing the credentialed URL
    :param error: exception raised by httpx while calling Springer
    :return: short description safe to log and to forward to the owner
    """
    if isinstance(error, httpx.HTTPStatusError):
        return f'HTTP {error.response.status_code}'
    return type(error).__name__


def build_query(journal_id: int, date_from: str, date_to: str) -> str:
    """
    Action: assemble the Springer `q` expression for one journal over a window
    :param journal_id: journal id from Springer Nature database (from JID dict)
    :param date_from: earliest online date to accept, formatted as YYYY-MM-DD
    :param date_to: latest online date to accept, formatted as YYYY-MM-DD
    :return: query string of space-separated (implicitly ANDed) constraints
    """
    return (f'onlinedatefrom:{date_from} onlinedateto:{date_to} '
            f'journalid:{journal_id}')


def is_wanted(article: dict, journal_name: str) -> bool:
    """
    Action: decide whether an article belongs in its journal's channel
    :param article: dictionary from API response with individual article data
    :param journal_name: journal name from JID dict
    :return: True for every type on unfiltered journals, reviews only elsewhere
    """
    if journal_name in UNFILTERED_JOURNALS:
        return True
    return article_type(article) in REVIEW_ARTICLE_TYPES


async def notify_owner(bot: ExtBot, text: str) -> None:
    """
    Action: tell the owner something went wrong, without ever raising
    :param bot: Telegram bot used to reach the owner
    :param text: message to deliver
    :return: None

    USER_CHAT_ID is operator-supplied. If it is wrong, or the bot is removed
    from that chat, the report must not replace the failure it was reporting.
    """
    try:
        await bot.send_message(chat_id=USER_CHAT_ID, text=text)
    except TelegramError as error:
        logger.error('Could not reach the owner at %r: %s', USER_CHAT_ID, error)


async def fetch_page(client: httpx.AsyncClient,
                     query: str,
                     start: int,
                     api_key: str) -> httpx.Response | None:
    """
    Action: request one page, retrying the failures that tend to be transient
    :param client: HTTP client shared by every journal in one run
    :param query: Springer `q` expression for this journal
    :param start: 1-based index of the first record to return
    :param api_key: Springer Nature API key
    :return: the response, or None when Springer reports no matching articles
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        last = attempt == MAX_ATTEMPTS
        try:
            response = await client.get(SPRINGER_URL,
                                        params={'q': query, 's': start,
                                                'p': PAGE_SIZE, 'api_key': api_key},
                                        headers=HEADERS)
        except httpx.RequestError as error:
            # Connection reset, DNS hiccup, timeout: worth another go.
            if last:
                raise
            logger.info('Springer request errored (%s), retrying (%s/%s)',
                        type(error).__name__, attempt, MAX_ATTEMPTS - 1)
            await asyncio.sleep(RETRY_BACKOFF * attempt)
            continue

        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.status_code not in RETRY_STATUSES or last:
            response.raise_for_status()
            return response
        logger.info('Springer returned %s, retrying (%s/%s)',
                    response.status_code, attempt, MAX_ATTEMPTS - 1)
        await asyncio.sleep(RETRY_BACKOFF * attempt)
    raise AssertionError('unreachable')


async def get_current_articles(client: httpx.AsyncClient,
                               bot: ExtBot,
                               date_from: str,
                               date_to: str,
                               journal_id: int,
                               journal_name: str,
                               api_key: str = SPRINGER_API_KEY) -> list[dict] | None:
    """
    Action: Send API request for Meta data to Springer Nature API Portal
    :param client: HTTP client shared by every journal in one run
    :param bot: Telegram bot used to report failures to the owner
    :param date_from: earliest online date to accept, formatted as YYYY-MM-DD
    :param date_to: latest online date to accept, formatted as YYYY-MM-DD
    :param journal_id: journal id from Springer Nature database (from JID dict)
    :param journal_name: journal name from JID dict
    :param api_key: Springer Nature API key, overridable for tests
    :return: article records, or None when the request failed after retries
    """
    query = build_query(journal_id, date_from, date_to)
    articles: list[dict] = []
    for _ in range(MAX_PAGES):
        try:
            response = await fetch_page(client, query, len(articles) + 1, api_key)
        except httpx.HTTPError as error:
            # The exception text embeds the request URL, and the API key rides
            # in the query string, so only the safe parts get reported.
            reason = describe_http_error(error)
            logger.error('Springer request failed for %s: %s', journal_name, reason)
            await notify_owner(bot, f'Springer request failed for {journal_name}: {reason}')
            return None
        # Springer answers "no matching articles" with 404, which is a normal
        # outcome for a quiet journal rather than a failure.
        if response is None:
            break
        page = response.json()['records']
        articles.extend(page)
        # Springer fills every page up to `p`, so a short page is the last one.
        if len(page) < PAGE_SIZE:
            break
    else:
        logger.warning('Hit the %s-page cap for %s; some articles were skipped',
                       MAX_PAGES, journal_name)
    return articles


async def gather_articles(client: httpx.AsyncClient,
                          bot: ExtBot,
                          today: date) -> dict[str, list[tuple[str, dict]]]:
    """
    Action: fetch every journal's window and group what belongs in each channel
    :param client: HTTP client shared by every journal in one run
    :param bot: Telegram bot used to report failures to the owner
    :param today: last day of the query window
    :return: channel handle mapped to (journal name, article) pairs, oldest first
    """
    window_start = today - LOOKBACK_WINDOW
    by_channel: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for journal_name, journal_id in JID.items():
        found = await get_current_articles(client, bot,
                                           date_from=window_start.isoformat(),
                                           date_to=today.isoformat(),
                                           journal_id=journal_id,
                                           journal_name=journal_name)
        if found is None:
            # Retries are already exhausted, so the account is throttled or the
            # key is bad. The other 23 journals would fail the same way, and
            # each costs three more requests against a 500/day quota.
            logger.error('Stopping the sweep after %s failed', journal_name)
            break
        for article in found:
            if is_wanted(article, journal_name):
                by_channel[JCHANNEL[journal_name]].append((journal_name, article))
    for entries in by_channel.values():
        entries.sort(key=lambda entry: entry[1].get('onlineDate', ''))
    return dict(by_channel)


async def post_new_articles(bot: ExtBot,
                            store: SeenStore,
                            by_channel: dict[str, list[tuple[str, dict]]],
                            today: date,
                            limit: int = MAX_POSTS_PER_CHANNEL) -> list[str]:
    """
    Action: post articles not seen before, at most `limit` per channel
    :param bot: Telegram bot used to send the posts
    :param store: memory of DOIs already posted
    :param by_channel: channel handle mapped to (journal name, article) pairs
    :param today: date recorded against anything posted
    :param limit: how many articles one channel may receive in this run
    :return: DOIs that were posted (or permanently rejected) this run
    """
    settled: list[str] = []
    for channel, entries in by_channel.items():
        fresh = set(await store.unseen([article['doi'] for _, article in entries]))
        queued = [entry for entry in entries if entry[1]['doi'] in fresh][:limit]
        for journal_name, article in queued:
            try:
                await bot.send_message(chat_id=channel,
                                       text=render_post(article, journal_name, today),
                                       parse_mode=ParseMode.HTML,
                                       link_preview_options=preview_for(article))
            except BadRequest as error:
                # Telegram rejected the message itself, so retrying cannot help.
                # Record it as settled and tell the owner, rather than looping.
                logger.error('%s rejected %s: %s', channel, article['doi'], error)
                await bot.send_message(chat_id=USER_CHAT_ID,
                                       text=f'Could not post {article["doi"]} to {channel}: {error}')
                settled.append(article['doi'])
                continue
            except TelegramError as error:
                # Transient. Leaving it unrecorded means the next run retries.
                logger.warning('Delivery to %s failed, will retry: %s', channel, error)
                continue
            settled.append(article['doi'])
        logger.info('%s: %s queued, %s sent', channel, len(fresh), len(queued))
    await store.remember(settled, today)
    return settled


async def run(store: SeenStore, today: date, limit: int, seed: bool) -> None:
    """
    Action: perform one pass over every journal
    :param store: memory of DOIs already posted
    :param today: last day of the query window
    :param limit: how many articles one channel may receive in this run
    :param seed: record everything currently in the window without posting it
    :return: None
    """
    bot = ExtBot(BOT_API_KEY, rate_limiter=AIORateLimiter())
    async with bot, httpx.AsyncClient(timeout=REQUEST_TIMEOUT,
                                      follow_redirects=True) as client:
        by_channel = await gather_articles(client, bot, today)
        if seed:
            dois = [article['doi'] for entries in by_channel.values()
                    for _, article in entries]
            await store.remember(dois, today)
            logger.info('Seeded %s article(s) without posting', len(dois))
            return
        posted = await post_new_articles(bot, store, by_channel, today, limit)
        logger.info('Posted %s article(s)', len(posted))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Action: read command line options
    :param argv: argument list, defaulting to sys.argv
    :return: parsed options
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--seen', type=Path, default=DEFAULT_SEEN_PATH,
                        help='path to the posted-DOI store')
    parser.add_argument('--limit', type=int, default=MAX_POSTS_PER_CHANNEL,
                        help='maximum posts per channel for this run')
    parser.add_argument('--seed', action='store_true',
                        help='record the current window as posted, without posting. '
                             'Run this once against an empty store, or the first '
                             'real run posts a week of backlog at once')
    return parser.parse_args(argv)


def main() -> None:
    """
    Action: Run bot.
    :return: None
    """
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactSecret(SPRINGER_API_KEY, BOT_API_KEY))

    args = parse_args()
    asyncio.run(run(store=FileSeenStore(args.seen),
                    today=date.today(),
                    limit=args.limit,
                    seed=args.seed))


if __name__ == '__main__':
    main()
