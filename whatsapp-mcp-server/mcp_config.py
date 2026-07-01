"""Side-effect-free helpers for MCP server configuration env vars."""

from mcp.server.transport_security import TransportSecuritySettings

# Accepted WHATSAPP_MCP_TRANSPORT values mapped to FastMCP transport names.
# "http" is a friendly alias for the spec's current "streamable-http" transport.
TRANSPORT_ALIASES = {
    "stdio": "stdio",
    "http": "streamable-http",
    "streamable-http": "streamable-http",
    "streamable_http": "streamable-http",
    "sse": "sse",
}
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8000
LOCALHOST_ALLOWED_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
LOCALHOST_ALLOWED_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")
COMPOSE_ALLOWED_HOSTS = ("whatsapp:*", "aura-whatsapp:*")
COMPOSE_ALLOWED_ORIGINS = ("http://whatsapp:*", "http://aura-whatsapp:*")


def resolve_transport(value: str | None) -> str:
    """Map a WHATSAPP_MCP_TRANSPORT value to a FastMCP transport name.

    Unset or whitespace-only values default to "stdio".
    Raises ValueError for unrecognized values.
    """
    normalized = (value or "").strip().lower() or "stdio"
    try:
        return TRANSPORT_ALIASES[normalized]
    except KeyError:
        accepted = ", ".join(sorted(TRANSPORT_ALIASES))
        raise ValueError(
            f"Invalid WHATSAPP_MCP_TRANSPORT={value!r}; recommended values: stdio, http, sse "
            f"(http maps to the spec's streamable-http transport; all accepted inputs: {accepted})"
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


def resolve_transport_security(
    host: str,
    allowed_hosts: str | None = None,
    allowed_origins: str | None = None,
) -> TransportSecuritySettings:
    """Build FastMCP transport-security settings for network transports.

    FastMCP enables DNS rebinding protection when constructed with the default
    localhost host. This app resolves WHATSAPP_MCP_HOST at launch time, so the
    allow-list must be refreshed after the final bind host is known.
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
