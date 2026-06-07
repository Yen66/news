from src.pipeline.dedup import Deduplicator
from tests.conftest import make_item


def test_exact_duplicate_detected():
    d = Deduplicator()
    item = make_item("Bitcoin news", guid="g1")
    assert not d.is_duplicate(item)
    d.mark(item)
    assert d.is_duplicate(make_item("Bitcoin news", guid="g1"))


def test_different_articles_not_duplicate():
    d = Deduplicator()
    d.mark(make_item("Story A", guid="a1"))
    assert not d.is_duplicate(make_item("Story A", guid="a2"))  # different uid


def test_filter_new_collapses_same_uid_in_batch():
    d = Deduplicator()
    batch = [
        make_item("Same article", guid="dup"),
        make_item("Same article", guid="dup"),
        make_item("Other", guid="other"),
    ]
    new = d.filter_new(batch)
    assert len(new) == 2


def test_seen_bootstrap_from_storage():
    seed = make_item("Old news", guid="old")
    d = Deduplicator(seen_uids={seed.uid})
    assert d.is_duplicate(make_item("Old news", guid="old"))


def test_mark_increases_size():
    d = Deduplicator()
    d.mark(make_item("x", guid="1"))
    d.mark(make_item("y", guid="2"))
    assert d.size == 2
