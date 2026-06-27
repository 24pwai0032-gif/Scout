# Frontend image — Streamlit dashboard only. No backend code.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app.py ./

EXPOSE 8501
# SCOUT_API_URL must point at the deployed backend (default for local compose below).
ENV SCOUT_API_URL=http://api:8000
CMD ["streamlit", "run", "app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
