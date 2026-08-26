import pytest

import whatsapp
from tenant_context import TENANT_ID_HEADER

TEST_IDENTITY = "11111111-1111-4111-8111-111111111111"
TEST_BRIDGE_TOKEN = "bridge-token-for-tests"


class DummyResponse:
    def __init__(self, status_code=200, payload=None, text="OK"):
        self.status_code = status_code
        self._payload = payload or {"success": True, "message": "sent", "path": "/tmp/media.jpg"}
        self.text = text

    def json(self):
        return self._payload


def expected_headers():
    return {
        "Authorization": f"Bearer {TEST_BRIDGE_TOKEN}",
        TENANT_ID_HEADER: TEST_IDENTITY,
    }


def test_bridge_headers_require_service_token_and_identity():
    assert whatsapp._bridge_headers() == expected_headers()


def test_bridge_headers_fail_closed_without_token(monkeypatch):
    monkeypatch.delenv("WHATSAPP_BRIDGE_TOKEN")
    with pytest.raises(RuntimeError, match="WHATSAPP_BRIDGE_TOKEN is required"):
        whatsapp._bridge_headers()


def test_send_message_without_token_never_calls_gateway(monkeypatch):
    calls = []
    monkeypatch.delenv("WHATSAPP_BRIDGE_TOKEN")
    monkeypatch.setattr(whatsapp.requests, "post", lambda *args, **kwargs: calls.append((args, kwargs)))

    success, message = whatsapp.send_message("12025551234", "hello")

    assert success is False
    assert "WHATSAPP_BRIDGE_TOKEN is required" in message
    assert calls == []


@pytest.mark.parametrize(
    ("func_name", "args", "expected_suffix"),
    [
        ("send_message", ("12025551234", "hello"), "/send"),
        ("send_file", ("12025551234", "FILE"), "/send"),
        ("send_audio_message", ("12025551234", "FILE"), "/send"),
        ("download_media", ("msg-id", "12025551234@s.whatsapp.net"), "/download"),
        ("send_reaction", ("12025551234@s.whatsapp.net", "3AABCDEF01234567", "👍"), "/react"),
    ],
)
def test_bridge_post_helpers_include_identity_and_auth(monkeypatch, tmp_path, func_name, args, expected_suffix):
    calls = []
    media_file = tmp_path / "voice.ogg"
    media_file.write_bytes(b"ogg")
    resolved_args = tuple(str(media_file) if arg == "FILE" else arg for arg in args)

    def fake_post(url, json, headers=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return DummyResponse()

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    getattr(whatsapp, func_name)(*resolved_args)

    assert calls[0]["url"].endswith(expected_suffix)
    assert calls[0]["headers"] == expected_headers()


def test_send_reaction_posts_correct_payload(monkeypatch):
    calls = []

    def fake_post(url, json, headers=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return DummyResponse(payload={"ok": True})

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    success, _ = whatsapp.send_reaction(
        "12025551234@s.whatsapp.net",
        "3AABCDEF01234567",
        "👍",
        from_me=False,
        sender_jid="98765@s.whatsapp.net",
    )

    assert success is True
    assert calls[0]["json"] == {
        "recipient": "12025551234@s.whatsapp.net",
        "message_id": "3AABCDEF01234567",
        "emoji": "👍",
        "from_me": False,
        "sender_jid": "98765@s.whatsapp.net",
    }
    assert calls[0]["headers"] == expected_headers()


def test_send_reaction_empty_emoji_sends_removal(monkeypatch):
    calls = []

    def fake_post(url, json, headers=None):
        calls.append(json)
        return DummyResponse(payload={"ok": True})

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    success, _ = whatsapp.send_reaction("12025551234@s.whatsapp.net", "3AABCDEF01234567", "")

    assert success is True
    assert calls[0]["emoji"] == ""


def test_send_reaction_validates_required_fields():
    assert whatsapp.send_reaction("", "3AABCDEF01234567", "👍")[0] is False
    assert whatsapp.send_reaction("12025551234@s.whatsapp.net", "", "👍")[0] is False


def test_send_message_with_quoted_reply_includes_quote_fields(monkeypatch):
    calls = []

    def fake_post(url, json, headers=None):
        calls.append({"json": json, "headers": headers})
        return DummyResponse()

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    success, _ = whatsapp.send_message(
        "12025551234@s.whatsapp.net",
        "Great point!",
        quoted_message_id="3AORIGINAL0000001",
        quoted_sender_jid="99887766@s.whatsapp.net",
        quoted_content="original text",
    )

    assert success is True
    assert calls[0]["json"]["quoted_message_id"] == "3AORIGINAL0000001"
    assert calls[0]["json"]["quoted_sender_jid"] == "99887766@s.whatsapp.net"
    assert calls[0]["json"]["quoted_content"] == "original text"
    assert calls[0]["headers"] == expected_headers()


def test_send_message_without_quote_omits_quote_fields(monkeypatch):
    calls = []

    def fake_post(url, json, headers=None):
        calls.append(json)
        return DummyResponse()

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    whatsapp.send_message("12025551234@s.whatsapp.net", "Hello!")

    assert "quoted_message_id" not in calls[0]
    assert "quoted_sender_jid" not in calls[0]
    assert "quoted_content" not in calls[0]
