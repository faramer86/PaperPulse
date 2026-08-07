"""Memory of which articles have already been posted.

The bot re-queries a rolling window on every run, so the same article comes
back repeatedly until it falls out of the window. This store is what turns
that overlap from duplicate posts into a no-op, and it is why the bot no
longer needs the old two-day publication delay.

Entries only have to outlive the query window, so old ones are pruned and the
file stays a few kilobytes -- small enough to commit back from CI.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

# Comfortably longer than the query window so nothing is forgotten while it
# can still be returned by a query, and short enough to bound the file.
DEFAULT_RETENTION = timedelta(days=30)


class SeenStore(ABC):
    """Interface a backend must satisfy. Swap in Postgres by implementing it."""

    @abstractmethod
    async def unseen(self, dois: Iterable[str]) -> list[str]:
        """Return the given DOIs that have not been posted yet, in input order."""

    @abstractmethod
    async def remember(self, dois: Iterable[str], today: date) -> None:
        """Record DOIs as posted on `today`."""


class FileSeenStore(SeenStore):
    """A JSON object mapping DOI to the date it was posted."""

    def __init__(self, path: Path, retention: timedelta = DEFAULT_RETENTION):
        self.path = Path(path)
        self.retention = retention

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    async def unseen(self, dois: Iterable[str]) -> list[str]:
        posted = self._read()
        fresh: list[str] = []
        for doi in dois:
            if doi not in posted and doi not in fresh:
                fresh.append(doi)
        return fresh

    async def remember(self, dois: Iterable[str], today: date) -> None:
        dois = list(dois)
        if not dois:
            return
        posted = self._read()
        posted.update({doi: today.isoformat() for doi in dois})

        cutoff = (today - self.retention).isoformat()
        kept = {doi: on for doi, on in posted.items() if on >= cutoff}

        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Sorted with a trailing newline so CI commits produce minimal diffs.
        self.path.write_text(json.dumps(kept, indent=1, sort_keys=True) + '\n')
