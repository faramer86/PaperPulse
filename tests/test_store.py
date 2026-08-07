"""Tests for the store that remembers which articles were already posted."""

import json
from datetime import date, timedelta

import pytest

from store import FileSeenStore

TODAY = date(2026, 8, 7)


@pytest.fixture
def store(tmp_path):
    return FileSeenStore(tmp_path / 'seen.json')


async def test_everything_is_unseen_before_anything_is_remembered(store):
    assert await store.unseen(['10.1038/a', '10.1038/b']) == ['10.1038/a', '10.1038/b']


async def test_remembered_dois_stop_being_unseen(store):
    await store.remember(['10.1038/a'], TODAY)

    assert await store.unseen(['10.1038/a', '10.1038/b']) == ['10.1038/b']


async def test_unseen_keeps_input_order_and_drops_duplicates(store):
    assert await store.unseen(['10.1038/b', '10.1038/a', '10.1038/b']) == \
        ['10.1038/b', '10.1038/a']


async def test_state_survives_a_new_process(tmp_path):
    path = tmp_path / 'seen.json'
    await FileSeenStore(path).remember(['10.1038/a'], TODAY)

    assert await FileSeenStore(path).unseen(['10.1038/a']) == []


async def test_a_missing_file_reads_as_empty(tmp_path):
    assert await FileSeenStore(tmp_path / 'absent.json').unseen(['10.1038/a']) == ['10.1038/a']


async def test_entries_past_the_retention_window_are_pruned(tmp_path):
    path = tmp_path / 'seen.json'
    store = FileSeenStore(path, retention=timedelta(days=30))
    await store.remember(['10.1038/old'], TODAY - timedelta(days=40))
    await store.remember(['10.1038/new'], TODAY)

    assert json.loads(path.read_text()).keys() == {'10.1038/new'}


async def test_pruning_never_drops_anything_still_inside_the_lookback_window(tmp_path):
    """Retention must exceed the query window or articles would be re-posted."""
    store = FileSeenStore(tmp_path / 'seen.json', retention=timedelta(days=30))
    await store.remember(['10.1038/a'], TODAY - timedelta(days=7))
    await store.remember(['10.1038/b'], TODAY)

    assert await store.unseen(['10.1038/a', '10.1038/b']) == []


async def test_remembering_the_same_doi_twice_is_harmless(store):
    await store.remember(['10.1038/a'], TODAY)
    await store.remember(['10.1038/a'], TODAY)

    assert await store.unseen(['10.1038/a']) == []


async def test_file_is_written_sorted_so_git_diffs_stay_small(tmp_path):
    """The file is committed back by CI; unstable ordering would churn it."""
    path = tmp_path / 'seen.json'
    store = FileSeenStore(path)
    await store.remember(['10.1038/c', '10.1038/a', '10.1038/b'], TODAY)

    keys = list(json.loads(path.read_text()))
    assert keys == sorted(keys)
    assert path.read_text().endswith('\n')


async def test_remembering_nothing_does_not_create_a_file(tmp_path):
    path = tmp_path / 'seen.json'
    await FileSeenStore(path).remember([], TODAY)

    assert not path.exists()
