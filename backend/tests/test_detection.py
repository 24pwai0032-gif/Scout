from datetime import date, timedelta

from scout.agent.detection import detect_for_day
from scout.config import get_settings


def _incident_tuesday() -> date:
    today = date.today()
    off = (today.weekday() - 1) % 7 or 7
    return today - timedelta(days=off)


def test_incident_tuesday_flags():
    a = detect_for_day("demo-store", "revenue", _incident_tuesday(), get_settings())
    assert a is not None
    assert a.weekday == "Tuesday"
    assert a.deviation_pct < -10        # ~ -18%
    assert abs(a.robust_z) >= get_settings().robust_z_threshold


def test_normal_day_does_not_flag():
    normal = _incident_tuesday() - timedelta(days=1)  # the Monday before
    assert detect_for_day("demo-store", "revenue", normal, get_settings()) is None


def test_prior_same_weekday_does_not_flag():
    prior_tue = _incident_tuesday() - timedelta(days=7)
    assert detect_for_day("demo-store", "revenue", prior_tue, get_settings()) is None
