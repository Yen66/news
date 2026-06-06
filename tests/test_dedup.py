from src.pipeline.dedup import Deduplicator
from tests.conftest import make_item


def test_exact_duplicate_detected():
    d = Deduplicator()
    item = make_item("Bitcoin news", guid="g1")
    assert not d.is_duplicate(item)
    d.mark(item)
    assert d.is_duplicate(make_item("Bitcoin news", guid="g1"))


def test_cross_source_story_collapsed_in_batch():
    d = Deduplicator()
    batch = [
        make_item("Bitcoin Hits $100K", source_id="a", guid="a1"),
        make_item("bitcoin hits $100k", source_id="b", guid="b1"),
        make_item("Ethereum upgrade live", source_id="c", guid="c1"),
    ]
    new = d.filter_new(batch)
    assert len(new) == 2


def test_seen_bootstrap_from_storage():
    seed = make_item("Old news", guid="old")
    d = Deduplicator(seen_uids={seed.uid}, seen_keys={seed.dedup_key})
    assert d.is_duplicate(make_item("Old news", guid="old"))


def test_mark_increases_size():
    d = Deduplicator()
    d.mark(make_item("x", guid="1"))
    d.mark(make_item("y", guid="2"))
    assert d.size == 2
