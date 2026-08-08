"""Tests for keeping the Springer API key out of logs.

Springer takes the key as a query parameter, and httpx logs the full request
URL at INFO. Suppressing httpx's logger works until someone raises the level,
so the key is scrubbed at the handler instead.
"""

import logging

from paperpulse import RedactSecret

SECRET = 'b58d74681d7d68d660989066a0160881'
URL = f'https://api.springernature.com/meta/v2/json?q=journalid:41568&api_key={SECRET}'


def emit(caplog, logger_name, msg, *args):
    logger = logging.getLogger(logger_name)
    logger.addFilter(RedactSecret(SECRET))
    with caplog.at_level(logging.INFO, logger=logger_name):
        logger.info(msg, *args)
    return caplog.text


def test_key_is_scrubbed_from_a_plain_message(caplog):
    assert SECRET not in emit(caplog, 'plain', f'GET {URL}')


def test_key_is_scrubbed_when_it_arrives_through_lazy_args(caplog):
    """httpx logs 'HTTP Request: %s %s' with the URL as an argument."""
    text = emit(caplog, 'lazy', 'HTTP Request: %s %s "%s"', 'GET', URL, '200 OK')

    assert SECRET not in text
    assert 'HTTP Request: GET' in text


def test_the_rest_of_the_message_survives(caplog):
    text = emit(caplog, 'kept', 'HTTP Request: %s %s', 'GET', URL)

    assert 'journalid:41568' in text
    assert '<redacted>' in text


def test_records_without_the_secret_are_untouched(caplog):
    text = emit(caplog, 'clean', 'Posted %s article(s)', 7)

    assert 'Posted 7 article(s)' in text


def test_the_bot_token_is_scrubbed_too(caplog):
    """httpx logs POST https://api.telegram.org/bot<TOKEN>/sendMessage at INFO.
    In a public repo that URL is a channel-takeover credential in plain sight."""
    token = '1808005838:AAFqWrGmuUd0P8HbhOnf02w5csRtqLIrMDA'
    logger = logging.getLogger('tokens')
    logger.addFilter(RedactSecret(SECRET, token))

    with caplog.at_level(logging.INFO, logger='tokens'):
        logger.info('HTTP Request: %s %s "%s"', 'POST',
                    f'https://api.telegram.org/bot{token}/sendMessage', '200 OK')

    assert token not in caplog.text
    assert token.split(':')[1] not in caplog.text
    assert 'api.telegram.org' in caplog.text


def test_both_secrets_are_scrubbed_from_one_record(caplog):
    token = 'bot-token-value'
    logger = logging.getLogger('both')
    logger.addFilter(RedactSecret(SECRET, token))

    with caplog.at_level(logging.INFO, logger='both'):
        logger.info('springer=%s telegram=%s', SECRET, token)

    assert SECRET not in caplog.text
    assert token not in caplog.text


def test_an_empty_secret_never_redacts_everything(caplog):
    logger = logging.getLogger('empty')
    logger.addFilter(RedactSecret(''))
    with caplog.at_level(logging.INFO, logger='empty'):
        logger.info('Posted 3 article(s)')

    assert 'Posted 3 article(s)' in caplog.text
    assert '<redacted>' not in caplog.text
