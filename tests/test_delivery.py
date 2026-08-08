"""Tests for how the bot is configured to talk to Telegram.

Every post carries a link preview, so Telegram fetches the nature.com page and
its og:image before answering. PTB's default 5s read/write timeout is not
enough for that, and a timeout is ambiguous: the message may already have been
delivered, so a retry can duplicate it in the channel.
"""

from telegram.request import HTTPXRequest

import paperpulse
from paperpulse import build_bot


def test_timeouts_exceed_the_library_default():
    """5s is PTB's default and is too short when Telegram must fetch a preview."""
    default = HTTPXRequest()._client.timeout

    assert default.read == 5.0, 'PTB default changed; revisit these constants'
    assert paperpulse.READ_TIMEOUT > default.read
    assert paperpulse.WRITE_TIMEOUT > default.write


def test_the_bot_is_built_with_those_timeouts():
    """Read the effective httpx timeouts, since PTB exposes only read_timeout."""
    timeout = build_bot().request._client.timeout

    assert timeout.read == paperpulse.READ_TIMEOUT
    assert timeout.write == paperpulse.WRITE_TIMEOUT
    assert timeout.connect == paperpulse.CONNECT_TIMEOUT


def test_the_bot_still_has_a_rate_limiter():
    """Posting 8 articles to one channel in a burst needs flood control."""
    assert build_bot().rate_limiter is not None
