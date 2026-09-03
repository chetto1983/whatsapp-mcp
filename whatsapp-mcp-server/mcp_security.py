"""OAuth resource-server authentication for the remote WhatsApp MCP."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import anyio
import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from tenant_context import normalize_identity

MCP_TOOLS_SCOPE = "mcp:tools"
SUPPORTED_JWT_ALGORITHMS = ("EdDSA", "RS256", "PS256", "ES256")
# Where an issuer's keys live when the operator did not say. Aura's authorization
# server serves them here; a foreign issuer that does not (Google, Keycloak) has to be
# declared with an explicit `issuer=jwks_url` pair.
DEFAULT_JWKS_PATH = "/oauth/jwks"
# Kept WITH the trailing slash, matching the sibling arcadedb-mcp's own default. The
# spec's canonical form drops it (2026-07-28, "Canonical Server URI"), but every
# deployment sets MCP_OAUTH_RESOURCE explicitly, so changing this would move nothing
# except someone's existing single-name setup.
DEFAULT_RESOURCE = "http://localhost:8080/mcp/"
# Anchors the identity derivation below. Computed from a fixed URL rather than written
# as a literal, so the value is reproducible by reading this line and nobody has to
# trust a magic constant they cannot re-derive.
FOREIGN_IDENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "https://aura.local/mcp/foreign-identity")
logger = logging.getLogger("whatsapp_mcp.oauth")


@dataclass(frozen=True)
class TrustedIssuer:
    """One authorization server whose tokens are accepted, with the JWKS that verifies
    them.

    Two values and not one, because they are not always the same host: Compose already
    runs a split horizon where the issuer is advertised as 127.0.0.1:9080 (the name a
    client on the host can reach) while the keys are fetched from aura:9080 (the name
    this container can reach).
    """

    issuer: str
    jwks_url: str

    @classmethod
    def of(cls, issuer: str, jwks_url: str = "") -> TrustedIssuer:
        issuer = issuer.strip().rstrip("/")
        return cls(issuer=issuer, jwks_url=jwks_url.strip() or f"{issuer}{DEFAULT_JWKS_PATH}")


def parse_trusted_issuers(raw: str) -> tuple[TrustedIssuer, ...]:
    """Read MCP_OAUTH_TRUSTED_ISSUERS: a comma-separated list of `issuer` or
    `issuer=jwks_url` entries, naming authorization servers OTHER than the home one.

    Blank and malformed-empty entries are dropped rather than becoming an issuer named
    "" that no token could ever match but that would still sit in the trusted set.
    """
    issuers: list[TrustedIssuer] = []
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        issuer, _, jwks_url = entry.partition("=")
        if not issuer.strip():
            continue
        issuers.append(TrustedIssuer.of(issuer, jwks_url))
    return tuple(issuers)


def split_audiences(raw: str) -> tuple[str, ...]:
    """Read MCP_OAUTH_RESOURCE as a comma-separated list, so one server can answer to the
    several names it is reachable under. The FIRST entry is canonical: it is the only one
    advertised, and MCP clients treat it as the server's ADDRESS. The rest are merely
    accepted as token audiences.

    Both halves are load-bearing, measured 2026-09-02 on the sibling arcadedb-mcp and
    again here on 2026-09-03:

      - advertising the CONTAINER name made a host MCP client take it for the server's
        address and fail with `getaddrinfo ENOTFOUND whatsapp` before authentication
        could even begin;
      - advertising ONLY the loopback name would break the in-container agent, because
        Aura pins its self-issued grant's audience to the URL it dials -- observed in
        its own log as `Post "http://whatsapp:8080/mcp/"`.

    Accepting both is what lets one server answer both callers. This stays OUR job: the
    SDK's AuthSettings.resource_server_url is a single value serving as "the resource
    identifier AND base route to look up OAuth Protected Resource Metadata", with no
    option for several names (python-sdk issue #1264, open).

    Always returns at least one element, so callers need no emptiness check.
    """
    audiences = tuple(entry.strip() for entry in (raw or "").split(",") if entry.strip())
    return audiences or (DEFAULT_RESOURCE,)


@dataclass(frozen=True)
class OAuthConfig:
    # Every authorization server whose tokens are accepted, HOME FIRST. A tuple rather
    # than a single value because an MCP server is an OAuth *resource server*, and the
    # specification (revision 2026-07-28, basic/authorization) says its authorization
    # server "may be hosted with the resource server or a separate entity". Trusting
    # exactly one was never a protocol requirement -- it was this server assuming that
    # everyone who talks to it is already a registered Aura user.
    issuers: tuple[TrustedIssuer, ...]
    # The CANONICAL resource identifier: the one advertised in the protected-resource
    # metadata, which MCP clients also treat as the server's address. It must therefore
    # be a URL the CLIENT can reach.
    resource: str
    # Every resource identifier a token may legitimately carry, canonical first. Empty
    # means "only the canonical one", so a config built literally -- the tests, and any
    # caller that sets `resource` alone -- keeps the single-audience behaviour instead of
    # silently accepting nothing.
    audiences: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls) -> OAuthConfig:
        home = TrustedIssuer.of(
            os.getenv("MCP_OAUTH_ISSUER", "http://localhost:9080"),
            os.getenv("MCP_OAUTH_JWKS_URL", ""),
        )
        audiences = split_audiences(os.getenv("MCP_OAUTH_RESOURCE", DEFAULT_RESOURCE))
        return cls(
            issuers=(home, *parse_trusted_issuers(os.getenv("MCP_OAUTH_TRUSTED_ISSUERS", ""))),
            resource=audiences[0],
            audiences=audiences,
        )

    @property
    def accepted_audiences(self) -> tuple[str, ...]:
        """The audience allow-list, falling back to the canonical resource alone."""
        return self.audiences or (self.resource,)

    @property
    def home(self) -> TrustedIssuer:
        """The authorization server this deployment owns."""
        return self.issuers[0]

    def issuer_named(self, name: object) -> TrustedIssuer | None:
        """Exact match only. An issuer is the root of trust, so prefix or suffix
        tolerance here would let a lookalike host mint identities."""
        if not isinstance(name, str):
            return None
        wanted = name.strip().rstrip("/")
        return next((issuer for issuer in self.issuers if issuer.issuer == wanted), None)

    def tenant_identity(self, issuer: object, subject: object) -> str:
        """Map an authenticated (issuer, subject) pair onto the tenant it may reach.

        RFC 7519 section 4.1.2 guarantees `sub` is unique only WITHIN one issuer's
        namespace. The moment a second issuer is trusted, keying on `sub` alone is not
        merely untidy: a foreign account named after an Aura identity UUID would be
        handed that person's WhatsApp session.

        The home issuer is the exception, deliberately. Its subjects ARE Aura identity
        UUIDs and every tenant store already on disk is named after one, so passing them
        through unchanged means widening the trusted set migrates nothing.

        Foreign subjects fold into a UUIDv5 because normalize_identity requires a UUID.
        A name-based UUID is deterministic (the same person returns to the same tenant),
        collision-resistant, and needs no registry to translate it back.
        """
        if not isinstance(issuer, str) or not isinstance(subject, str):
            raise ValueError("OAuth issuer and subject are required")
        if issuer.strip().rstrip("/") == self.home.issuer:
            return normalize_identity(subject)
        # The separator cannot appear in either half, so no two distinct pairs can be
        # spelled as the same joined string.
        return str(uuid5(FOREIGN_IDENTITY_NAMESPACE, f"{issuer}\n{subject}"))


class JWTTokenVerifier:
    def __init__(self, config: OAuthConfig, jwks_client: Any | None = None):
        self._config = config
        # One key client per issuer. A single shared client would serve whichever issuer
        # asked last, so one issuer's tokens could end up verified against another's
        # keys -- the exact confusion the trusted list is supposed to prevent.
        #
        # jwks_client may be a mapping from issuer to client, which is how a test holds
        # two issuers with genuinely different keys; a bare client stands in for all of
        # them, which is what a single-issuer test wants.
        self._jwks = {
            issuer.issuer: (jwks_client.get(issuer.issuer) if isinstance(jwks_client, dict) else jwks_client)
            or jwt.PyJWKClient(
                issuer.jwks_url,
                cache_keys=True,
                cache_jwk_set=True,
                lifespan=300,
                timeout=5,
            )
            for issuer in config.issuers
        }
        logger.info(
            "OAuth resource verifier configured resource=%s audiences=%s issuers=%s",
            config.resource,
            list(config.accepted_audiences),
            [issuer.issuer for issuer in config.issuers],
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await anyio.to_thread.run_sync(self._decode, token)
            subject = self._config.tenant_identity(claims["iss"], claims["sub"])
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
        issuer = self._trusted_issuer_of(token)
        signing_key = self._jwks[issuer.issuer].get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key,
            algorithms=list(SUPPORTED_JWT_ALGORITHMS),
            # PyJWT accepts an iterable and requires the token to name ANY of them
            # (api_jwt._validate_aud), which is exactly the intersection rule this list
            # is for. A token carrying no `aud` still fails: it is required just below,
            # and a bearer bound to nothing is replayable against every resource that
            # trusts this issuer.
            audience=list(self._config.accepted_audiences),
            issuer=issuer.issuer,
            options={"require": ["exp", "iss", "aud", "sub", "scope", "client_id"]},
        )

    def _trusted_issuer_of(self, token: str) -> TrustedIssuer:
        """Read `iss` WITHOUT verifying it, purely to decide which key set to verify
        against -- there is no way to pick a JWKS before knowing who claims to have
        signed the token.

        Nothing is trusted on the strength of this read: _decode then pins `issuer=` to
        the matched entry, so a token that names one issuer and was signed by another
        fails there.
        """
        claimed = jwt.decode(token, options={"verify_signature": False}).get("iss")
        issuer = self._config.issuer_named(claimed)
        if issuer is None:
            raise jwt.InvalidIssuerError(f"issuer {claimed!r} is not trusted")
        return issuer


def auth_settings(config: OAuthConfig) -> AuthSettings:
    return AuthSettings(
        issuer_url=config.home.issuer,
        resource_server_url=config.resource,
        required_scopes=[MCP_TOOLS_SCOPE],
    )
