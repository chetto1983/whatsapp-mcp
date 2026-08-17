"""Tests for MCP transport selection."""

import pytest

from mcp_config import (
    resolve_host,
    resolve_port,
    resolve_run_kwargs,
    resolve_stateless,
    resolve_transport,
    resolve_transport_security,
)


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


class TestResolveStateless:
    """The 2026-07-28 core is stateless; this server keeps no per-session state."""

    @pytest.mark.parametrize("value", [None, "", "   ", "1", "true", "yes", "anything"])
    def test_defaults_to_stateless(self, value):
        assert resolve_stateless(value) is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", " no ", "off"])
    def test_recognised_false_words_opt_out(self, value):
        assert resolve_stateless(value) is False


class TestResolveRunKwargs:
    """`MCPServer.run()` is overloaded per transport and rejects arguments the
    transport does not take, so the mapping is resolved before the call."""

    def test_stdio_takes_nothing(self):
        assert resolve_run_kwargs("stdio", host="0.0.0.0", port="9000", stateless="false") == {}

    def test_streamable_http_is_stateless_by_default(self):
        kwargs = resolve_run_kwargs("streamable-http", host="0.0.0.0", port="9000")

        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 9000
        assert kwargs["stateless_http"] is True
        assert kwargs["transport_security"].enable_dns_rebinding_protection is True

    def test_streamable_http_can_be_put_back_on_sessions(self):
        assert resolve_run_kwargs("streamable-http", stateless="false")["stateless_http"] is False

    def test_sse_never_receives_stateless_http(self):
        """`stateless_http` belongs to streamable-http alone; passing it to the sse
        overload is a TypeError at launch, which is the worst place to find out."""
        kwargs = resolve_run_kwargs("sse", host="127.0.0.1", port="8000")

        assert "stateless_http" not in kwargs
        assert kwargs["port"] == 8000

    def test_the_bind_host_drives_the_allow_list(self):
        kwargs = resolve_run_kwargs("streamable-http", host="0.0.0.0")

        assert "aura-whatsapp:*" in kwargs["transport_security"].allowed_hosts

    def test_a_bad_port_still_raises(self):
        with pytest.raises(ValueError, match="Invalid WHATSAPP_MCP_PORT"):
            resolve_run_kwargs("streamable-http", port="not-a-number")
