from tests.conftest import make_item


def test_uid_stable_and_unique():
    a = make_item("Bitcoin hits 100k", guid="g1")
    b = make_item("Bitcoin hits 100k", guid="g1")
    c = make_item("Bitcoin hits 100k", guid="g2")
    assert a.uid == b.uid
    assert a.uid != c.uid


def test_dedup_key_collapses_same_story_across_sources():
    a = make_item("Bitcoin Hits $100K", source_id="coindesk", guid="x")
    b = make_item("bitcoin hits $100k!!!", source_id="cointelegraph", guid="y")
    assert a.dedup_key == b.dedup_key
    # Different uid (different guid/source) though.
    assert a.uid != b.uid


def test_dedup_key_differs_for_different_stories():
    a = make_item("Ethereum upgrade goes live")
    b = make_item("SEC sues exchange over fraud")
    assert a.dedup_key != b.dedup_key
