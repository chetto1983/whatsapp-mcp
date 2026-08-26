"""OAuth resource-server authentication for the remote WhatsApp MCP."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import anyio
import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from tenant_context import normalize_identity

MCP_TOOLS_SCOPE = "mcp:tools"
SUPPORTED_JWT_ALGORITHMS = ("EdDSA", "RS256", "PS256", "ES256")
logger = logging.getLogger("whatsapp_mcp.oauth")


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    jwks_url: str
    resource: str

    @classmethod
    def from_environment(cls) -> OAuthConfig:
        issuer = os.getenv("MCP_OAUTH_ISSUER", "http://localhost:9080").rstrip("/")
        return cls(
            issuer=issuer,
            jwks_url=os.getenv("MCP_OAUTH_JWKS_URL", f"{issuer}/oauth/jwks"),
            resource=os.getenv("MCP_OAUTH_RESOURCE", "http://localhost:8080/mcp/"),
        )


class JWTTokenVerifier:
    def __init__(self, config: OAuthConfig, jwks_client: Any | None = None):
        self._config = config
        self._jwks = jwks_client or jwt.PyJWKClient(
            config.jwks_url,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )
        logger.info(
            "OAuth resource verifier configured issuer=%s resource=%s jwks=%s",
            config.issuer,
            config.resource,
            config.jwks_url,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await anyio.to_thread.run_sync(self._decode, token)
            subject = normalize_identity(claims["sub"])
            client_id = claims["client_id"]
            scope = claims["scope"]
            expires_at = claims["exp"]
            if not isinstance(client_id, str) or not isinstance(scope, str) or not isinstance(expires_at, int):
                logger.warning("OAuth bearer rejected before tenant binding: invalid claim types")
                return None
        except jwt.PyJWKClientConnectionError as error:
            logger.warning("OAuth JWKS fetch failed before tenant binding: %s", error)
            return None
        except (KeyError, TypeError, ValueError, jwt.PyJWTError) as error:
            logger.warning("OAuth bearer rejected before tenant binding: %s", type(error).__name__)
            return None
        logger.debug("OAuth bearer accepted")
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scope.split(),
            expires_at=expires_at,
            resource=self._config.resource,
            subject=subject,
            claims=claims,
        )

    def _decode(self, token: str) -> dict[str, Any]:
        signing_key = self._jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key,
            algorithms=list(SUPPORTED_JWT_ALGORITHMS),
            audience=self._config.resource,
            issuer=self._config.issuer,
            options={"require": ["exp", "iss", "aud", "sub", "scope", "client_id"]},
        )


def auth_settings(config: OAuthConfig) -> AuthSettings:
    return AuthSettings(
        issuer_url=config.issuer,
        resource_server_url=config.resource,
        required_scopes=[MCP_TOOLS_SCOPE],
    )
