"""Tests for `media_data_url`, the tool a rendered view uses to show a photo.

Its sibling `download_media` returns a path inside the container, which a browser
can neither open nor fetch, so a view could only ever draw a placeholder where the
picture belongs. This carries the bytes instead — and every way it can decline has
to say WHICH way, because a blank box with no reason is exactly what it replaced.
"""

import base64

import pytest

import whatsapp
import whatsapp_actions


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """A downloaded file, with `download_media` pointed at it."""

    def place(name: str, blob: bytes):
        path = tmp_path / name
        path.write_bytes(blob)
        monkeypatch.setattr(whatsapp_actions, "download_media", lambda *_: str(path))
        return path

    return place


def test_an_image_comes_back_as_a_data_url(stored):
    stored("photo.jpg", b"\xff\xd8\xff\xe0 not really a jpeg, but bytes are bytes")

    result = whatsapp.media_data_url("MSG", "chat@s.whatsapp.net")

    assert result["success"] is True
    assert result["mime"] == "image/jpeg"
    assert result["data_url"].startswith("data:image/jpeg;base64,")
    payload = result["data_url"].split(",", 1)[1]
    assert base64.b64decode(payload).startswith(b"\xff\xd8\xff")
    assert result["bytes"] == len(base64.b64decode(payload))


@pytest.mark.parametrize(
    ("name", "mime"),
    [("a.png", "image/png"), ("a.webp", "image/webp"), ("a.gif", "image/gif"), ("A.JPEG", "image/jpeg")],
)
def test_every_paintable_type_is_named_by_its_extension(stored, name, mime):
    """The extension decides, case-insensitively: the bridge writes .JPEG as
    readily as .jpg and a view cannot paint what it has not been told the type of."""
    stored(name, b"bytes")

    assert whatsapp.media_data_url("MSG", "chat")["mime"] == mime


def test_a_failed_download_says_so(monkeypatch):
    """WhatsApp expires media keys, so this is the ordinary case in a real chat and
    not an edge one — two of four images in a live thread came back this way."""
    monkeypatch.setattr(whatsapp_actions, "download_media", lambda *_: None)

    result = whatsapp.media_data_url("MSG", "chat")

    assert result["success"] is False
    assert result["reason"] == "unavailable"


def test_a_type_no_view_can_paint_is_refused(stored):
    """An <img> does nothing with an opus blob; spending the bytes to send one
    would buy a placeholder that took longer to appear."""
    stored("voice.ogg", b"OggS")

    result = whatsapp.media_data_url("MSG", "chat")

    assert result["success"] is False
    assert result["reason"] == "not_inlinable"


def test_a_file_over_the_cap_is_refused_with_its_size(stored, monkeypatch):
    """The size travels back so the view can say how large rather than just no."""
    monkeypatch.setattr(whatsapp_actions, "MAX_INLINE_MEDIA_BYTES", 32)
    stored("huge.jpg", b"x" * 64)

    result = whatsapp.media_data_url("MSG", "chat")

    assert result["success"] is False
    assert result["reason"] == "too_large"
    assert result["bytes"] == 64


def test_an_unreadable_file_is_reported_not_raised(tmp_path, monkeypatch):
    """The bridge can report a path it then fails to leave behind. A raise here
    would surface to the model as a tool error for what is only a missing picture."""
    monkeypatch.setattr(whatsapp_actions, "download_media", lambda *_: str(tmp_path / "gone.jpg"))

    result = whatsapp.media_data_url("MSG", "chat")

    assert result["success"] is False
    assert result["reason"] == "unreadable"
