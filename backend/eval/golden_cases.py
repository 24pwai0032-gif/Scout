"""Golden cases for the eval: 1 true-positive (the stockout Tuesday) + true-negatives
(normal days that must NOT flag)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class GoldenCase:
    name: str
    day: date
    expect_flag: bool
    expect_cause: str | None  # confirmed cause when flagged


def _incident_tuesday(today: date | None = None) -> date:
    today = today or date.today()
    offset = (today.weekday() - 1) % 7 or 7
    return today - timedelta(days=offset)


def golden_cases(today: date | None = None) -> list[GoldenCase]:
    incident = _incident_tuesday(today)
    return [
        GoldenCase("stockout_tuesday", incident, expect_flag=True, expect_cause="STOCKOUT"),
        # True negatives: normal days that should be ignored.
        GoldenCase("normal_monday", incident - timedelta(days=1), expect_flag=False, expect_cause=None),
        GoldenCase("prior_tuesday", incident - timedelta(days=7), expect_flag=False, expect_cause=None),
        GoldenCase("normal_wednesday", incident - timedelta(days=6), expect_flag=False, expect_cause=None),
    ]
