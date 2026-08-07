"""Tests for which articles reach which channel.

A journal can feed several channels with different filters: Nature goes to
@NatureMain unfiltered and to @NatureReviewsLife as reviews only. So the
"accepts every article type" rule belongs to the channel, not the journal.
"""

from datetime import date

import httpx
import pytest

import SpringerNatureBot
from SpringerNatureBot import channels_for, gather_articles, is_wanted, limit_for
from Vars import JCHANNEL, JID

TODAY = date(2026, 8, 7)


def article(genre):
    return {'genre': list(genre), 'doi': f'10.1038/{"-".join(genre)}',
            'title': 't', 'abstract': '', 'onlineDate': '2026-08-05',
            'openaccess': 'false',
            'url': [{'format': 'html', 'value': 'https://example.org'}]}


class RecordingBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


def test_every_journal_routes_to_at_least_one_channel():
    assert set(JID) == set(JCHANNEL)
    for journal, channels in JCHANNEL.items():
        assert channels_for(journal), journal


def test_nature_feeds_both_the_main_and_the_reviews_channel():
    assert set(channels_for('Nature')) == {'@NatureMain', '@NatureReviewsLife'}


@pytest.mark.parametrize('genre', [
    ('OriginalPaper', 'Article'), ('News', 'News'), ('News', 'Career Column'),
    ('ReviewPaper', 'Review Article'),
])
def test_the_main_channel_takes_every_article_type(genre):
    assert is_wanted(article(genre), '@NatureMain')


def test_the_reviews_channel_takes_only_reviews_and_perspectives():
    assert is_wanted(article(('ReviewPaper', 'Review Article')), '@NatureReviewsLife')
    assert is_wanted(article(('ReviewPaper', 'Perspective')), '@NatureReviewsLife')
    assert not is_wanted(article(('OriginalPaper', 'Article')), '@NatureReviewsLife')
    assert not is_wanted(article(('News', 'News')), '@NatureReviewsLife')


@pytest.mark.parametrize('channel', ['@NatureMain', '@NatureGenetics',
                                     '@NatureReviewsLife'])
def test_author_corrections_are_never_posted_anywhere(channel):
    """Corrections are noise on every channel, including the unfiltered ones."""
    assert not is_wanted(article(('OriginalPaper', 'Author Correction')), channel)


def test_the_main_channel_gets_a_higher_per_run_limit():
    """Nature publishes ~12/day, far more than the review journals."""
    assert limit_for('@NatureMain') > limit_for('@NatureReviewsLife')


def test_an_unlisted_channel_falls_back_to_the_default_limit():
    assert limit_for('@NatureReviewsClinical') == SpringerNatureBot.MAX_POSTS_PER_CHANNEL


async def test_one_journal_fans_out_to_both_its_channels(monkeypatch):
    monkeypatch.setattr(SpringerNatureBot, 'JID', {'Nature': 41586})
    monkeypatch.setattr(SpringerNatureBot, 'JCHANNEL',
                        {'Nature': ('@NatureMain', '@NatureReviewsLife')})
    records = [article(('OriginalPaper', 'Article')),
               article(('ReviewPaper', 'Review Article')),
               article(('OriginalPaper', 'Author Correction'))]

    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'records': records})))
    async with client:
        by_channel = await gather_articles(client, RecordingBot(), TODAY)

    # Main takes the paper and the review, but not the correction.
    assert len(by_channel['@NatureMain']) == 2
    # Reviews takes only the review.
    assert len(by_channel['@NatureReviewsLife']) == 1


async def test_a_single_channel_journal_still_works(monkeypatch):
    monkeypatch.setattr(SpringerNatureBot, 'JID', {'NatureReviewsCancer': 41568})
    monkeypatch.setattr(SpringerNatureBot, 'JCHANNEL',
                        {'NatureReviewsCancer': ('@NatureReviewsClinical',)})
    records = [article(('ReviewPaper', 'Review Article'))]

    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'records': records})))
    async with client:
        by_channel = await gather_articles(client, RecordingBot(), TODAY)

    assert len(by_channel['@NatureReviewsClinical']) == 1
