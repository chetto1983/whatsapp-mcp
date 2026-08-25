"""Real Streamable HTTP proof for bearer auth and Aura tenant isolation."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import anyio
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

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


async def call_for_tenant(session: ClientSession, identity: str) -> str:
    result = await session.call_tool(
        "list_chats",
        {"include_last_message": False},
        meta={"aura": {"user_identifier": identity}},
    )
    if result.is_error:
        raise RuntimeError(f"list_chats failed for {identity}: {result}")
    return json.dumps(result.model_dump(mode="json", by_alias=True), sort_keys=True)


async def run() -> None:
    url = os.environ["WHATSAPP_E2E_MCP_URL"]
    token = os.environ["WHATSAPP_MCP_SERVICE_TOKEN"]
    root = Path(os.environ["WHATSAPP_STORE_ROOT"])
    seed(root, TENANT_A, "tenant-a-only")
    seed(root, TENANT_B, "tenant-b-only")

    async with httpx2.AsyncClient() as anonymous:
        response = await anonymous.post(url, json={})
        assert response.status_code == 401, response.text

    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as client:
        async with streamable_http_client(url, http_client=client, terminate_on_close=False) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "list_chats" in {tool.name for tool in tools.tools}
                tenant_a = await call_for_tenant(session, TENANT_A)
                tenant_b = await call_for_tenant(session, TENANT_B)
                assert "tenant-a-only" in tenant_a and "tenant-b-only" not in tenant_a
                assert "tenant-b-only" in tenant_b and "tenant-a-only" not in tenant_b
                try:
                    await session.call_tool("list_chats", {"include_last_message": False})
                except MCPError as exc:
                    assert "user_identifier is required" in str(exc)
                else:
                    raise AssertionError("tool call without Aura identity was accepted")

    print("whatsapp tenant E2E: bearer=ok tenant_a=isolated tenant_b=isolated missing_identity=rejected")


if __name__ == "__main__":
    anyio.run(run)
