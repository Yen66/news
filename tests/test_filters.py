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


def test_macro_keywords_match():
    for title in [
        "ECB holds interest rates steady",
        "Gold hits record as dollar weakens",
        "Oil prices surge on supply fears",
        "US Treasury yields climb to 5%",
        "Hedge funds boost bets on the yen",
        "Bitcoin ETF flows turn positive",
        "Forex markets brace for Fed decision",
    ]:
        assert filters.matches_keywords(make_item(title)), title


def test_word_boundary_avoids_false_positives():
    # 'ada' inside 'Canada', 'oil' inside 'boiling', 'ton' inside 'Washington'
    assert not filters.matches_keywords(make_item("Canada boiling over Washington"))
    # but a real standalone ticker still matches
    assert filters.matches_keywords(make_item("ADA gains 5% today"))


def test_score_impact_ban_does_not_match_bank():
    bank = make_item("Major bank reports earnings", impact=40)
    # 'bank' must not trigger the 'ban' high-impact term.
    assert filters.score_impact(bank) == 40
    real_ban = make_item("Country announces crypto ban", impact=40)
    assert filters.score_impact(real_ban) > 40


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
