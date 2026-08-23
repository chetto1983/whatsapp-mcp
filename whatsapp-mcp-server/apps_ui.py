"""MCP Apps views for the WhatsApp server (`io.modelcontextprotocol/ui`).

ONE `ui://` resource -- a two-pane client, the chat index beside the open
conversation -- bound to both `list_messages` and `list_chats`. A host that
negotiated MCP Apps renders it in a sandboxed iframe; a host that did not receives
exactly the same tool payload as before, so the UI is a progressive enhancement
and never a requirement (ext-apps specification/2026-01-26/apps.mdx
§"Progressive Enhancement").

It was two resources, one per tool, and that was the wrong seam: whichever tool
the model happened to call filled the whole frame while the other half of the app
was simply absent -- a transcript with no way back to the list, or a list that
could only reach a transcript by asking the model for one. WhatsApp is a two-pane
client; the view is now one document that puts the incoming payload in its own
pane and fills the other itself.

The views are plain HTML with the JSON-RPC-over-postMessage bridge inlined: the
ext-apps SDK is TypeScript and expects a bundler, while a `ui://` resource must
be one self-contained document. `ui/_bridge.js` and `ui/_theme.css` are kept
authorable on their own and spliced in here.

The view is read from `ui/` beside this module, which is how the server runs (the
image copies the source tree and launches `main.py` from it). It is not packaged
into the wheel: `py-modules` carries modules, not data directories, and inventing
a package just to hold the HTML would buy nothing here.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.apps import Apps, ResourceCsp

UI_DIR = Path(__file__).resolve().parent / "ui"

CLIENT_URI = "ui://whatsapp/client.html"

# Placeholders the view carries, and the shared asset spliced into each.
_INCLUDES = (("/*{{THEME}}*/", "_theme.css"), ("/*{{BRIDGE}}*/", "_bridge.js"))

# The view never fetches: it renders what the host hands it and calls back over
# postMessage. Declaring every domain list empty says exactly that, so a host's
# sandbox can seal the iframe rather than guess a default.
SEALED_CSP = ResourceCsp(
    connect_domains=[],
    resource_domains=[],
    frame_domains=[],
    base_uri_domains=[],
)


def openai_alias(resource_uri: str) -> dict[str, str]:
    """The `_meta` alias ChatGPT reads for the same `ui://` resource.

    ChatGPT implements MCP Apps and prefers `_meta.ui.resourceUri`, but still
    accepts `openai/outputTemplate`. Emitting both costs one key and widens the
    set of hosts that render these views.
    """
    return {"openai/outputTemplate": resource_uri}


def _document(name: str) -> str:
    """Read a view and splice in the shared theme and bridge.

    Raises:
        ValueError: If the view is missing a placeholder — a view that silently
            shipped without its bridge would render, then never speak to the host.
    """
    html = (UI_DIR / name).read_text(encoding="utf-8")
    for marker, asset in _INCLUDES:
        if marker not in html:
            raise ValueError(f"{name} has no {marker} placeholder; it cannot be assembled")
        html = html.replace(marker, (UI_DIR / asset).read_text(encoding="utf-8"))
    return html


def build_apps() -> Apps:
    """Build the Apps extension with the client view registered.

    The returned instance must be decorated with its tools (`@apps.tool(...)`)
    before it is handed to `MCPServer(extensions=[...])`: the server consumes the
    extension at construction and rejects a tool whose `resource_uri` has no
    registered resource.
    """
    apps = Apps()
    apps.add_html_resource(
        CLIENT_URI,
        _document("client.html"),
        name="whatsapp-client",
        title="WhatsApp",
        description=(
            "The chat index beside the open conversation: pick a chat on the left, read it on the "
            "right, page back through older messages. Marks any chat whose activity has no stored "
            "message behind it."
        ),
        csp=SEALED_CSP,
        prefers_border=True,
    )
    return apps
