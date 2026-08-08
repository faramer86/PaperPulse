"""Tests for the Springer query and the client-side article-type filter.

The Basic plan rejects `articletype:` with HTTP 403 (premium only), so type
filtering happens in Python against the `genre` field every record carries.
"""

import pytest

from paperpulse import build_query, is_wanted


def test_query_uses_a_date_range_not_a_single_day():
    """Journals publish a handful of items per month, so a single-day query is
    empty on most days and misses anything Springer indexes late."""
    query = build_query(journal_id=41568, date_from='2026-08-01', date_to='2026-08-08')

    assert 'onlinedatefrom:2026-08-01' in query
    assert 'onlinedateto:2026-08-08' in query
    assert 'onlinedate:' not in query.replace('onlinedatefrom:', '').replace('onlinedateto:', '')


def test_query_stays_within_the_basic_plan():
    """articletype: is a premium constraint and 403s on this account."""
    query = build_query(journal_id=41568, date_from='2026-08-01', date_to='2026-08-08')

    assert 'articletype:' not in query


def test_query_constraints_are_space_separated_and_untrimmed():
    query = build_query(journal_id=41568, date_from='2026-08-01', date_to='2026-08-08')

    assert query == 'onlinedatefrom:2026-08-01 onlinedateto:2026-08-08 journalid:41568'


def article_with(genre):
    return {'genre': genre}


@pytest.mark.parametrize('genre', [
    ['ReviewPaper', 'Review Article'],
    ['ReviewPaper', 'Perspective'],
])
def test_review_channels_accept_reviews_and_perspectives(genre):
    assert is_wanted(article_with(genre), '@NatureReviewsClinical')


@pytest.mark.parametrize('genre', [
    ['BriefCommunication', 'Journal Club'],
    ['BriefCommunication', 'Research Highlight'],
    ['BriefCommunication', 'Tools of the Trade'],
    ['News', 'News And Views'],
    ['News', 'Correspondence'],
    ['News', 'World View'],
    ['EditorialNotes', 'Editorial'],
    ['OriginalPaper', 'Article'],
])
def test_review_channels_reject_everything_else(genre):
    """These genres are all real values observed on Nature Reviews journals."""
    assert not is_wanted(article_with(genre), '@NatureReviewsClinical')


@pytest.mark.parametrize('genre', [
    ['OriginalPaper', 'Article'],
    ['News', 'Editorial'],
    ['ReviewPaper', 'Review Article'],
])
def test_unfiltered_channels_accept_every_type(genre):
    assert is_wanted(article_with(genre), '@NatureGenetics')
    assert is_wanted(article_with(genre), '@NatureMachineIntelligence')


def test_article_with_no_genre_is_rejected_from_review_channels():
    assert not is_wanted({'genre': []}, '@NatureReviewsClinical')
    assert not is_wanted({}, '@NatureReviewsClinical')
