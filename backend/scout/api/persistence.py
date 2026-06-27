"""Persist and read back Findings (reuses the Phase 0.5 schema)."""

from __future__ import annotations

import json

from sqlalchemy import select

from scout.capture.db import session_scope
from scout.capture.schema import FindingRecord
from scout.models import Finding


def save_finding(finding: Finding) -> int:
    with session_scope() as s:
        rec = FindingRecord(
            store_id=finding.store_id,
            headline=finding.headline,
            confirmed_cause=finding.confirmed_cause.value if finding.confirmed_cause else "",
            confidence=finding.confidence,
            payload_json=finding.model_dump_json(),
        )
        s.add(rec)
        s.flush()
        return rec.id


def list_findings(store_id: str | None = None, limit: int = 50) -> list[dict]:
    with session_scope() as s:
        q = select(FindingRecord).order_by(FindingRecord.created_at.desc()).limit(limit)
        if store_id:
            q = q.where(FindingRecord.store_id == store_id)
        rows = s.execute(q).scalars().all()
        return [
            {
                "id": r.id,
                "store_id": r.store_id,
                "headline": r.headline,
                "confirmed_cause": r.confirmed_cause or None,
                "confidence": r.confidence,
                "created_at": r.created_at.isoformat(),
                "finding": json.loads(r.payload_json),
            }
            for r in rows
        ]
