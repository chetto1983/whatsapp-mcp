import base64
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from mcp_security import MCP_TOOLS_SCOPE, JWTTokenVerifier, OAuthConfig, auth_settings

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
    config = OAuthConfig(issuer=ISSUER, jwks_url="https://auth.example/jwks", resource=RESOURCE)
    accepted = await JWTTokenVerifier(config, StaticJWKClient(key)).verify_token(signed_token(key))

    assert accepted is not None
    assert accepted.client_id == "remote-client"
    assert accepted.subject == TENANT
    assert accepted.scopes == [MCP_TOOLS_SCOPE]


@pytest.mark.asyncio
async def test_verifier_accepts_standard_rsa_authorization_server_token():
    key = generate_private_key(public_exponent=65537, key_size=2048)
    config = OAuthConfig(issuer=ISSUER, jwks_url="https://auth.example/jwks", resource=RESOURCE)
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
    config = OAuthConfig(issuer=ISSUER, jwks_url="https://auth.example/jwks", resource=RESOURCE)
    assert await JWTTokenVerifier(config, StaticJWKClient(key)).verify_token(signed_token(key, **overrides)) is None


def test_auth_settings_publish_generic_resource_contract():
    config = OAuthConfig(issuer=ISSUER, jwks_url="https://auth.example/jwks", resource=RESOURCE)
    settings = auth_settings(config)

    assert str(settings.issuer_url) == ISSUER
    assert str(settings.resource_server_url) == RESOURCE
    assert settings.required_scopes == [MCP_TOOLS_SCOPE]
