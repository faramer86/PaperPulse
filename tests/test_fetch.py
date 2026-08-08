"""Tests for fetching article records from the Springer Nature API."""

import httpx

import paperpulse
from paperpulse import PAGE_SIZE, get_current_articles


class RecordingBot:
    """Stands in for telegram.Bot and records what the job tried to send."""

    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


def records(count, offset=0):
    return [{'title': f'Article {offset + n}', 'abstract': 'x',
             'url': [{'value': 'https://example.org'}]} for n in range(count)]


def client_returning(pages, calls):
    """Build a client whose successive requests return the given pages."""

    def handler(request):
        calls.append(dict(request.url.params))
        page = pages[len(calls) - 1] if len(calls) <= len(pages) else []
        return httpx.Response(200, json={'records': page})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_requests_the_maximum_page_size():
    """Springer defaults to 10 records per request; the old code never set p."""
    calls = []
    async with client_returning([records(3)], calls) as client:
        await get_current_articles(client, RecordingBot(), '2026-08-01', '2026-08-08', 41568,
                                   'NatureReviewsCancer')

    assert calls[0]['p'] == str(PAGE_SIZE)
    assert calls[0]['s'] == '1'


async def test_follows_pagination_until_a_short_page_arrives():
    calls = []
    pages = [records(PAGE_SIZE), records(PAGE_SIZE, offset=PAGE_SIZE), records(4)]
    async with client_returning(pages, calls) as client:
        articles = await get_current_articles(client, RecordingBot(), '2026-08-01', '2026-08-08',
                                              41568, 'NatureReviewsCancer')

    assert len(articles) == PAGE_SIZE * 2 + 4
    assert [call['s'] for call in calls] == ['1', str(PAGE_SIZE + 1), str(PAGE_SIZE * 2 + 1)]


async def test_single_short_page_costs_exactly_one_request():
    calls = []
    async with client_returning([records(2)], calls) as client:
        articles = await get_current_articles(client, RecordingBot(), '2026-08-01', '2026-08-08',
                                              41568, 'NatureReviewsCancer')

    assert len(articles) == 2
    assert len(calls) == 1


async def test_empty_result_set_costs_exactly_one_request():
    calls = []
    async with client_returning([[]], calls) as client:
        articles = await get_current_articles(client, RecordingBot(), '2026-08-01', '2026-08-08',
                                              41568, 'NatureReviewsCancer')

    assert articles == []
    assert len(calls) == 1


async def test_pagination_is_capped_so_a_stuck_api_cannot_loop_forever():
    calls = []
    always_full = [records(PAGE_SIZE)] * (paperpulse.MAX_PAGES + 5)
    async with client_returning(always_full, calls) as client:
        await get_current_articles(client, RecordingBot(), '2026-08-01', '2026-08-08', 41568,
                                   'NatureReviewsCancer')

    assert len(calls) == paperpulse.MAX_PAGES


async def test_http_error_notifies_the_owner_and_reports_a_hard_failure():
    def handler(request):
        return httpx.Response(401, json={'status': 'Fail'})

    context = RecordingBot()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        articles = await get_current_articles(client, context, '2026-08-01', '2026-08-08', 41568,
                                              'NatureReviewsCancer')

    assert articles is None
    assert len(context.messages) == 1
    assert 'NatureReviewsCancer' in context.messages[0][1]
