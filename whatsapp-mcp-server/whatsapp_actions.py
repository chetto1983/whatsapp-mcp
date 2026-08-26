"""Tenant-routed WhatsApp bridge actions and media helpers."""

import base64
import json
import os
from typing import Any

import requests

import audio
from tenant_context import TENANT_ID_HEADER, current_identity

WHATSAPP_API_BASE_URL = os.getenv("WHATSAPP_API_URL", "http://localhost:8081/api")


def _read_bridge_token() -> str:
    token = os.getenv("WHATSAPP_BRIDGE_TOKEN", "").strip()
    if len(token) < 16:
        raise RuntimeError("WHATSAPP_BRIDGE_TOKEN is required and must be at least 16 characters")
    return token


def _bridge_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_read_bridge_token()}",
        TENANT_ID_HEADER: current_identity(),
    }


def send_message(
    recipient: str,
    message: str,
    quoted_message_id: str = "",
    quoted_sender_jid: str = "",
    quoted_content: str = "",
) -> tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload: dict[str, Any] = {
            "recipient": recipient,
            "message": message,
        }
        if quoted_message_id:
            payload["quoted_message_id"] = quoted_message_id
            payload["quoted_sender_jid"] = quoted_sender_jid
            payload["quoted_content"] = quoted_content

        response = requests.post(url, json=payload, headers=_bridge_headers())

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def send_file(recipient: str, media_path: str) -> tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        if not media_path:
            return False, "Media path must be provided"

        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {"recipient": recipient, "media_path": media_path}

        response = requests.post(url, json=payload, headers=_bridge_headers())

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def send_audio_message(recipient: str, media_path: str) -> tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        if not media_path:
            return False, "Media path must be provided"

        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"

        if not media_path.endswith(".ogg"):
            try:
                media_path = audio.convert_to_opus_ogg_temp(media_path)
            except Exception as e:
                return False, f"Error converting file to opus ogg. You likely need to install ffmpeg: {str(e)}"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {"recipient": recipient, "media_path": media_path}

        response = requests.post(url, json=payload, headers=_bridge_headers())

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def send_reaction(
    recipient: str,
    message_id: str,
    emoji: str,
    from_me: bool = False,
    sender_jid: str = "",
) -> tuple[bool, str]:
    """Send (or remove) a reaction to a WhatsApp message.

    Args:
        recipient: The chat JID the message belongs to (phone JID or group JID).
        message_id: The ID of the message to react to.
        emoji: The reaction emoji. Pass an empty string to remove an existing reaction.
        from_me: Whether the original message was sent by the current user.
        sender_jid: JID of the original message sender (required for group messages
                    when from_me is False so the bridge can build the correct key).

    Returns:
        Tuple of (success, status_message).
    """
    try:
        if not recipient:
            return False, "Recipient must be provided"
        if not message_id:
            return False, "Message ID must be provided"

        url = f"{WHATSAPP_API_BASE_URL}/react"
        payload: dict[str, Any] = {
            "recipient": recipient,
            "message_id": message_id,
            "emoji": emoji,
            "from_me": from_me,
            "sender_jid": sender_jid,
        }

        response = requests.post(url, json=payload, headers=_bridge_headers())

        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                return True, "Reaction sent"
            return False, result.get("error", "Unknown error")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def download_media(message_id: str, chat_jid: str) -> str | None:
    """Download media from a message and return the local file path.

    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message

    Returns:
        The local file path if download was successful, None otherwise
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/download"
        payload = {"message_id": message_id, "chat_jid": chat_jid}

        response = requests.post(url, json=payload, headers=_bridge_headers())

        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                path = result.get("path")
                print(f"Media downloaded successfully: {path}")
                return path
            else:
                print(f"Download failed: {result.get('message', 'Unknown error')}")
                return None
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return None

    except requests.RequestException as e:
        print(f"Request error: {str(e)}")
        return None
    except json.JSONDecodeError:
        print(f"Error parsing response: {response.text}")
        return None
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return None


# The media a browser can actually paint. Everything else stays a chip in the view:
# a rendered panel has nothing to do with an opus blob, and inlining one would only
# spend bytes on something no <img> will ever show.
INLINE_MEDIA_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# WhatsApp compresses what it sends before it ever reaches the store: measured
# 2026-08-23 over a real store, 28 files, median 200 KB and the largest 568 KB. So
# 800 KB admits every ordinary photo while still refusing to hand a browser
# something unbounded -- base64 inflates by a third, and a view is a panel, not a
# file viewer. A file over the cap keeps its chip and reports its size.
MAX_INLINE_MEDIA_BYTES = 800_000


def media_data_url(message_id: str, chat_jid: str) -> dict[str, Any]:
    """Download a message's media and return it as a `data:` URL.

    `download_media` returns a path inside the container, which is exactly no use
    to a rendered view: the browser cannot open it and the sandboxed frame may not
    fetch anything. The bytes have to travel in the tool result, so this is the
    same download followed by a read.

    Returns:
        On success `{"success": True, "mime": ..., "bytes": ..., "data_url": ...}`.
        On refusal `success` is False and `reason` names which of the three ways it
        failed -- the download, the type, or the cap -- because "no image" with no
        reason is the kind of blank a view cannot explain to anyone.
    """
    path = download_media(message_id, chat_jid)
    if not path:
        return {"success": False, "reason": "unavailable", "message": "The media could not be downloaded."}

    mime = INLINE_MEDIA_MIME.get(os.path.splitext(path)[1].lower())
    if mime is None:
        return {
            "success": False,
            "reason": "not_inlinable",
            "message": f"{os.path.splitext(path)[1] or 'this file'} is not an image a view can paint.",
        }

    try:
        size = os.path.getsize(path)
        if size > MAX_INLINE_MEDIA_BYTES:
            return {
                "success": False,
                "reason": "too_large",
                "bytes": size,
                "message": f"{size} bytes is over the {MAX_INLINE_MEDIA_BYTES}-byte inline cap.",
            }
        with open(path, "rb") as handle:
            blob = handle.read()
    except OSError as err:
        return {"success": False, "reason": "unreadable", "message": str(err)}

    return {
        "success": True,
        "mime": mime,
        "bytes": len(blob),
        "data_url": "data:" + mime + ";base64," + base64.b64encode(blob).decode("ascii"),
    }
