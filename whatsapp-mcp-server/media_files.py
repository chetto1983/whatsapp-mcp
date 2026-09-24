"""A received file as an MCP client sees it: its name, type and size, and the
`whatsapp-media://` resource its bytes are read back through.

The bridge stores no MIME type, writes every image as `.jpg` (PNGs included) and
drops a document's own name when it saves the file, so none of the three can be
read off the path it returns. A document keeps the name its sender gave it
(`messages.filename`), plus the extension its bytes declare when the name has none;
everything else is named and typed by its first bytes.
"""

import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError
from mcp_types import CallToolResult, ResourceLink, TextContent

import whatsapp_actions
from whatsapp_query_messages import get_media_meta

OCTET_STREAM = "application/octet-stream"
# The cap Aura's MCP bridge materializes a file under. WhatsApp itself carries far
# larger documents; one over the cap is still linked, with its size, and refused
# on read.
MAX_MEDIA_FILE_BYTES = 25 * 1024 * 1024
# No store path and no tenant in the URI: this process can read every tenant's
# store, so the tenant comes from the caller's token, never from the link.
MEDIA_URI_TEMPLATE = "whatsapp-media://{chat_jid}/{message_id}"

# The media_type values the bridge downloads; "reaction" rows are not files.
_DOWNLOADABLE = frozenset({"image", "video", "audio", "document", "sticker"})
# Characters that would split or re-decode a template segment on the way back.
_URI_UNSAFE = frozenset("/?#&,{}% ")
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF8", "image/gif", ".gif"),
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"OggS", "audio/ogg", ".ogg"),
)
_SNIFF_BYTES = 16

# The standard library's own table, not the host's /etc/mime.types: the same name
# must get the same type in the test run and in the slim image. WhatsApp documents
# are mostly PDFs and Office files, and the built-in table lacks OOXML and, on 3.11,
# .md, which Aura itself sends.
_TYPES = mimetypes.MimeTypes()
_TYPES.add_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")
_TYPES.add_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")
_TYPES.add_type("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx")
_TYPES.add_type("text/markdown", ".md")
# The container type of each `guess_type` encoding worth naming; the others (compress,
# br) fall back to unknown bytes rather than to the type of what is inside.
_ENCODED_TYPES = {"gzip": "application/gzip", "bzip2": "application/x-bzip2", "xz": "application/x-xz"}


@dataclass(frozen=True)
class MediaFile:
    path: str
    name: str
    mime_type: str
    size_bytes: int


def sniff(head: bytes, media_type: str | None) -> tuple[str, str]:
    """The MIME type and extension a file's first bytes declare."""
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if head[4:8] == b"ftyp":
        # One container for both: an audio message in it is AAC from an iPhone.
        return ("audio/mp4", ".m4a") if media_type == "audio" else ("video/mp4", ".mp4")
    for magic, mime, ext in _MAGIC:
        if head.startswith(magic):
            return mime, ext
    return OCTET_STREAM, ""


def describe(media_type: str | None, filename: str | None, message_id: str, head: bytes) -> tuple[str, str]:
    """The name and MIME type a client should see for this file."""
    if media_type == "document":
        # The sender chose this name; only its last segment is a file name.
        name = PurePosixPath((filename or "").replace("\\", "/")).name
        if name not in ("", ".."):
            sniffed_mime, sniffed_ext = sniff(head, media_type)
            mime, encoding = _TYPES.guess_type(name)
            if encoding:
                # `export.csv.gz` is a gzip file, not a CSV: the bytes are the container.
                mime = _ENCODED_TYPES.get(encoding, OCTET_STREAM)
            if not PurePosixPath(name).suffix:
                # The bridge stores a nameless document as `document_<ts>_<id>`, so a name
                # with no extension is common, and a client picks its reader from the extension.
                name += sniffed_ext
            return name, mime or sniffed_mime
    mime, ext = sniff(head, media_type)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in message_id)
    return f"{media_type or 'media'}_{safe_id}{ext}", mime


def media_uri(chat_jid: str, message_id: str) -> str | None:
    """The resource URI of a message's media, or None when an id could not survive
    the round trip through the template."""
    if not chat_jid or not message_id or _URI_UNSAFE & set(chat_jid + message_id):
        return None
    return MEDIA_URI_TEMPLATE.format(chat_jid=chat_jid, message_id=message_id)


def media_file(message_id: str, chat_jid: str) -> MediaFile | None:
    """Download a message's media through the tenant's bridge and describe it.

    None when the active tenant's store has no such media message, or the bridge
    could not download it: WhatsApp expires media keys, so that is the ordinary
    outcome for old media. The store is read first, so a message id from another
    tenant never reaches the bridge. Raises OSError when the downloaded file cannot
    be read.
    """
    meta = get_media_meta(message_id, chat_jid)
    if meta is None or meta[0] not in _DOWNLOADABLE:
        return None
    path = whatsapp_actions.download_media(message_id, chat_jid)
    if not path:
        return None
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        head = handle.read(_SNIFF_BYTES)
    name, mime = describe(meta[0], meta[1], message_id, head)
    return MediaFile(path=path, name=name, mime_type=mime, size_bytes=size)


def download_result(message_id: str, chat_jid: str) -> CallToolResult:
    """download_media's result: the file described as JSON, plus a link to its bytes.

    `file_path` is where the bridge stored the file. `send_file` accepts it only when
    WHATSAPP_MEDIA_ROOTS includes the bridge's store directory.
    """
    try:
        media = media_file(message_id, chat_jid)
    except OSError as err:
        return _json_result({"success": False, "message": f"Media downloaded but unreadable: {err}"})
    if media is None:
        return _json_result({"success": False, "message": "Failed to download media"})
    body = {
        "success": True,
        "message": "Media downloaded successfully",
        "name": media.name,
        "mime_type": media.mime_type,
        "size_bytes": media.size_bytes,
        "file_path": media.path,
    }
    uri = media_uri(chat_jid, message_id)
    if uri is None:
        body["message"] += "; no resource link, because this message id cannot be carried in a URI"
        return _json_result(body)
    link = ResourceLink(uri=uri, name=media.name, mime_type=media.mime_type, size=media.size_bytes)
    return CallToolResult(content=[TextContent(text=json.dumps(body, ensure_ascii=False)), link])


def read_bytes(message_id: str, chat_jid: str) -> bytes:
    """The media's bytes for `resources/read`.

    ResourceNotFoundError and ResourceError reach the client with their message;
    any other exception would reach it as a bare "Error reading resource".
    """
    try:
        media = media_file(message_id, chat_jid)
        if media is None:
            raise ResourceNotFoundError(f"no downloadable media for message {message_id} in {chat_jid}")
        if media.size_bytes > MAX_MEDIA_FILE_BYTES:
            raise _over_cap(media.size_bytes)
        with open(media.path, "rb") as handle:
            # The size above was read before this open. Bound the read itself, so a file
            # that grew in between is refused instead of loaded whole.
            data = handle.read(MAX_MEDIA_FILE_BYTES + 1)
        if len(data) > MAX_MEDIA_FILE_BYTES:
            raise _over_cap(len(data))  # a lower bound: the read stopped at the cap
        return data
    except OSError as err:
        raise ResourceError(f"media unreadable: {err}") from err


def _over_cap(size: int) -> ResourceError:
    return ResourceError(f"{size} bytes exceeds the {MAX_MEDIA_FILE_BYTES}-byte cap")


def _json_result(body: dict[str, Any]) -> CallToolResult:
    return CallToolResult(content=[TextContent(text=json.dumps(body, ensure_ascii=False))])
