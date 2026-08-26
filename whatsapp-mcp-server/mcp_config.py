"""Side-effect-free helpers for MCP server configuration env vars."""

from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

# Accepted WHATSAPP_MCP_TRANSPORT values mapped to MCPServer transport names.
# "http" is a friendly alias for the spec's current "streamable-http" transport.
TRANSPORT_ALIASES = {
    "http": "streamable-http",
    "streamable-http": "streamable-http",
    "streamable_http": "streamable-http",
}
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8000
LOCALHOST_ALLOWED_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
LOCALHOST_ALLOWED_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")
COMPOSE_ALLOWED_HOSTS = ("whatsapp:*",)
COMPOSE_ALLOWED_ORIGINS = ("http://whatsapp:*",)


def resolve_transport(value: str | None) -> str:
    """Map a WHATSAPP_MCP_TRANSPORT value to an MCPServer transport name.

    Unset or whitespace-only values default to Streamable HTTP.
    Raises ValueError for unrecognized values.
    """
    normalized = (value or "").strip().lower() or "http"
    try:
        return TRANSPORT_ALIASES[normalized]
    except KeyError:
        accepted = ", ".join(sorted(TRANSPORT_ALIASES))
        raise ValueError(
            f"Invalid WHATSAPP_MCP_TRANSPORT={value!r}; this fork is remote-only "
            f"(accepted Streamable HTTP inputs: {accepted})"
        ) from None


def resolve_host(value: str | None) -> str:
    """Parse WHATSAPP_MCP_HOST, defaulting to DEFAULT_MCP_HOST."""
    return (value or "").strip() or DEFAULT_MCP_HOST


def resolve_port(value: str | None) -> int:
    """Parse WHATSAPP_MCP_PORT, defaulting to DEFAULT_MCP_PORT.

    Unset or whitespace-only values default to DEFAULT_MCP_PORT.
    Raises ValueError for non-integer or out-of-range values.
    """
    value = (value or "").strip()
    if not value:
        return DEFAULT_MCP_PORT
    try:
        port = int(value)
    except ValueError:
        raise ValueError(f"Invalid WHATSAPP_MCP_PORT={value!r}; must be an integer") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid WHATSAPP_MCP_PORT={value!r}; must be between 1 and 65535") from None
    return port


def _split_csv(value: str | None) -> list[str]:
    """Parse a comma-separated env var, dropping blanks while preserving order."""
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_run_kwargs(
    transport: str,
    *,
    host: str | None = None,
    port: str | None = None,
    allowed_hosts: str | None = None,
    allowed_origins: str | None = None,
) -> dict[str, Any]:
    """Build the keyword arguments for `MCPServer.run()` on a given transport.

    This fork exposes the current stateless Streamable HTTP transport only.

    Raises:
        ValueError: If the host/port/stateless values are unusable.
    """
    if transport != "streamable-http":
        raise ValueError(f"unsupported remote MCP transport: {transport}")
    resolved_host = resolve_host(host)
    kwargs: dict[str, Any] = {
        "host": resolved_host,
        "port": resolve_port(port),
        "transport_security": resolve_transport_security(
            resolved_host,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    }
    kwargs["stateless_http"] = True
    return kwargs


def resolve_transport_security(
    host: str,
    allowed_hosts: str | None = None,
    allowed_origins: str | None = None,
) -> TransportSecuritySettings:
    """Build transport-security settings for the network transports.

    The server enables DNS rebinding protection with a localhost allow-list by
    default. This app resolves WHATSAPP_MCP_HOST at launch time, so the
    allow-list must be built after the final bind host is known.
    """
    hosts = _split_csv(allowed_hosts)
    if not hosts:
        hosts = list(LOCALHOST_ALLOWED_HOSTS)
        if host in ("0.0.0.0", "::"):
            hosts.extend(COMPOSE_ALLOWED_HOSTS)
        elif host not in ("127.0.0.1", "localhost", "::1"):
            hosts.append(f"{host}:*")

    origins = _split_csv(allowed_origins)
    if not origins:
        origins = list(LOCALHOST_ALLOWED_ORIGINS)
        if host in ("0.0.0.0", "::"):
            origins.extend(COMPOSE_ALLOWED_ORIGINS)
        elif host not in ("127.0.0.1", "localhost", "::1"):
            origins.extend((f"http://{host}:*", f"https://{host}:*"))

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )
