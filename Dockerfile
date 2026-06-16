# Aura fork of whatsapp-mcp (chetto1983/whatsapp-mcp @ aura/cockpit-connect).
# Builds the combined image: the CGO whatsmeow Go bridge (REST + cockpit management
# API on :8081) and the Python FastMCP front served over streamable-HTTP (:8080), so
# the agent mounts the MCP at http://host:8080/mcp/ while Aura's cockpit drives device
# linking via the bridge's /api/{status,qr,logout} on :8081.

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

# fastmcp 2.x provides the streamable-HTTP transport; patch the import the upstream
# main.py uses (mcp.server.fastmcp -> fastmcp). The run() call is already HTTP in this
# fork (whatsapp-mcp-server/main.py).
RUN cd /app/whatsapp-mcp-server \
    && uv sync --frozen --no-dev \
    && uv pip install --python .venv/bin/python fastmcp==2.14.7 \
    && python -c "from pathlib import Path; p = Path('/app/whatsapp-mcp-server/main.py'); t = p.read_text(); p.write_text(t.replace('from mcp.server.fastmcp import FastMCP', 'from fastmcp import FastMCP'))" \
    && chmod +x /usr/local/bin/entrypoint.sh

ENV WHATSAPP_BRIDGE_PORT=8081
ENV WHATSAPP_API_BASE_URL=http://127.0.0.1:8081/api
ENV MCP_PORT=8080

EXPOSE 8080 8081

# The bridge management REST (always up, REST-first) is the liveness signal.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8081/api/status || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
