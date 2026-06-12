"""Task 1.1 — subject-level burst cap.

Same subject 5× in window must yield exactly MAX_PER_SUBJECT admissions;
distinct subjects must be unaffected; passing the window expires the count.
"""
from src.models import subject_key
from src.pipeline.subject import SubjectCap
from tests.conftest import make_item


# ---- SubjectCap behaviour --------------------------------------------------

def test_same_subject_capped_at_max_per_subject():
    cap = SubjectCap(window_hours=12, max_per_subject=2)
    titles = [
        "SpaceX IPO targets $400 billion valuation",
        "SpaceX IPO eyes $500B valuation",
        "Musk's SpaceX files IPO paperwork",
        "SpaceX IPO sees strong demand",
        "SpaceX IPO valuation jumps 30%",
    ]
    now = 1_000_000.0
    accepted = 0
    for title in titles:
        item = make_item(title, guid=title)
        if not cap.is_capped(item, now=now):
            cap.mark(item, now=now)
            accepted += 1
    assert accepted == 2


def test_distinct_subjects_unaffected():
    cap = SubjectCap(window_hours=12, max_per_subject=2)
    now = 1_000_000.0
    for title in [
        "SpaceX IPO targets $400 billion valuation",
        "Tesla earnings beat estimates",
        "Apple unveils new chip",
        "Coinbase wins SEC court ruling",
    ]:
        item = make_item(title)
        assert not cap.is_capped(item, now=now), f"capped wrongly: {title!r}"
        cap.mark(item, now=now)


def test_window_expiry_resets_count():
    cap = SubjectCap(window_hours=12, max_per_subject=2)
    t0 = 1_000_000.0
    cap.mark(make_item("SpaceX IPO targets $400B"), now=t0)
    cap.mark(make_item("SpaceX IPO valuation rises"), now=t0)
    third = make_item("SpaceX IPO sees demand")
    # Within the 12h window — capped.
    assert cap.is_capped(third, now=t0 + 3600)
    # Past the window — open again.
    assert not cap.is_capped(third, now=t0 + 13 * 3600)


def test_zero_max_caps_everything():
    cap = SubjectCap(window_hours=12, max_per_subject=0)
    assert cap.is_capped(make_item("anything"))


# ---- subject_key collapses sagas, distinguishes unrelated ------------------

def test_subject_key_collapses_spacex_saga():
    titles = [
        "SpaceX IPO targets $400 billion valuation",
        "SpaceX IPO eyes $500B valuation",
        "Musk's SpaceX files IPO paperwork",
        "SpaceX IPO valuation jumps 30%",
    ]
    keys = {subject_key(t) for t in titles}
    assert len(keys) == 1, f"saga should collapse to one subject: {keys}"


def test_subject_key_distinguishes_unrelated_stories():
    a = subject_key("Tesla earnings beat estimates")
    b = subject_key("Bitcoin hits new all-time high")
    c = subject_key("Coinbase wins SEC court ruling")
    assert len({a, b, c}) == 3


def test_subject_key_collapses_named_principal_saga():
    # Different verbs/numbers around the same named principal collapse.
    a = subject_key("Zuckerberg unveils new AI labs")
    b = subject_key("Zuckerberg announces Meta restructuring")
    c = subject_key("Mark Zuckerberg buys San Francisco mansion")
    assert a == b == c
