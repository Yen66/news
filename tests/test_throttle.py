from src.pipeline.throttle import DailyBudget


def test_budget_counts_and_exhausts():
    b = DailyBudget(3)
    assert b.remaining == 3
    b.record()
    b.record(2)
    assert b.used == 3
    assert b.exhausted
    assert not b.can_spend(1)


def test_near_limit_threshold():
    b = DailyBudget(10)
    for _ in range(8):
        b.record()
    assert b.near_limit  # 2 remaining <= 20% of 10
    assert not b.exhausted
