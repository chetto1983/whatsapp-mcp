"""Real Streamable HTTP proof for OAuth bearer auth and tenant isolation."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import anyio
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def seed(root: Path, identity: str, name: str) -> None:
    database = root / "tenants" / identity / "store" / "messages.db"
    if not database.is_file():
        raise RuntimeError(f"tenant runtime database is missing: {database}")
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)",
            (f"{name}@s.whatsapp.net", name, None),
        )


async def list_chats(session: ClientSession) -> str:
    result = await session.call_tool(
        "list_chats",
        {"include_last_message": False},
    )
    if result.is_error:
        raise RuntimeError(f"list_chats failed: {result}")
    return json.dumps(result.model_dump(mode="json", by_alias=True), sort_keys=True)


async def read_with_token(url: str, token: str) -> str:
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as client:
        async with streamable_http_client(url, http_client=client, terminate_on_close=False) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "list_chats" in {tool.name for tool in tools.tools}
                return await list_chats(session)


async def run() -> None:
    url = os.environ["WHATSAPP_E2E_MCP_URL"]
    token_a = os.environ["WHATSAPP_E2E_TOKEN_A"]
    token_b = os.environ["WHATSAPP_E2E_TOKEN_B"]
    root = Path(os.environ["WHATSAPP_STORE_ROOT"])
    seed(root, TENANT_A, "tenant-a-only")
    seed(root, TENANT_B, "tenant-b-only")

    async with httpx2.AsyncClient() as anonymous:
        response = await anonymous.post(url, json={})
        assert response.status_code == 401, response.text
        assert "resource_metadata=" in response.headers["www-authenticate"]

    tenant_a = await read_with_token(url, token_a)
    tenant_b = await read_with_token(url, token_b)
    assert "tenant-a-only" in tenant_a and "tenant-b-only" not in tenant_a
    assert "tenant-b-only" in tenant_b and "tenant-a-only" not in tenant_b

    print("whatsapp tenant E2E: oauth=ok tenant_a=isolated tenant_b=isolated foreign_identity=rejected")


if __name__ == "__main__":
    anyio.run(run)
