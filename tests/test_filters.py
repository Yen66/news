from src.pipeline import filters
from tests.conftest import make_item


def test_keyword_filter_keeps_relevant():
    assert filters.matches_keywords(make_item("Bitcoin rallies above 70k"))
    assert filters.matches_keywords(make_item("Nasdaq closes at record high"))
    assert filters.matches_keywords(make_item("Nvidia earnings beat estimates"))


def test_keyword_filter_drops_irrelevant():
    assert not filters.matches_keywords(make_item("Local bakery wins award"))


def test_ads_dropped():
    assert filters.is_ad(make_item("Sponsored: buy this token now"))
    assert filters.is_ad(make_item("Huge airdrop giveaway for everyone"))


def test_official_source_never_ad():
    item = make_item("SEC press release on crypto", official=True)
    assert not filters.is_ad(item)


def test_price_horoscope_dropped():
    assert filters.is_price_horoscope(
        make_item("Bitcoin price prediction: BTC could hit 1,000,000")
    )
    assert filters.is_price_horoscope(make_item("This altcoin will do 100x soon"))


def test_opinion_requires_influential_author():
    random_guy = make_item("Random trader predicts Bitcoin crash")
    assert not filters.should_publish(random_guy)

    powell = make_item("Powell warns inflation may persist, markets watch")
    assert filters.should_publish(powell)


def test_should_publish_master_gate():
    good = make_item("Ethereum network completes major upgrade")
    assert filters.should_publish(good)

    junk = make_item("Best meme coins to buy for 100x gains")
    assert not filters.should_publish(junk)


def test_impact_scoring_boosts_high_signal():
    base = make_item("SEC approves spot bitcoin ETF", official=True, impact=85)
    scored = filters.score_impact(base)
    assert scored >= base.impact
    assert scored <= 100


def test_filter_items_updates_impact_and_filters():
    items = [
        make_item("SEC approves spot bitcoin ETF", official=True, impact=85),
        make_item("Best altcoins price prediction 100x"),
        make_item("Cat video goes viral"),
    ]
    kept = filters.filter_items(items)
    assert len(kept) == 1
    assert kept[0].title.startswith("SEC")
