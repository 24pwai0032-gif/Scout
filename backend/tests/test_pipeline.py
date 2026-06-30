from scout.api.persistence import list_findings, list_runs
from scout.api.queue import run_pipeline


def test_pipeline_produces_stockout_finding():
    fid = run_pipeline("demo-store", trigger="manual")
    assert fid is not None
    findings = list_findings("demo-store", limit=1)
    assert findings, "a finding should be persisted"
    f = findings[0]
    assert f["confirmed_cause"] == "STOCKOUT"
    assert "out of stock" in f["headline"].lower()
    assert f["finding"]["recommended_action"]


def test_pipeline_records_an_investigation_run():
    run_pipeline("demo-store", trigger="manual")
    runs = list_runs("demo-store", limit=1)
    assert runs, "a run should be recorded"
    r = runs[0]
    assert r["trigger"] == "manual"
    assert r["status"] in ("completed", "inconclusive")
    assert r["findingId"] is not None
    assert r["durationMs"] >= 0
