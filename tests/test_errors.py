"""Tests for how the fetch path reports API failures."""

import httpx

from paperpulse import get_current_articles


class RecordingBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


def client_returning(status, payload=None):
    def handler(request):
        return httpx.Response(status, json=payload or {'status': 'Fail'})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_404_means_no_matching_articles_not_a_failure():
    """Springer answers an empty result set with 404 'No data was found'.
    Treating it as an error DMs the owner every run for quiet journals."""
    context = RecordingBot()
    async with client_returning(404, {'status': 'Fail',
                                      'message': 'No data was found for the given query.'}) as client:
        articles = await get_current_articles(client, context, '2026-08-01', '2026-08-08',
                                              41574, 'NatureReviewsEndocrinology')

    assert articles == []
    assert context.messages == []


async def test_real_failures_are_still_reported():
    context = RecordingBot()
    async with client_returning(403) as client:
        articles = await get_current_articles(client, context, '2026-08-01', '2026-08-08',
                                              41568, 'NatureReviewsCancer')

    assert articles is None, 'None signals a hard failure so the sweep can stop'
    assert len(context.messages) == 1


async def test_the_api_key_never_reaches_the_logs_or_the_owner(caplog):
    """httpx puts the full request URL in its error string, and the key rides
    in the query string, so the raw exception must never be interpolated."""
    secret = 'sup3rs3cr3tapikeyvalue'

    def handler(request):
        assert secret in str(request.url)
        return httpx.Response(403, json={'status': 'Fail'})

    context = RecordingBot()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with caplog.at_level('ERROR'):
            await get_current_articles(client, context, '2026-08-01', '2026-08-08',
                                       41568, 'NatureReviewsCancer', api_key=secret)

    assert secret not in caplog.text
    assert all(secret not in text for _, text in context.messages)
