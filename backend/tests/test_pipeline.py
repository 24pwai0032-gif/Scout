from scout.api.persistence import list_findings
from scout.api.queue import run_pipeline


def test_pipeline_produces_stockout_finding():
    fid = run_pipeline("demo-store")
    assert fid is not None
    findings = list_findings("demo-store", limit=1)
    assert findings, "a finding should be persisted"
    f = findings[0]
    assert f["confirmed_cause"] == "STOCKOUT"
    assert "out of stock" in f["headline"].lower()
    assert f["finding"]["recommended_action"]
