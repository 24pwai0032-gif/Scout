# Scout — Frontend (Streamlit dashboard)

A standalone Streamlit app. It talks to the backend **only over HTTP** (`SCOUT_API_URL`)
and imports no backend code, so it deploys independently — e.g. to Streamlit Community
Cloud — while the backend is hosted elsewhere.

## Run locally

```bash
pip install -r requirements.txt
export SCOUT_API_URL=http://localhost:8000   # the running backend
streamlit run app.py
```

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `SCOUT_API_URL` | `http://localhost:8000` | Base URL of the backend FastAPI service |
| `SCOUT_STORE_ID` | `demo-store` | Store to show |

## Deploy to Streamlit Community Cloud

Point Community Cloud at `frontend/app.py`, and set `SCOUT_API_URL` to your deployed
backend URL. Community Cloud runs the dashboard only — the backend (API + agent + MCP
server + DB + scheduler) must be hosted separately (see ../README.md).
