"""Fixed deployment-token authentication for Aura's remote WhatsApp MCP."""

from __future__ import annotations

import hmac
import os

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings


def service_token() -> str:
    token = os.getenv("WHATSAPP_MCP_SERVICE_TOKEN", "").strip()
    if len(token) < 16:
        raise ValueError("WHATSAPP_MCP_SERVICE_TOKEN is required and must be at least 16 characters")
    return token


class ServiceTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            expected = service_token()
        except ValueError:
            return None
        if not hmac.compare_digest(token, expected):
            return None
        return AccessToken(token=token, client_id="aura", scopes=[])


def auth_settings() -> AuthSettings:
    public_url = os.getenv("WHATSAPP_MCP_PUBLIC_URL", "http://localhost:8080").rstrip("/")
    return AuthSettings(
        issuer_url=public_url,
        resource_server_url=f"{public_url}/mcp",
    )
