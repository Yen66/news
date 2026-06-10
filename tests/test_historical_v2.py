"""Phase 3 — retrospective vs current-event-with-historical-reference.

Built from real production failures. The goal is NOT to block years; it is to
block articles that are ABOUT the past, while letting current events that
merely REFERENCE a past year through.
"""
from src.pipeline import filters
from src.pipeline.filters import filter_items
from tests.conftest import make_item


# --- MUST FAIL: articles whose primary topic is a past year/era -----------

RETROSPECTIVES_FAIL = [
    "2016 was a key year for Bitcoin",
    "Why 2022 changed crypto forever",
    "Lessons from the 2021 bull market",
    "2023 became a turning point",
    "2016 year became significant for Bitcoin",
    "2021 cycle lessons every trader should know",
    "2022 collapse retrospective",
    "2024 will be remembered as the institutional year",
    "2025 cycle analysis",
    "How Bitcoin survived the 2022 bear market",
]


def test_retrospectives_fail():
    for title in RETROSPECTIVES_FAIL:
        item = make_item(title)
        assert filters.is_historical(item), f"not historical: {title}"
        assert filters.is_invalid_noise(item), f"not noise: {title}"
        assert not filters.should_publish(item), f"published: {title}"
        assert not filter_items([item]), f"kept: {title}"


# --- MUST PASS: current events that reference a past year ------------------

CURRENT_WITH_REFERENCE_PASS = [
    "Bitcoin falls to levels last seen in 2020",
    "Inflation reaches highest level since 2021",
    "Nvidia reports strongest growth since 2022",
    "BTC returns to prices not seen since 2021",
    "Gold hits highest since 2020 on safe-haven demand",
    "Treasury yields climb to highest since 2007",
]


def test_current_with_reference_passes():
    for title in CURRENT_WITH_REFERENCE_PASS:
        item = make_item(title)
        assert not filters.is_historical(item), f"historical: {title}"
        assert not filters.is_invalid_noise(item), f"noise: {title}"
        assert filters.should_publish(item), f"rejected: {title}"
        assert filter_items([item]), f"dropped: {title}"


def test_reference_helpers():
    assert filters.is_year_reference(
        make_item("Bitcoin falls to levels last seen in 2020")
    )
    assert filters.is_year_reference(
        make_item("Inflation reaches highest level since 2021")
    )
    assert not filters.is_year_reference(make_item("2016 was a key year"))
    assert filters.is_retrospective_topic(make_item("2016 was a key year"))
    assert not filters.is_retrospective_topic(
        make_item("Bitcoin falls to levels last seen in 2020")
    )
