"""Daily AI-call budget tracking to stay within free limits.

A simple per-UTC-day counter. When we are close to the budget, the processor
prioritises official / high-impact items and can skip the optional editor
pass. This is plain code, not an AI task.
"""
from __future__ import annotations

from datetime import date


class DailyBudget:
    def __init__(self, daily_limit: int) -> None:
        self._limit = max(1, daily_limit)
        self._day = date.today()
        self._used = 0

    def _roll(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self._used = 0

    def record(self, calls: int = 1) -> None:
        self._roll()
        self._used += calls

    @property
    def used(self) -> int:
        self._roll()
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self._limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    @property
    def near_limit(self) -> bool:
        """True when under 20% of the daily budget remains."""
        return self.remaining <= max(1, self._limit // 5)

    def can_spend(self, calls: int = 1) -> bool:
        return self.remaining >= calls
