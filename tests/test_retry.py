"""Tests for retrying transient Springer failures.

The API intermittently answers a valid request with 401 and succeeds on an
immediate retry with the same key. Without retries a blip costs the journal a
whole run and sends the owner a false alarm.
"""

import httpx

from SpringerNatureBot import MAX_ATTEMPTS, get_current_articles


class RecordingBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


def client_replaying(statuses, calls):
    """Answer with each status in turn, then 200 with one record."""

    def handler(request):
        calls.append(request)
        if len(calls) <= len(statuses):
            return httpx.Response(statuses[len(calls) - 1], json={'status': 'Fail'})
        return httpx.Response(200, json={'records': [{'doi': '10.1038/a'}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def fetch(client, bot):
    return await get_current_articles(client, bot, '2026-08-01', '2026-08-08',
                                      41584, 'NatureReviewsRheumatology')


async def test_a_transient_401_is_retried_and_succeeds():
    calls, bot = [], RecordingBot()
    async with client_replaying([401], calls) as client:
        articles = await fetch(client, bot)

    assert len(articles) == 1
    assert len(calls) == 2
    assert bot.messages == [], 'a recovered blip must not alarm the owner'


async def test_server_errors_and_rate_limits_are_retried():
    for status in (429, 500, 502, 503):
        calls, bot = [], RecordingBot()
        async with client_replaying([status], calls) as client:
            articles = await fetch(client, bot)
        assert len(articles) == 1, status
        assert bot.messages == [], status


async def test_network_errors_are_retried():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError('connection reset')
        return httpx.Response(200, json={'records': [{'doi': '10.1038/a'}]})

    bot = RecordingBot()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        articles = await fetch(client, bot)

    assert len(articles) == 1
    assert bot.messages == []


async def test_retries_are_bounded_and_then_reported():
    calls, bot = [], RecordingBot()
    async with client_replaying([401] * 10, calls) as client:
        articles = await fetch(client, bot)

    assert articles is None
    assert len(calls) == MAX_ATTEMPTS
    assert len(bot.messages) == 1


async def test_a_404_is_not_retried_because_it_means_no_results():
    calls, bot = [], RecordingBot()
    async with client_replaying([404] * 10, calls) as client:
        articles = await fetch(client, bot)

    assert articles == []
    assert len(calls) == 1
    assert bot.messages == []


async def test_a_403_is_not_retried_because_the_plan_will_not_change():
    """Premium-only constraints 403 permanently; retrying just wastes quota."""
    calls, bot = [], RecordingBot()
    async with client_replaying([403] * 10, calls) as client:
        articles = await fetch(client, bot)

    assert articles is None
    assert len(calls) == 1
    assert len(bot.messages) == 1
