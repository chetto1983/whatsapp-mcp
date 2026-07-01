# syntax=docker/dockerfile:1.7

# Aura sidecar image for the fused fork:
# - Go whatsmeow bridge on :8081, including Aura cockpit management endpoints.
# - Python MCP server on :8080 using upstream verygoodplugins transport config.

FROM golang:bookworm AS bridge-build

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/whatsapp-bridge
COPY whatsapp-bridge/go.mod whatsapp-bridge/go.sum ./
RUN go mod download
COPY whatsapp-bridge/ ./
RUN CGO_ENABLED=1 go build -trimpath -ldflags="-s -w" -o /out/whatsapp-bridge .

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.5.31

WORKDIR /app
COPY whatsapp-mcp-server/ ./whatsapp-mcp-server/
COPY whatsapp-bridge/ ./whatsapp-bridge/
COPY --from=bridge-build /out/whatsapp-bridge /usr/local/bin/whatsapp-bridge
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN cd /app/whatsapp-mcp-server \
    && uv sync --frozen --no-dev \
    && chmod +x /usr/local/bin/entrypoint.sh

ENV WHATSAPP_BRIDGE_HOST=0.0.0.0
ENV WHATSAPP_BRIDGE_PORT=8081
ENV WHATSAPP_API_URL=http://127.0.0.1:8081/api
ENV WHATSAPP_DB_PATH=/app/whatsapp-bridge/store/messages.db
ENV WHATSMEOW_DB_PATH=/app/whatsapp-bridge/store/whatsapp.db
ENV WHATSAPP_MCP_TRANSPORT=http
ENV WHATSAPP_MCP_HOST=0.0.0.0
ENV WHATSAPP_MCP_PORT=8080
ENV WHATSAPP_MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*,[::1]:*,whatsapp:*,aura-whatsapp:*
ENV WHATSAPP_MCP_ALLOWED_ORIGINS=http://127.0.0.1:*,http://localhost:*,http://[::1]:*,http://whatsapp:*,http://aura-whatsapp:*

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8081/api/status || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
