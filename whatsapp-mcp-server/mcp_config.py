"""Side-effect-free helpers for MCP server configuration env vars."""

from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

# Accepted WHATSAPP_MCP_TRANSPORT values mapped to MCPServer transport names.
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
    """Map a WHATSAPP_MCP_TRANSPORT value to an MCPServer transport name.

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


def resolve_stateless(value: str | None) -> bool:
    """Parse WHATSAPP_MCP_STATELESS, defaulting to True.

    The 2026-07-28 revision made the protocol core stateless: no `initialize`
    handshake to pin a session, no `Mcp-Session-Id` header, so a server can sit
    behind a plain round-robin load balancer. This server has no per-session
    state to keep — every tool reads SQLite or calls the bridge — so stateless is
    the honest default, and the env var exists only to put a pre-2026 host back
    on the session-bearing path.

    Anything other than a recognised false-ish word is True.
    """
    return (value or "").strip().lower() not in ("0", "false", "no", "off")


def resolve_run_kwargs(
    transport: str,
    *,
    host: str | None = None,
    port: str | None = None,
    allowed_hosts: str | None = None,
    allowed_origins: str | None = None,
    stateless: str | None = None,
) -> dict[str, Any]:
    """Build the keyword arguments for `MCPServer.run()` on a given transport.

    `run()` is overloaded per transport and rejects arguments the transport does
    not take: stdio accepts none at all, and `stateless_http` belongs to
    streamable-http alone. Resolving that here keeps the launch block a single
    call and makes the mapping testable without starting a server.

    Raises:
        ValueError: If the host/port/stateless values are unusable.
    """
    if transport == "stdio":
        return {}
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
    if transport == "streamable-http":
        kwargs["stateless_http"] = resolve_stateless(stateless)
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
