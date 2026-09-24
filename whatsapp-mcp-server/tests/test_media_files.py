"""What download_media reports about a received file, and what it refuses to guess.

The bridge stores no MIME type, writes every image as .jpg and drops a document's
own name, so the name and the type come from the message row and the file's first
bytes. Every case here is one a real chat produces.
"""

from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ResourceError

import media_files
import whatsapp_actions
from tenant_context import current_identity, tenant_store

CHAT = "393331234567@s.whatsapp.net"
GROUP = "120363025246125888@g.us"
MSG = "3EB0C767D26A1D3B9A0C"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.parametrize(
    ("head", "media_type", "expected"),
    [
        (JPEG, "image", ("image/jpeg", ".jpg")),
        (PNG, "image", ("image/png", ".png")),
        (b"GIF89a\x01\x00", "image", ("image/gif", ".gif")),
        (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "sticker", ("image/webp", ".webp")),
        (b"%PDF-1.7\n%\xe2\xe3", "document", ("application/pdf", ".pdf")),
        (b"OggS\x00\x02\x00\x00", "audio", ("audio/ogg", ".ogg")),
        (b"\x00\x00\x00\x18ftypmp42", "video", ("video/mp4", ".mp4")),
        (b"\x00\x00\x00\x1cftypM4A ", "audio", ("audio/mp4", ".m4a")),
        (b"PK\x03\x04\x14\x00", "document", ("application/octet-stream", "")),
        (b"", "image", ("application/octet-stream", "")),
    ],
)
def test_sniff_types_a_file_by_its_first_bytes(head, media_type, expected):
    assert media_files.sniff(head, media_type) == expected


def test_an_image_saved_as_jpg_that_is_a_png_is_named_and_typed_png():
    assert media_files.describe("image", None, MSG, PNG) == (f"image_{MSG}.png", "image/png")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Fattura settembre.pdf", ("Fattura settembre.pdf", "application/pdf")),
        ("Relazione finale.docx", ("Relazione finale.docx", DOCX)),
        ("../../etc/passwd.pdf", ("passwd.pdf", "application/pdf")),
        ("C:\\Users\\anna\\Preventivo.xlsx", ("Preventivo.xlsx", XLSX)),
        # Compressed: the bytes are the container, whatever the inner name says.
        ("export.csv.gz", ("export.csv.gz", "application/gzip")),
        ("backup.tar.gz", ("backup.tar.gz", "application/gzip")),
        ("bundle.tgz", ("bundle.tgz", "application/gzip")),
        ("data.gz", ("data.gz", "application/gzip")),
        ("logs.txt.bz2", ("logs.txt.bz2", "application/x-bzip2")),
        ("dump.sql.xz", ("dump.sql.xz", "application/x-xz")),
        ("old.tar.Z", ("old.tar.Z", media_files.OCTET_STREAM)),
    ],
)
def test_a_document_keeps_the_name_its_sender_gave_it(filename, expected):
    assert media_files.describe("document", filename, MSG, b"PK\x03\x04") == expected


@pytest.mark.parametrize("filename", [None, "", ".", ".."])
def test_a_document_without_a_usable_name_is_named_like_other_media(filename):
    assert media_files.describe("document", filename, MSG, b"%PDF-1.4") == (f"document_{MSG}.pdf", "application/pdf")


@pytest.mark.parametrize(
    ("filename", "head", "expected"),
    [
        # The bridge stores a nameless document as `document_<ts>_<id>`, so a name with
        # no extension is common: it gets the one its bytes declare.
        ("scansione", b"%PDF-1.4", ("scansione.pdf", "application/pdf")),
        ("Foto del 12 maggio", PNG, ("Foto del 12 maggio.png", "image/png")),
        # Nothing to declare: the sender's name stands, typed as unknown.
        ("README", b"PK\x03\x04", ("README", media_files.OCTET_STREAM)),
        # An extension the table does not know is still the sender's: typed by the bytes.
        ("scansione.scan", b"%PDF-1.4", ("scansione.scan", "application/pdf")),
    ],
)
def test_a_document_whose_name_has_no_extension_gets_the_one_its_bytes_declare(filename, head, expected):
    assert media_files.describe("document", filename, MSG, head) == expected


def test_a_hostile_message_id_cannot_shape_the_file_name():
    name, _ = media_files.describe("image", None, "../x/y", JPEG)

    assert "/" not in name
    assert ".." not in name


def test_the_uri_carries_the_chat_and_the_message():
    assert media_files.media_uri(GROUP, MSG) == f"whatsapp-media://{GROUP}/{MSG}"


@pytest.mark.parametrize(
    ("chat_jid", "message_id"),
    [(CHAT, ""), ("", MSG), (CHAT, "a/b"), (CHAT, "a%2Fb"), (CHAT, "a?b"), (CHAT, "a#b"), (CHAT, "a b")],
)
def test_an_id_that_cannot_round_trip_gets_no_uri(chat_jid, message_id):
    assert media_files.media_uri(chat_jid, message_id) is None


def test_media_file_describes_what_the_bridge_downloaded(seed_media, bridge_download):
    seed_media(current_identity(), MSG, CHAT, "document", "Fattura.pdf")
    calls = bridge_download(b"%PDF-1.7 body")

    media = media_files.media_file(MSG, CHAT)

    assert calls == [(MSG, CHAT)]
    assert (media.name, media.mime_type, media.size_bytes) == ("Fattura.pdf", "application/pdf", 13)
    assert Path(media.path).read_bytes() == b"%PDF-1.7 body"


def test_a_message_the_tenant_does_not_have_never_reaches_the_bridge(seed_media, bridge_download):
    seed_media(current_identity(), "ANOTHER", CHAT, "image")
    calls = bridge_download(JPEG)

    assert media_files.media_file(MSG, CHAT) is None
    assert calls == []


def test_a_tenant_without_a_store_never_reaches_the_bridge(bridge_download):
    """Before a tenant has ever paired, its store has no messages.db at all --
    not merely no matching row -- and that is still not a file."""
    db_path = tenant_store(current_identity()) / "messages.db"
    if db_path.exists():
        db_path.unlink()
    calls = bridge_download(JPEG)

    assert media_files.media_file(MSG, CHAT) is None
    assert calls == []


@pytest.mark.parametrize("media_type", ["reaction", "", None])
def test_a_message_without_a_file_never_reaches_the_bridge(seed_media, bridge_download, media_type):
    """A reaction row stores the reacted-to message id in `filename`; it is not a file."""
    seed_media(current_identity(), MSG, CHAT, media_type, "3EB0REACTEDTO")
    calls = bridge_download(JPEG)

    assert media_files.media_file(MSG, CHAT) is None
    assert calls == []


def test_a_failed_download_is_none(seed_media, bridge_download):
    seed_media(current_identity(), MSG, CHAT, "image")
    bridge_download(None)

    assert media_files.media_file(MSG, CHAT) is None


def test_a_downloaded_path_that_is_gone_raises(seed_media, monkeypatch, tmp_path):
    seed_media(current_identity(), MSG, CHAT, "image")
    monkeypatch.setattr(whatsapp_actions, "download_media", lambda *_: str(tmp_path / "gone.jpg"))

    with pytest.raises(OSError):
        media_files.media_file(MSG, CHAT)


@pytest.mark.parametrize(("on_disk", "served"), [(8, True), (9, False)], ids=["at-the-cap", "one-past-it"])
def test_the_read_is_bounded_by_the_cap_not_by_the_size_read_earlier(monkeypatch, tmp_path, on_disk, served):
    """`media_file` reads the size before the read opens the file; a bridge write in
    between must not slip a larger file past the cap."""
    path = tmp_path / "grew.bin"
    path.write_bytes(b"x" * on_disk)
    stale = media_files.MediaFile(str(path), "grew.bin", media_files.OCTET_STREAM, size_bytes=4)
    monkeypatch.setattr(media_files, "MAX_MEDIA_FILE_BYTES", 8)
    monkeypatch.setattr(media_files, "media_file", lambda *_: stale)

    if served:
        assert media_files.read_bytes(MSG, CHAT) == b"x" * on_disk
    else:
        with pytest.raises(ResourceError, match="exceeds the 8-byte cap"):
            media_files.read_bytes(MSG, CHAT)


def test_the_bridge_download_gives_up_after_70_seconds(monkeypatch):
    """The tenant gateway answers within 65 s; without a timeout of its own a
    stuck runtime held the tool call forever."""
    seen = {}

    def post(url, **kwargs):
        seen.update(kwargs)
        raise whatsapp_actions.requests.Timeout("stuck")

    monkeypatch.setattr(whatsapp_actions.requests, "post", post)

    assert whatsapp_actions.download_media(MSG, CHAT) is None
    assert seen["timeout"] == 70
