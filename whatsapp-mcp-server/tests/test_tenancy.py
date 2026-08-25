import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.shared.exceptions import MCPError

import tenant_context
import whatsapp
from store_migration import migrate_singleton_store
from tenant_context import (
    AuraIdentityMiddleware,
    TenantFile,
    current_identity,
    identity_from_meta,
    normalize_identity,
    tenant_scope,
    tenant_store,
)

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _seed_chat(identity: str, name: str) -> Path:
    with tenant_scope(identity):
        path = tenant_store() / "messages.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP);
                CREATE TABLE messages (
                    id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP,
                    is_from_me BOOLEAN, media_type TEXT, quoted_message_id TEXT, filename TEXT
                );
                """
            )
            conn.execute("INSERT INTO chats VALUES (?, ?, ?)", (f"{name}@s.whatsapp.net", name, None))
        return path


def test_identity_is_canonical_and_only_read_from_meta():
    assert normalize_identity(TENANT_A.upper()) == TENANT_A
    assert identity_from_meta({"aura": {"user_identifier": TENANT_A}}) == TENANT_A
    with pytest.raises(ValueError, match="required"):
        identity_from_meta({})
    with pytest.raises(ValueError, match="UUID"):
        identity_from_meta({"aura": {"user_identifier": "alice"}})


def test_tenant_file_has_no_context_fallback():
    path = TenantFile("messages.db")
    with tenant_scope(TENANT_A):
        assert Path(path) == tenant_store(TENANT_A) / "messages.db"
    token = tenant_context._identity.set(None)
    try:
        with pytest.raises(RuntimeError, match="tenant context is not active"):
            Path(path)
    finally:
        tenant_context._identity.reset(token)


@pytest.mark.asyncio
async def test_middleware_binds_identity_for_tool_call():
    middleware = AuraIdentityMiddleware()
    ctx = SimpleNamespace(method="tools/call", meta={"aura": {"user_identifier": TENANT_B}})

    async def call_next(_ctx):
        return {"identity": current_identity()}

    assert await middleware(ctx, call_next) == {"identity": TENANT_B}


@pytest.mark.asyncio
async def test_middleware_rejects_missing_identity_before_tool():
    middleware = AuraIdentityMiddleware()
    ctx = SimpleNamespace(method="tools/call", meta=None)
    called = False

    async def call_next(_ctx):
        nonlocal called
        called = True

    with pytest.raises(MCPError, match="user_identifier is required"):
        await middleware(ctx, call_next)
    assert called is False


def test_sqlite_queries_are_isolated_between_tenants():
    path_a = _seed_chat(TENANT_A, "alice")
    path_b = _seed_chat(TENANT_B, "bob")
    assert path_a != path_b

    with tenant_scope(TENANT_A):
        assert [chat["name"] for chat in whatsapp.list_chats()] == ["alice"]
    with tenant_scope(TENANT_B):
        assert [chat["name"] for chat in whatsapp.list_chats()] == ["bob"]


def test_singleton_migration_requires_explicit_owner(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "messages.db").write_bytes(b"sqlite")

    with pytest.raises(RuntimeError, match="MIGRATION_TENANT_ID"):
        migrate_singleton_store(root, None)
    assert (root / "messages.db").exists()


def test_singleton_migration_moves_the_complete_store(tmp_path):
    root = tmp_path / "root"
    (root / "chat").mkdir(parents=True)
    (root / "messages.db").write_bytes(b"messages")
    (root / "whatsapp.db").write_bytes(b"whatsmeow")
    (root / ".bridge-token").write_text("retired-token")
    (root / "chat" / "image.jpg").write_bytes(b"image")

    assert migrate_singleton_store(root, TENANT_A) is True
    target = root / "tenants" / TENANT_A / "store"
    assert not (root / "messages.db").exists()
    assert (target / "messages.db").read_bytes() == b"messages"
    assert (target / "whatsapp.db").read_bytes() == b"whatsmeow"
    assert (target / "chat" / "image.jpg").read_bytes() == b"image"
    assert not (target / ".bridge-token").exists()


def test_singleton_migration_never_merges(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "messages.db").write_bytes(b"legacy")
    target = root / "tenants" / TENANT_A / "store"
    target.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="refusing to merge"):
        migrate_singleton_store(root, TENANT_A)
