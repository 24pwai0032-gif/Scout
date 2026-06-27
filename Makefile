# Scout developer tasks. On Windows without `make`, run the commands shown directly.
# Backend code lives in backend/ (run targets cd there); frontend is the Streamlit app.
PY ?= python
BE := cd backend &&

.PHONY: install install-frontend seed detect run eval test api dashboard mcp verify-events smoketest

install:           ## install backend (editable, all extras) for local dev
	$(BE) $(PY) -m pip install -e ".[all]"

install-frontend:  ## install the frontend (Streamlit) deps
	cd frontend && $(PY) -m pip install -r requirements.txt

seed:              ## seed the deterministic demo store
	$(BE) $(PY) -m scout.capture.seed_demo

detect:            ## run detection over recent days
	$(BE) $(PY) -c "from scout.agent.detection import detect_recent; [print(a.date,a.weekday,a.deviation_pct,a.robust_z) for a in detect_recent('demo-store')]"

run:               ## detect + investigate the strongest anomaly (prints the Finding)
	$(BE) $(PY) -m scout.agent.run

eval:              ## deterministic eval: precision/recall/attribution (gated)
	$(BE) SCOUT_MCP_TRANSPORT=inprocess $(PY) -m eval.run_eval

test:              ## run the test suite
	$(BE) $(PY) -m pytest -q

api:               ## run the FastAPI backend
	$(BE) $(PY) -m uvicorn scout.api.main:app --reload --port 8000

dashboard:         ## run the Streamlit dashboard (needs the backend running)
	cd frontend && SCOUT_API_URL=http://localhost:8000 $(PY) -m streamlit run app.py

mcp:               ## run the MCP server standalone
	$(BE) $(PY) -m scout.mcp_server.server

smoketest:         ## call every MCP tool end-to-end
	$(BE) $(PY) scripts/mcp_smoketest.py

verify-events:     ## show captured event counts
	$(BE) $(PY) scripts/verify_events.py
