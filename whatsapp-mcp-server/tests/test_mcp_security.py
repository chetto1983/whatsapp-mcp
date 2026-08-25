import pytest

from mcp_security import ServiceTokenVerifier, service_token


def test_service_token_is_required(monkeypatch):
    monkeypatch.delenv("WHATSAPP_MCP_SERVICE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="WHATSAPP_MCP_SERVICE_TOKEN is required"):
        service_token()


@pytest.mark.asyncio
async def test_service_token_verifier_accepts_only_exact_token(monkeypatch):
    monkeypatch.setenv("WHATSAPP_MCP_SERVICE_TOKEN", "remote-mcp-token-for-tests")
    verifier = ServiceTokenVerifier()

    accepted = await verifier.verify_token("remote-mcp-token-for-tests")
    assert accepted is not None
    assert accepted.client_id == "aura"
    assert await verifier.verify_token("remote-mcp-token-for-testx") is None
