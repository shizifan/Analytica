FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl, CJK fonts, and Node.js (pptxgenjs bridge) for health check
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fonts-noto-cjk \
        fonts-noto-cjk-extra \
        fonts-jetbrains-mono \
        fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20.x for pptxgenjs bridge (PPTX 矢量图表质量红线)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && node -v && npm -v

# Install pptxgenjs bridge dependencies
COPY backend/tools/report/_pptxgen_bridge/package.json /app/bridge/package.json
RUN cd /app/bridge && npm ci --production && cd /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY backend/ backend/
COPY migrations/ migrations/
COPY alembic.ini pyproject.toml ./
COPY employees/ employees/

# Copy entrypoint script
COPY deploy/docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
