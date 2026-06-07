from src.models import story_key, story_tokens
from src.pipeline.story import StoryDeduplicator
from tests.conftest import make_item


def test_same_story_different_wording_same_key():
    # The headline example from the spec.
    assert story_key("BTC drops to $59K") == story_key("Bitcoin falls to $59,000")
    # And the classic case-insensitive one.
    assert story_key("Bitcoin Hits $100K") == story_key("bitcoin hits $100k!!!")


def test_different_stories_different_key():
    assert story_key("Ethereum upgrade goes live") != story_key(
        "SEC sues exchange over fraud"
    )
    # Same asset, different numberless event -> must NOT collapse.
    assert story_key("Ethereum upgrade goes live") != story_key(
        "Ethereum staking hits record"
    )


def test_story_tokens_normalise_numbers_and_coins():
    toks = story_tokens("Bitcoin falls to $59,000")
    assert "btc" in toks
    assert "59000" in toks


def test_percent_normalisation():
    assert story_key("ETH down 7,25% today") == story_key("Ethereum drops 7.25%")


def test_window_dedup_skips_recent():
    d = StoryDeduplicator(window_hours=6)
    a = make_item("BTC drops to $59K", guid="a")
    b = make_item("Bitcoin falls to $59,000", guid="b")
    assert not d.is_recent(a, now=1000.0)
    d.mark(a, now=1000.0)
    # Same story, different source, within window => recent.
    assert d.is_recent(b, now=1000.0 + 3600)


def test_window_dedup_allows_after_window():
    d = StoryDeduplicator(window_hours=6)
    a = make_item("BTC drops to $59K", guid="a")
    d.mark(a, now=1000.0)
    # 7h later (> 6h window) => no longer considered recent.
    assert not d.is_recent(a, now=1000.0 + 7 * 3600)


def test_window_prune_drops_old_entries():
    d = StoryDeduplicator(window_hours=6)
    d.mark(make_item("BTC drops to $59K", guid="a"), now=1000.0)
    assert d.size == 1
    # marking something new far in the future prunes the stale entry
    d.mark(make_item("Gold hits $3000 record", guid="b"), now=1000.0 + 8 * 3600)
    assert d.size == 1
