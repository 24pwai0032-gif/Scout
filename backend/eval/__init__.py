"""Phase 3.5 — deterministic offline eval harness.

Recorded fixtures (cassettes) are the SANCTIONED test path. The 'no mock data' rule
applies to PRODUCTION only; here we replay recorded tool responses so detection +
attribution are measurable without live APIs or burning tokens.
"""
