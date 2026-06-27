"""Time helpers.

`utcnow()` returns a NAIVE UTC datetime — same semantics as the deprecated
`datetime.utcnow()`, so stored values and comparisons are unchanged, but without the
Python 3.12 DeprecationWarning. Our DB columns are timezone-naive; keep it that way.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
