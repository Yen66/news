"""Phase 8 — story_key collapses event-synonym retellings.

"Meta announces X" and "Meta unveils X" are the same story from two desks and
must dedup; genuinely different stories must stay distinct.
"""
from src.models import story_key


SAME_STORY_PAIRS = [
    ("Meta announces new AI data center", "Meta unveils new AI data center"),
    ("Coinbase launches staking product", "Coinbase releases staking product"),
    ("BlackRock acquires crypto custody firm",
     "BlackRock buys crypto custody firm"),
    ("Circle raises 400 million in funding round",
     "Circle secures 400 million in funding round"),
    ("SEC approves spot ether ETF", "SEC approval for spot ether ETF"),
]


def test_synonym_retellings_collapse():
    for a, b in SAME_STORY_PAIRS:
        assert story_key(a) == story_key(b), f"{a!r} != {b!r}"


DISTINCT_STORY_PAIRS = [
    # Same subject, genuinely different actions -> must NOT collapse.
    ("Meta announces new data center", "Meta acquires AI startup"),
    ("Ethereum upgrade goes live", "Ethereum staking hits record"),
    ("Coinbase launches staking", "Coinbase sued by SEC"),
    ("SEC approves spot ether ETF", "SEC rejects spot ether ETF"),
]


def test_distinct_stories_stay_distinct():
    for a, b in DISTINCT_STORY_PAIRS:
        assert story_key(a) != story_key(b), f"collapsed: {a!r} == {b!r}"
