# Cloud Run image for the Lawn-Mower Deployment Advisor (FastAPI + Vertex Gemini).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for layer caching.
COPY agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code (flat imports: server.py imports mcp_client/orchestrator).
COPY agent/src/ ./src/
WORKDIR /app/src

# Cloud Run injects PORT (defaults to 8080); server.py honours it.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
