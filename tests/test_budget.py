"""Tests that a throttled run cannot amplify into a quota overrun.

The Springer basic plan allows 500 requests/day and 100/minute. One sweep is
~27 requests; with 3 retries each that becomes ~81, and eight such runs would
blow the daily cap. Once a journal has exhausted its retries the account is
almost certainly throttled, so the sweep stops rather than hammering the
remaining 23 journals.
"""

import httpx

import paperpulse
from paperpulse import gather_articles
from datetime import date

TODAY = date(2026, 8, 7)


class RecordingBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


def all_journals_failing(status, calls):
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'status': 'Fail'})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_throttled_sweep_stops_instead_of_hammering_every_journal(monkeypatch):
    calls = []
    bot = RecordingBot()
    async with all_journals_failing(401, calls) as client:
        await gather_articles(client, bot, TODAY)

    # One journal's worth of retries, not 24 journals' worth.
    assert len(calls) == paperpulse.MAX_ATTEMPTS
    assert len(bot.messages) == 1


async def test_a_healthy_sweep_still_visits_every_journal(monkeypatch):
    monkeypatch.setattr(paperpulse, 'JID',
                        {'NatureReviewsCancer': 41568, 'NatureReviewsGenetics': 41576})
    monkeypatch.setattr(paperpulse, 'JCHANNEL',
                        {'NatureReviewsCancer': '@a', 'NatureReviewsGenetics': '@b'})
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'records': []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await gather_articles(client, RecordingBot(), TODAY)

    assert len(calls) == 2


async def test_an_empty_journal_does_not_stop_the_sweep(monkeypatch):
    """404 means no articles, not a failure, so the sweep must continue."""
    monkeypatch.setattr(paperpulse, 'JID',
                        {'NatureReviewsCancer': 41568, 'NatureReviewsGenetics': 41576})
    monkeypatch.setattr(paperpulse, 'JCHANNEL',
                        {'NatureReviewsCancer': '@a', 'NatureReviewsGenetics': '@b'})
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={'status': 'Fail'})

    bot = RecordingBot()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await gather_articles(client, bot, TODAY)

    assert len(calls) == 2
    assert bot.messages == []
