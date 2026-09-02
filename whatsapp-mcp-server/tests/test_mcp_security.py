import base64
import json
import time
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from mcp_security import MCP_TOOLS_SCOPE, JWTTokenVerifier, OAuthConfig, TrustedIssuer, auth_settings

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ISSUER = "https://auth.example"
RESOURCE = "https://mcp.example/mcp/"


class StaticJWKClient:
    def __init__(self, key, algorithm="EdDSA"):
        if algorithm == "EdDSA":
            public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            encoded = base64.urlsafe_b64encode(public).rstrip(b"=").decode()
            jwk = {"kty": "OKP", "crv": "Ed25519", "x": encoded}
        else:
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update({"kid": "test", "alg": algorithm, "use": "sig"})
        self.signing_key = jwt.PyJWK.from_dict(jwk)

    def get_signing_key_from_jwt(self, _token):
        return self.signing_key


def signed_token(key, algorithm="EdDSA", **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": RESOURCE,
        "exp": now + 300,
        "scope": MCP_TOOLS_SCOPE,
        "client_id": "remote-client",
        "sub": TENANT,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "test"})


@pytest.mark.asyncio
async def test_verifier_accepts_audience_bound_oauth_token():
    key = Ed25519PrivateKey.generate()
    config = OAuthConfig(
        issuers=(TrustedIssuer(issuer=ISSUER, jwks_url="https://auth.example/jwks"),), resource=RESOURCE
    )
    accepted = await JWTTokenVerifier(config, StaticJWKClient(key)).verify_token(signed_token(key))

    assert accepted is not None
    assert accepted.client_id == "remote-client"
    assert accepted.subject == TENANT
    assert accepted.scopes == [MCP_TOOLS_SCOPE]


@pytest.mark.asyncio
async def test_verifier_accepts_standard_rsa_authorization_server_token():
    key = generate_private_key(public_exponent=65537, key_size=2048)
    config = OAuthConfig(
        issuers=(TrustedIssuer(issuer=ISSUER, jwks_url="https://auth.example/jwks"),), resource=RESOURCE
    )
    token = signed_token(key, algorithm="RS256")

    accepted = await JWTTokenVerifier(config, StaticJWKClient(key, "RS256")).verify_token(token)

    assert accepted is not None
    assert accepted.subject == TENANT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://issuer.invalid"},
        {"aud": "http://foreign.invalid/mcp/"},
        {"exp": 1},
        {"sub": "not-a-uuid"},
    ],
)
async def test_verifier_rejects_invalid_token_claims(overrides):
    key = Ed25519PrivateKey.generate()
    config = OAuthConfig(
        issuers=(TrustedIssuer(issuer=ISSUER, jwks_url="https://auth.example/jwks"),), resource=RESOURCE
    )
    assert await JWTTokenVerifier(config, StaticJWKClient(key)).verify_token(signed_token(key, **overrides)) is None


def test_auth_settings_publish_generic_resource_contract():
    config = OAuthConfig(
        issuers=(TrustedIssuer(issuer=ISSUER, jwks_url="https://auth.example/jwks"),), resource=RESOURCE
    )
    settings = auth_settings(config)

    assert str(settings.issuer_url) == ISSUER
    assert str(settings.resource_server_url) == RESOURCE
    assert settings.required_scopes == [MCP_TOOLS_SCOPE]


# --- More than one authorization server -------------------------------------
#
# These exist in both directions on purpose: a trusted issuer must get in, and
# everything that merely LOOKS like one must not.

FOREIGN_ISSUER = "https://foreign.example"


def foreign_token(key, algorithm="EdDSA", issuer=FOREIGN_ISSUER, **overrides):
    return signed_token(key, algorithm=algorithm, iss=issuer, **overrides)


def two_issuer_config():
    return OAuthConfig(
        issuers=(
            TrustedIssuer(issuer=ISSUER, jwks_url="https://auth.example/jwks"),
            TrustedIssuer(issuer=FOREIGN_ISSUER, jwks_url="https://foreign.example/jwks"),
        ),
        resource=RESOURCE,
    )


@pytest.mark.asyncio
async def test_a_foreign_account_named_after_a_tenant_does_not_get_that_tenant():
    """The attack the (issuer, subject) key prevents. RFC 7519 promises `sub` is unique
    only within ONE issuer's namespace, so nothing stops a foreign account from being
    named after an Aura identity -- keying on `sub` alone would hand it that session."""
    home_key = Ed25519PrivateKey.generate()
    foreign_key = Ed25519PrivateKey.generate()
    config = two_issuer_config()
    clients = {ISSUER: StaticJWKClient(home_key), FOREIGN_ISSUER: StaticJWKClient(foreign_key)}
    verifier = JWTTokenVerifier(config, clients)

    from_home = await verifier.verify_token(signed_token(home_key))
    from_foreign = await verifier.verify_token(foreign_token(foreign_key))

    assert from_home is not None and from_foreign is not None
    assert from_home.subject == TENANT, "the home subject stopped passing through"
    assert from_foreign.subject != TENANT, "a foreign account reached the tenant of the same name"
    # And the foreign one must still be a usable tenant, or "different" just means broken.
    from tenant_context import normalize_identity

    assert normalize_identity(from_foreign.subject) == from_foreign.subject


@pytest.mark.asyncio
async def test_an_unlisted_issuer_is_refused_even_with_a_good_signature():
    key = Ed25519PrivateKey.generate()
    config = OAuthConfig(
        issuers=(TrustedIssuer(issuer=ISSUER, jwks_url="https://auth.example/jwks"),), resource=RESOURCE
    )
    stranger = foreign_token(key, issuer="https://stranger.example")

    assert await JWTTokenVerifier(config, StaticJWKClient(key)).verify_token(stranger) is None


@pytest.mark.asyncio
async def test_claiming_an_issuer_is_not_being_one():
    """The issuer is read unverified to pick a key set. That read must buy nothing else:
    a token naming the home issuer but signed by the foreign key has to fail."""
    home_key = Ed25519PrivateKey.generate()
    foreign_key = Ed25519PrivateKey.generate()
    config = two_issuer_config()
    clients = {ISSUER: StaticJWKClient(home_key), FOREIGN_ISSUER: StaticJWKClient(foreign_key)}

    forged = signed_token(foreign_key)  # iss = home, signed with the foreign key
    assert await JWTTokenVerifier(config, clients).verify_token(forged) is None


def test_foreign_identities_are_stable_uuids():
    config = two_issuer_config()
    first = config.tenant_identity(FOREIGN_ISSUER, "1043")
    assert first == config.tenant_identity(FOREIGN_ISSUER, "1043"), "the same caller derived two identities"
    assert UUID(first)  # the tenant store is specified over UUIDs
    assert first != config.tenant_identity(FOREIGN_ISSUER, "10430"), "two subjects collided"
    assert first != config.tenant_identity("https://other.example", "1043"), "two issuers collided"


def test_trusted_issuers_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("MCP_OAUTH_ISSUER", "https://home.example/")
    monkeypatch.setenv("MCP_OAUTH_JWKS_URL", "http://aura:9080/oauth/jwks")
    monkeypatch.setenv(
        "MCP_OAUTH_TRUSTED_ISSUERS",
        " https://accounts.google.com=https://www.googleapis.com/oauth2/v3/certs , https://kc.example/realms/aura ,, ",
    )
    monkeypatch.setenv("MCP_OAUTH_RESOURCE", RESOURCE)

    config = OAuthConfig.from_environment()

    assert config.issuers == (
        # The home issuer keeps its split-horizon JWKS: the issuer is the name a client
        # reaches, the JWKS the name this container reaches.
        TrustedIssuer("https://home.example", "http://aura:9080/oauth/jwks"),
        TrustedIssuer("https://accounts.google.com", "https://www.googleapis.com/oauth2/v3/certs"),
        # No `=`, so the default path applies -- the same rule the home issuer follows.
        TrustedIssuer("https://kc.example/realms/aura", "https://kc.example/realms/aura/oauth/jwks"),
    )
