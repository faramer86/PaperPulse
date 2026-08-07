import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# config.py holds deployment secrets and is gitignored, so it is absent on a
# fresh clone and in CI. Stub it so the tests exercise the bot's own logic.
if not (Path(__file__).resolve().parent.parent / 'config.py').exists():
    stub = types.ModuleType('config')
    stub.SPRINGER_API_KEY = 'test-springer-key'
    stub.BOT_API_KEY = 'test-bot-token'
    stub.USER_CHAT_ID = 0
    sys.modules['config'] = stub

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch):
    """Exercise the retry logic without sleeping through it."""
    import SpringerNatureBot

    monkeypatch.setattr(SpringerNatureBot, 'RETRY_BACKOFF', 0)
