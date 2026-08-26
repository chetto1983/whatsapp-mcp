"""Tenant context shared by OAuth-protected MCP tools and the bridge gateway."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import UUID

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import CallNext, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS

TENANT_ID_HEADER = "X-Tenant-ID"
_identity: ContextVar[str | None] = ContextVar("whatsapp_tenant", default=None)


def normalize_identity(value: object) -> str:
    """Return a canonical UUID suitable for a tenant store path."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("OAuth subject is required")
    try:
        return str(UUID(value.strip()))
    except ValueError as exc:
        raise ValueError("OAuth subject must be a UUID") from exc


def current_identity() -> str:
    identity = _identity.get()
    if identity is None:
        raise RuntimeError("tenant context is not active")
    return identity


@contextmanager
def tenant_scope(identity: str) -> Iterator[str]:
    canonical = normalize_identity(identity)
    token = _identity.set(canonical)
    try:
        yield canonical
    finally:
        _identity.reset(token)


def store_root() -> Path:
    configured = os.getenv("WHATSAPP_STORE_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    return (Path(__file__).resolve().parent.parent / "whatsapp-bridge" / "store").resolve()


def tenant_store(identity: str | None = None) -> Path:
    canonical = normalize_identity(identity) if identity is not None else current_identity()
    return store_root() / "tenants" / canonical / "store"


class TenantFile(os.PathLike[str]):
    """A path-like value resolved from the active request tenant."""

    def __init__(self, filename: str):
        self.filename = filename

    def __fspath__(self) -> str:
        return str(tenant_store() / self.filename)

    def __str__(self) -> str:
        return self.__fspath__()


class SubjectTenantMiddleware:
    """Bind each tool call to the authenticated OAuth subject."""

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext):
        if ctx.method != "tools/call":
            return await call_next(ctx)
        try:
            access_token = get_access_token()
            if access_token is None:
                raise ValueError("authenticated OAuth subject is required")
            identity = normalize_identity(access_token.subject)
        except (TypeError, ValueError) as exc:
            raise MCPError(code=INVALID_PARAMS, message=str(exc)) from exc
        with tenant_scope(identity):
            return await call_next(ctx)
