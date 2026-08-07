"""Tests for one pass of the cron job: gather, filter, dedupe, pace, post."""

from datetime import date

import httpx
import pytest
from telegram.error import BadRequest, TimedOut

import SpringerNatureBot
from SpringerNatureBot import USER_CHAT_ID, gather_articles, post_new_articles
from store import FileSeenStore

TODAY = date(2026, 8, 7)


class RecordingBot:
    """Stands in for telegram.Bot and records what the run tried to send."""

    def __init__(self, failure=None):
        self.messages = []
        self.failure = failure

    async def send_message(self, chat_id, text, **kwargs):
        if self.failure and chat_id != USER_CHAT_ID:
            raise self.failure
        self.messages.append((chat_id, text))

    def to(self, chat_id):
        return [text for chat, text in self.messages if chat == chat_id]


def record(n, genre=('ReviewPaper', 'Review Article'), online='2026-08-05'):
    return {'title': f'Article {n}', 'abstract': 'Body.', 'genre': list(genre),
            'creators': [{'creator': 'Smith, Jane'}], 'onlineDate': online,
            'publicationName': 'Nature Reviews Cancer', 'openaccess': 'false',
            'doi': f'10.1038/s41568-025-{n:05}',
            'url': [{'format': 'html', 'value': f'https://www.nature.com/articles/{n}'}]}


def one_journal(monkeypatch, records):
    monkeypatch.setattr(SpringerNatureBot, 'JID', {'NatureReviewsCancer': 41568})
    monkeypatch.setattr(SpringerNatureBot, 'JCHANNEL', {'NatureReviewsCancer': ('@channel',)})
    return httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'records': records})))


@pytest.fixture
def store(tmp_path):
    return FileSeenStore(tmp_path / 'seen.json')


async def test_only_review_genres_reach_a_review_channel(monkeypatch):
    """The basic plan cannot filter by type, so the run must."""
    mixed = [record(1, ('ReviewPaper', 'Review Article')),
             record(2, ('BriefCommunication', 'Research Highlight')),
             record(3, ('News', 'News And Views')),
             record(4, ('ReviewPaper', 'Perspective'))]
    bot = RecordingBot()
    async with one_journal(monkeypatch, mixed) as client:
        by_channel = await gather_articles(client, bot, TODAY)

    assert [article['doi'] for _, article in by_channel['@channel']] == \
        ['10.1038/s41568-025-00001', '10.1038/s41568-025-00004']


async def test_articles_are_ordered_oldest_first(monkeypatch):
    out_of_order = [record(1, online='2026-08-06'), record(2, online='2026-08-02'),
                    record(3, online='2026-08-04')]
    async with one_journal(monkeypatch, out_of_order) as client:
        by_channel = await gather_articles(client, RecordingBot(), TODAY)

    assert [a['onlineDate'] for _, a in by_channel['@channel']] == \
        ['2026-08-02', '2026-08-04', '2026-08-06']


async def test_a_run_posts_at_most_the_per_channel_limit(store):
    by_channel = {'@channel': [('NatureReviewsCancer', record(n)) for n in range(10)]}
    bot = RecordingBot()

    posted = await post_new_articles(bot, store, by_channel, TODAY, limit=3)

    assert len(posted) == 3
    assert len(bot.to('@channel')) == 3


async def test_the_next_run_continues_where_the_last_one_stopped(store):
    by_channel = {'@channel': [('NatureReviewsCancer', record(n)) for n in range(10)]}

    first = await post_new_articles(RecordingBot(), store, by_channel, TODAY, limit=3)
    second = await post_new_articles(RecordingBot(), store, by_channel, TODAY, limit=3)

    assert set(first).isdisjoint(second)
    assert len(second) == 3


async def test_an_article_is_never_posted_twice(store):
    by_channel = {'@channel': [('NatureReviewsCancer', record(1))]}

    await post_new_articles(RecordingBot(), store, by_channel, TODAY, limit=3)
    bot = RecordingBot()
    await post_new_articles(bot, store, by_channel, TODAY, limit=3)

    assert bot.to('@channel') == []


async def test_a_rejected_message_is_not_retried_forever(store):
    """A BadRequest means Telegram refused the content; retrying cannot fix it."""
    by_channel = {'@channel': [('NatureReviewsCancer', record(1))]}
    bot = RecordingBot(failure=BadRequest('Can\'t parse entities'))

    posted = await post_new_articles(bot, store, by_channel, TODAY, limit=3)

    assert posted == ['10.1038/s41568-025-00001']
    assert len(bot.to(USER_CHAT_ID)) == 1
    assert await store.unseen(['10.1038/s41568-025-00001']) == []


async def test_a_transient_failure_is_left_for_the_next_run(store):
    by_channel = {'@channel': [('NatureReviewsCancer', record(1))]}

    posted = await post_new_articles(RecordingBot(failure=TimedOut()), store,
                                     by_channel, TODAY, limit=3)

    assert posted == []
    assert await store.unseen(['10.1038/s41568-025-00001']) == ['10.1038/s41568-025-00001']


async def test_nothing_new_sends_nothing(store):
    bot = RecordingBot()

    await post_new_articles(bot, store, {}, TODAY, limit=3)

    assert bot.messages == []
