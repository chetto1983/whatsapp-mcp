"""Aura identity tenancy shared by the MCP tools and the bridge gateway."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import UUID

from mcp.server.context import CallNext, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS

AURA_IDENTITY_HEADER = "X-Aura-Identity"
_identity: ContextVar[str | None] = ContextVar("aura_whatsapp_identity", default=None)


def normalize_identity(value: object) -> str:
    """Return a canonical UUID or reject the caller-provided identity."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("_meta.aura.user_identifier is required")
    try:
        return str(UUID(value.strip()))
    except ValueError as exc:
        raise ValueError("_meta.aura.user_identifier must be a UUID") from exc


def _as_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    root = getattr(value, "root", None)
    return root if isinstance(root, Mapping) else {}


def identity_from_meta(meta: object) -> str:
    aura = _as_mapping(meta).get("aura")
    return normalize_identity(_as_mapping(aura).get("user_identifier"))


def current_identity() -> str:
    identity = _identity.get()
    if identity is None:
        raise RuntimeError("Aura tenant context is not active")
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
    """A path-like value resolved from the active request identity."""

    def __init__(self, filename: str):
        self.filename = filename

    def __fspath__(self) -> str:
        return str(tenant_store() / self.filename)

    def __str__(self) -> str:
        return self.__fspath__()


class AuraIdentityMiddleware:
    """Require and bind Aura identity metadata for every tool invocation."""

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext):
        if ctx.method != "tools/call":
            return await call_next(ctx)
        try:
            identity = identity_from_meta(ctx.meta)
        except ValueError as exc:
            raise MCPError(code=INVALID_PARAMS, message=str(exc)) from exc
        with tenant_scope(identity):
            return await call_next(ctx)
