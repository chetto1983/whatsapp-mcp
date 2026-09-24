"""download_media and its whatsapp-media:// resource, driven through a real MCP client.

`Client(main.mcp)` talks to the server in-process, so every request crosses the same
middleware a remote one does. The caller's OAuth subject is never the tenant the
suite binds by default: a read that skipped the tenant middleware would run as that
default tenant, find no store, and fail.
"""

import base64
import json

import pytest
from mcp import Client
from mcp.server.auth.provider import AccessToken
from mcp.shared.exceptions import MCPError
from mcp_types import ResourceLink, TextContent

import main
import media_files
import tenant_context
import whatsapp_actions

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CHAT = "393331234567@s.whatsapp.net"
MSG = "3EB0C767D26A1D3B9A0C"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


@pytest.fixture
def signed_in(monkeypatch):
    """Make every request arrive with `subject`'s bearer token."""

    def as_subject(subject: str) -> None:
        monkeypatch.setattr(
            tenant_context,
            "get_access_token",
            lambda: AccessToken(token="token", client_id="client", scopes=["mcp:tools"], subject=subject),
        )

    return as_subject


def _body(result) -> dict:
    return json.loads(next(block for block in result.content if isinstance(block, TextContent)).text)


def _links(result) -> list[ResourceLink]:
    return [block for block in result.content if isinstance(block, ResourceLink)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chat_jid",
    [
        CHAT,
        "393331234567:12@s.whatsapp.net",
        "120363012345678901@g.us",
        "393331234567-1600000000@g.us",
        "123456789012345@lid",
    ],
    ids=["dm", "dm-device", "group", "group-legacy", "lid"],
)
async def test_download_media_links_the_file_and_the_link_reads_back(signed_in, seed_media, bridge_download, chat_jid):
    """Every JID form the bridge stores must survive the URI: the link is built here and
    matched back into `{chat_jid}` by the SDK's template."""
    signed_in(TENANT_A)
    seed_media(TENANT_A, MSG, chat_jid, "image")
    bridge_download(PNG)

    async with Client(main.mcp) as client:
        result = await client.call_tool("download_media", {"message_id": MSG, "chat_jid": chat_jid})
        [link] = _links(result)
        read = await client.read_resource(str(link.uri))

    body = _body(result)
    assert result.is_error is False
    assert body["success"] is True
    assert (body["name"], body["mime_type"], body["size_bytes"]) == (f"image_{MSG}.png", "image/png", len(PNG))
    assert body["file_path"].endswith("bridge-download.jpg")
    assert str(link.uri) == f"whatsapp-media://{chat_jid}/{MSG}"
    assert (link.name, link.mime_type, link.size) == (f"image_{MSG}.png", "image/png", len(PNG))
    [contents] = read.contents
    assert base64.b64decode(contents.blob) == PNG


@pytest.mark.asyncio
async def test_another_tenant_reads_nothing_and_never_reaches_the_bridge(signed_in, seed_media, bridge_download):
    seed_media(TENANT_A, MSG, CHAT, "image")
    seed_media(TENANT_B, "B-OWN-MESSAGE", CHAT, "image")
    calls = bridge_download(PNG)
    signed_in(TENANT_B)

    async with Client(main.mcp) as client:
        with pytest.raises(MCPError, match="no downloadable media"):
            await client.read_resource(f"whatsapp-media://{CHAT}/{MSG}")

    assert calls == []


@pytest.mark.asyncio
async def test_a_read_without_a_subject_is_refused_and_never_reaches_the_bridge(seed_media, bridge_download):
    """No `signed_in`: the request carries no bearer token, so there is no tenant to read as."""
    seed_media(TENANT_A, MSG, CHAT, "image")
    calls = bridge_download(PNG)

    async with Client(main.mcp) as client:
        with pytest.raises(MCPError, match="OAuth subject is required"):
            await client.read_resource(f"whatsapp-media://{CHAT}/{MSG}")

    assert calls == []


@pytest.mark.asyncio
async def test_a_failed_download_says_so_and_links_nothing(signed_in, seed_media, bridge_download):
    signed_in(TENANT_A)
    seed_media(TENANT_A, MSG, CHAT, "image")
    bridge_download(None)

    async with Client(main.mcp) as client:
        result = await client.call_tool("download_media", {"message_id": MSG, "chat_jid": CHAT})

    assert _body(result) == {"success": False, "message": "Failed to download media"}
    assert _links(result) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cap", "served"), [(len(PNG) - 1, False), (len(PNG), True)], ids=["one-over-the-cap", "exactly-the-cap"]
)
async def test_media_is_served_up_to_the_cap_and_only_linked_past_it(
    signed_in, seed_media, bridge_download, monkeypatch, cap, served
):
    """The link states the size either way, so a client can decline before it reads.
    A file of exactly the cap is served: only one that exceeds it is refused."""
    monkeypatch.setattr(media_files, "MAX_MEDIA_FILE_BYTES", cap)
    signed_in(TENANT_A)
    seed_media(TENANT_A, MSG, CHAT, "image")
    bridge_download(PNG)

    async with Client(main.mcp) as client:
        result = await client.call_tool("download_media", {"message_id": MSG, "chat_jid": CHAT})
        [link] = _links(result)
        if served:
            [contents] = (await client.read_resource(str(link.uri))).contents
            assert base64.b64decode(contents.blob) == PNG
        else:
            with pytest.raises(MCPError, match=f"exceeds the {cap}-byte cap"):
                await client.read_resource(str(link.uri))

    assert link.size == len(PNG)


@pytest.mark.asyncio
async def test_a_message_id_a_uri_cannot_carry_gets_the_file_without_a_link(signed_in, seed_media, bridge_download):
    signed_in(TENANT_A)
    seed_media(TENANT_A, "ODD/ID", CHAT, "image")
    bridge_download(PNG)

    async with Client(main.mcp) as client:
        result = await client.call_tool("download_media", {"message_id": "ODD/ID", "chat_jid": CHAT})

    body = _body(result)
    assert body["success"] is True
    assert "no resource link" in body["message"]
    assert _links(result) == []


@pytest.mark.asyncio
async def test_a_download_whose_file_is_gone_is_reported_not_raised(signed_in, seed_media, monkeypatch, tmp_path):
    signed_in(TENANT_A)
    seed_media(TENANT_A, MSG, CHAT, "image")
    monkeypatch.setattr(whatsapp_actions, "download_media", lambda *_: str(tmp_path / "gone.jpg"))

    async with Client(main.mcp) as client:
        result = await client.call_tool("download_media", {"message_id": MSG, "chat_jid": CHAT})
        with pytest.raises(MCPError, match="media unreadable"):
            await client.read_resource(f"whatsapp-media://{CHAT}/{MSG}")

    body = _body(result)
    assert body["success"] is False
    assert body["message"].startswith("Media downloaded but unreadable")


@pytest.mark.asyncio
async def test_get_media_data_keeps_the_shape_the_view_reads(signed_in, bridge_download):
    """ui/_bridge.js `payloadOf` reads structuredContent when present, else the first
    text block's JSON; the view then needs `success` and a data:image/ URL."""
    signed_in(TENANT_A)
    bridge_download(PNG)

    async with Client(main.mcp) as client:
        result = await client.call_tool("get_media_data", {"message_id": MSG, "chat_jid": CHAT})

    payload = result.structured_content or _body(result)
    assert payload["success"] is True
    assert payload["data_url"].startswith("data:image/jpeg;base64,")
