"""Tests for MCP transport selection."""

import pytest

from mcp_config import resolve_host, resolve_port, resolve_transport, resolve_transport_security


class TestResolveTransport:
    """Tests for resolve_transport()."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "stdio"),
            ("", "stdio"),
            ("   ", "stdio"),
            ("\t\n", "stdio"),
            ("  STDIO ", "stdio"),
            ("http", "streamable-http"),
            ("Http", "streamable-http"),
            ("streamable-http", "streamable-http"),
            ("streamable_http", "streamable-http"),
            ("sse", "sse"),
        ],
    )
    def test_valid_values(self, value, expected):
        assert resolve_transport(value) == expected

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError, match="Invalid WHATSAPP_MCP_TRANSPORT"):
            resolve_transport("websocket")


class TestResolveHost:
    """Tests for resolve_host()."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "127.0.0.1"),
            ("", "127.0.0.1"),
            ("   ", "127.0.0.1"),
            ("\t\n", "127.0.0.1"),
            (" 127.0.0.1 ", "127.0.0.1"),
            ("0.0.0.0", "0.0.0.0"),
        ],
    )
    def test_values(self, value, expected):
        assert resolve_host(value) == expected


class TestResolvePort:
    """Tests for resolve_port()."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, 8000),
            ("", 8000),
            ("   ", 8000),
            ("\t\n", 8000),
            ("9000", 9000),
            (" 9000 ", 9000),
            ("1", 1),
            ("65535", 65535),
        ],
    )
    def test_valid_values(self, value, expected):
        assert resolve_port(value) == expected

    def test_non_integer_raises(self):
        with pytest.raises(ValueError, match="Invalid WHATSAPP_MCP_PORT"):
            resolve_port("not-a-number")

    def test_out_of_range_raises(self):
        for value in ("0", "-1", "65536"):
            with pytest.raises(ValueError, match="Invalid WHATSAPP_MCP_PORT"):
                resolve_port(value)


class TestResolveTransportSecurity:
    """Tests for the network transport host/origin allow-list."""

    def test_localhost_host_allows_loopback_only(self):
        settings = resolve_transport_security("127.0.0.1")

        assert settings.enable_dns_rebinding_protection is True
        assert settings.allowed_hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        assert "whatsapp:*" not in settings.allowed_hosts

    def test_wildcard_bind_allows_compose_service_names(self):
        settings = resolve_transport_security("0.0.0.0")

        assert settings.allowed_hosts == [
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "whatsapp:*",
            "aura-whatsapp:*",
        ]
        assert "http://whatsapp:*" in settings.allowed_origins
        assert "http://aura-whatsapp:*" in settings.allowed_origins

    def test_custom_allowed_hosts_and_origins_override_defaults(self):
        settings = resolve_transport_security(
            "0.0.0.0",
            allowed_hosts="mcp.local:*, whatsapp.internal:8080,",
            allowed_origins="https://app.example, http://localhost:9080",
        )

        assert settings.allowed_hosts == ["mcp.local:*", "whatsapp.internal:8080"]
        assert settings.allowed_origins == ["https://app.example", "http://localhost:9080"]
