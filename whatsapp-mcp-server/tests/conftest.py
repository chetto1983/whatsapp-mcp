import sqlite3
from contextlib import closing

import pytest

import whatsapp_actions
from tenant_context import tenant_scope, tenant_store

TEST_IDENTITY = "11111111-1111-4111-8111-111111111111"
TEST_BRIDGE_TOKEN = "bridge-token-for-tests"


@pytest.fixture(autouse=True)
def tenant_context(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_STORE_ROOT", str(tmp_path / "whatsapp-root"))
    monkeypatch.setenv("WHATSAPP_BRIDGE_TOKEN", TEST_BRIDGE_TOKEN)
    with tenant_scope(TEST_IDENTITY):
        yield


@pytest.fixture
def seed_media():
    """Write one message row into a tenant's messages.db, the columns the bridge fills."""

    def seed(identity: str, message_id: str, chat_jid: str, media_type: str | None, filename: str | None = None):
        path = tenant_store(identity) / "messages.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP, is_from_me BOOLEAN, "
                "media_type TEXT, filename TEXT, PRIMARY KEY (id, chat_jid))"
            )
            conn.execute(
                "INSERT INTO messages VALUES (?, ?, ?, '', '2026-09-24 10:00:00', 0, ?, ?)",
                (message_id, chat_jid, chat_jid, media_type, filename),
            )

    return seed


@pytest.fixture
def bridge_download(tmp_path, monkeypatch):
    """Stand in for the bridge's /api/download. `place(blob)` makes it answer with a
    file holding `blob`, named `.jpg` the way the bridge names every image; None
    makes the download fail. Returns the list of requests it receives."""
    calls: list[tuple[str, str]] = []

    def place(blob: bytes | None) -> list[tuple[str, str]]:
        path = tmp_path / "bridge-download.jpg"
        if blob is not None:
            path.write_bytes(blob)

        def download(message_id: str, chat_jid: str) -> str | None:
            calls.append((message_id, chat_jid))
            return str(path) if blob is not None else None

        monkeypatch.setattr(whatsapp_actions, "download_media", download)
        return calls

    return place
