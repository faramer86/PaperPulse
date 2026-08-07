"""Invariants for the journal/channel routing tables."""

from Vars import JCHANNEL, JID, SPRINGER_URL


def test_api_is_reached_over_tls():
    """The API key travels in the query string, so plain HTTP leaks it."""
    assert SPRINGER_URL.startswith('https://')


def test_every_journal_has_a_channel():
    assert set(JID) == set(JCHANNEL)


def test_every_channel_is_a_telegram_handle():
    for journal_name, channel in JCHANNEL.items():
        assert channel.startswith('@'), journal_name
