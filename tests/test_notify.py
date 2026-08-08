"""Tests that a broken owner-notification path cannot take down a run.

USER_CHAT_ID is operator-supplied config. If it is unset or wrong, the attempt
to report a Springer failure fails inside the except block that was handling
it -- turning a transient API blip into a crashed run.
"""

import logging

import httpx
from telegram.error import BadRequest

from paperpulse import get_current_articles


class BrokenBot:
    """A bot whose chat_id is not deliverable, e.g. USER_CHAT_ID left empty."""

    async def send_message(self, chat_id, text, **kwargs):
        raise BadRequest('Chat not found')


class WorkingBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


def failing_client(status=401):
    return httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={'status': 'Fail'})))


async def test_a_springer_failure_survives_an_undeliverable_notification(caplog):
    async with failing_client() as client:
        with caplog.at_level(logging.ERROR):
            articles = await get_current_articles(client, BrokenBot(), '2026-08-01',
                                                  '2026-08-08', 41584, 'NatureReviewsRheumatology')

    assert articles is None
    assert 'HTTP 401' in caplog.text


async def test_the_original_failure_is_still_logged_when_notifying_fails(caplog):
    """The Springer error must not be masked by the notification error."""
    async with failing_client(403) as client:
        with caplog.at_level(logging.ERROR):
            await get_current_articles(client, BrokenBot(), '2026-08-01', '2026-08-08',
                                       41568, 'NatureReviewsCancer')

    assert 'NatureReviewsCancer' in caplog.text
    assert 'HTTP 403' in caplog.text


async def test_a_working_notification_path_still_reports(caplog):
    bot = WorkingBot()
    async with failing_client(403) as client:
        await get_current_articles(client, bot, '2026-08-01', '2026-08-08',
                                   41568, 'NatureReviewsCancer')

    assert len(bot.messages) == 1
