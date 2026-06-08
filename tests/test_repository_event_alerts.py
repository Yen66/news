from src.db.repository import InMemoryRepository, _rowcount_from_status


async def test_alert_fired_false_then_true_after_mark():
    repo = InMemoryRepository()
    assert not await repo.alert_fired("cpi:20260611T1230Z", "1h")
    inserted = await repo.mark_alert_fired("cpi:20260611T1230Z", "1h")
    assert inserted is True
    assert await repo.alert_fired("cpi:20260611T1230Z", "1h")


async def test_mark_is_idempotent():
    repo = InMemoryRepository()
    first = await repo.mark_alert_fired("fomc:20260617T1800Z", "24h")
    second = await repo.mark_alert_fired("fomc:20260617T1800Z", "24h")
    assert first is True
    assert second is False  # already recorded -> no duplicate


async def test_offsets_tracked_independently():
    repo = InMemoryRepository()
    await repo.mark_alert_fired("cpi:20260611T1230Z", "24h")
    assert await repo.alert_fired("cpi:20260611T1230Z", "24h")
    # The 1h offset for the same event is still unfired.
    assert not await repo.alert_fired("cpi:20260611T1230Z", "1h")


async def test_load_fired_alerts_returns_all():
    repo = InMemoryRepository()
    await repo.mark_alert_fired("cpi:20260611T1230Z", "24h")
    await repo.mark_alert_fired("cpi:20260611T1230Z", "1h")
    fired = await repo.load_fired_alerts()
    assert fired == {
        ("cpi:20260611T1230Z", "24h"),
        ("cpi:20260611T1230Z", "1h"),
    }


def test_rowcount_from_status_parsing():
    assert _rowcount_from_status("INSERT 0 1") == 1
    assert _rowcount_from_status("INSERT 0 0") == 0
    assert _rowcount_from_status("garbage") == 0
    assert _rowcount_from_status("") == 0
