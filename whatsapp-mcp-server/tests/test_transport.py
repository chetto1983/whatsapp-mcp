import pytest

from mcp_config import (
    COMPOSE_ALLOWED_HOSTS,
    COMPOSE_ALLOWED_ORIGINS,
    DEFAULT_MCP_HOST,
    DEFAULT_MCP_PORT,
    resolve_host,
    resolve_port,
    resolve_run_kwargs,
    resolve_transport,
    resolve_transport_security,
)


@pytest.mark.parametrize("value", [None, "", "http", "streamable-http", "streamable_http"])
def test_remote_transport_aliases(value):
    assert resolve_transport(value) == "streamable-http"


@pytest.mark.parametrize("value", ["stdio", "sse", "websocket", "bogus"])
def test_non_remote_or_legacy_transports_are_rejected(value):
    with pytest.raises(ValueError, match="remote-only"):
        resolve_transport(value)


def test_host_and_port_defaults():
    assert resolve_host(None) == DEFAULT_MCP_HOST
    assert resolve_port(None) == DEFAULT_MCP_PORT


@pytest.mark.parametrize("value", ["0", "65536", "abc"])
def test_invalid_ports_are_rejected(value):
    with pytest.raises(ValueError, match="WHATSAPP_MCP_PORT"):
        resolve_port(value)


def test_run_kwargs_are_always_current_stateless_http():
    kwargs = resolve_run_kwargs("streamable-http", host="127.0.0.1", port="8765")
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8765
    assert kwargs["stateless_http"] is True


def test_run_kwargs_reject_unknown_internal_transport():
    with pytest.raises(ValueError, match="unsupported remote MCP transport"):
        resolve_run_kwargs("stdio")


def test_localhost_transport_security_is_rebinding_safe():
    settings = resolve_transport_security("127.0.0.1")
    assert settings.enable_dns_rebinding_protection is True
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "http://127.0.0.1:*" in settings.allowed_origins


def test_compose_bind_adds_only_known_service_names():
    settings = resolve_transport_security("0.0.0.0")
    assert set(COMPOSE_ALLOWED_HOSTS).issubset(settings.allowed_hosts)
    assert set(COMPOSE_ALLOWED_ORIGINS).issubset(settings.allowed_origins)


def test_explicit_security_lists_replace_defaults():
    settings = resolve_transport_security(
        "0.0.0.0",
        allowed_hosts="mcp.local:*, whatsapp.internal:8080,",
        allowed_origins="https://mcp.local,",
    )
    assert settings.allowed_hosts == ["mcp.local:*", "whatsapp.internal:8080"]
    assert settings.allowed_origins == ["https://mcp.local"]
