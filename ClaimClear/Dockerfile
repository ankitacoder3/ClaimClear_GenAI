# ClaimClear in one image: the five MCP servers, the chat (UI2), and monitoring (Prometheus + Grafana), behind one
# public port (8000, nginx): the chat at /, Grafana at /grafana/ (read-only), Prometheus at /prometheus/.
# Runs without root (as Hugging Face Spaces require); docker compose publishes 8000 on port 80 (http://localhost),
# and a Space's address (https://<user>-<space>.hf.space) forwards to it.
#   docker compose up --build          (from ClaimClear/; reads the OpenRouter key from .env at run time)
# The image never contains .env or keys (.dockerignore); uploads and metrics live in var/.
FROM python:3.13-slim

ARG PROMETHEUS_VERSION=2.53.1
ARG GRAFANA_VERSION=11.1.0

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CLAIMCLEAR_UI_HOST=127.0.0.1 CLAIMCLEAR_CHAT_PORT=8001 CLAIMCLEAR_AUTO_LOCAL=0 \
    CLAIMCLEAR_MONITORING=1 CLAIMCLEAR_METRICS_PORT=9100 GRAFANA_HOME=/opt/grafana

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng build-essential nginx curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /opt/prometheus /opt/grafana \
 && curl -fsSL "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz" \
    | tar -xz -C /opt/prometheus --strip-components=1 \
 && curl -fsSL "https://dl.grafana.com/oss/release/grafana-${GRAFANA_VERSION}.linux-amd64.tar.gz" \
    | tar -xz -C /opt/grafana --strip-components=1 \
 && ln -s /opt/prometheus/prometheus /usr/local/bin/prometheus \
 && ln -s /opt/grafana/bin/grafana /usr/local/bin/grafana \
 && useradd -m -u 1000 claimclear \
 && mkdir -p /app && chown claimclear:claimclear /app

WORKDIR /app
COPY --chown=claimclear:claimclear . .
USER claimclear
ENV HOME=/home/claimclear

# both environments, the development data and the policy index, built once at image build time (as the same user
# that runs the app, so uploads, logs and caches stay writable)
RUN python start.py --setup-only --no-local-llm

EXPOSE 8000
CMD ["python", "start.py", "--no-browser", "--no-local-llm"]
