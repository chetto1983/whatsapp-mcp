#!/bin/sh
set -eu

gateway_port="${WHATSAPP_GATEWAY_PORT:-8081}"
export WHATSAPP_GATEWAY_PORT="$gateway_port"
export WHATSAPP_GATEWAY_HOST="${WHATSAPP_GATEWAY_HOST:-0.0.0.0}"
export WHATSAPP_STORE_ROOT="${WHATSAPP_STORE_ROOT:-/app/whatsapp-bridge/store}"
export WHATSAPP_API_URL="${WHATSAPP_API_URL:-http://127.0.0.1:${gateway_port}/api}"
export WHATSAPP_MCP_TRANSPORT="${WHATSAPP_MCP_TRANSPORT:-http}"
export WHATSAPP_MCP_HOST="${WHATSAPP_MCP_HOST:-0.0.0.0}"
export WHATSAPP_MCP_PORT="${WHATSAPP_MCP_PORT:-8080}"

mkdir -p /app/whatsapp-bridge/store

stop_children() {
  if [ "${gateway_pid:-}" ]; then
    kill "$gateway_pid" 2>/dev/null || true
  fi
  if [ "${mcp_pid:-}" ]; then
    kill "$mcp_pid" 2>/dev/null || true
  fi
}

trap 'stop_children; exit 143' INT TERM

(
  cd /app/whatsapp-mcp-server
  exec .venv/bin/python tenant_gateway.py
) &
gateway_pid="$!"

(
  cd /app/whatsapp-mcp-server
  exec .venv/bin/python main.py
) &
mcp_pid="$!"

status=0
while true; do
  if ! kill -0 "$gateway_pid" 2>/dev/null; then
    wait "$gateway_pid" || status="$?"
    stop_children
    wait "$mcp_pid" 2>/dev/null || true
    exit "$status"
  fi
  if ! kill -0 "$mcp_pid" 2>/dev/null; then
    wait "$mcp_pid" || status="$?"
    stop_children
    wait "$gateway_pid" 2>/dev/null || true
    exit "$status"
  fi
  sleep 2
done
