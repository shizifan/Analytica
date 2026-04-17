FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl for health check
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (production + test)
COPY requirements.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-test.txt

# Copy application source
COPY backend/ backend/
COPY migrations/ migrations/
COPY alembic.ini pyproject.toml ./

# Copy test & mock server (for pipeline testing on target)
COPY tests/ tests/
COPY mock_server/ mock_server/

# Copy entrypoint script
COPY deploy/docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
