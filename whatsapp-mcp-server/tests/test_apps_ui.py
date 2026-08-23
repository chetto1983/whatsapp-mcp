"""Tests for the MCP Apps view (`io.modelcontextprotocol/ui`)."""

import re

import pytest
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

import apps_ui
import main
from apps_ui import CLIENT_URI, build_apps, openai_alias

# The DOM sinks that turn text into markup. Matching the *assignment* (and the
# insert call) rather than the bare identifier keeps a comment saying "never
# innerHTML" from failing the check that enforces it.
MARKUP_SINKS = re.compile(r"\.(inner|outer)HTML\s*=|insertAdjacentHTML|document\.write\s*\(")


@pytest.fixture(scope="module")
def apps():
    """The server's own extension instance.

    `build_apps()` returns a fresh, tool-less one — the tools are bound by the
    decorators in `main`, so the bindings only exist on the instance `main`
    handed to MCPServer. Asserting against a fresh instance would pass an empty
    set and prove nothing.
    """
    return main.apps


@pytest.fixture(scope="module")
def resources(apps):
    return {binding.resource.uri: binding.resource for binding in apps.resources()}


@pytest.fixture(scope="module")
def view(resources):
    return resources[CLIENT_URI].text


class TestExtensionIdentity:
    def test_identifier_is_the_spec_one(self, apps):
        assert apps.identifier == EXTENSION_ID == "io.modelcontextprotocol/ui"


class TestResources:
    def test_one_client_view_is_registered(self, resources):
        """It was two, one per tool, and that was the wrong seam: whichever tool the
        model called filled the frame while the other half of the app was absent."""
        assert set(resources) == {CLIENT_URI}

    def test_served_as_an_app_document(self, resources):
        assert resources[CLIENT_URI].mime_type == APP_MIME_TYPE

    def test_no_placeholder_survives_assembly(self, view):
        """A view that shipped with its placeholder intact would render, then never
        speak to the host — the failure is silent, so it is asserted."""
        for marker, _ in apps_ui._INCLUDES:
            assert marker not in view

    def test_bridge_and_theme_are_inlined(self, view):
        assert "window.McpApp" in view, "the postMessage bridge is missing"
        assert "ui/notifications/initialized" in view, "the handshake is missing"
        assert "--font-wa" in view, "the shared theme is missing"

    def test_declares_a_sealed_csp(self, resources):
        """The view fetches nothing, and says so: every domain list is empty, so a
        host sandbox seals the iframe instead of applying a default."""
        ui = resources[CLIENT_URI].meta["ui"]
        assert ui["csp"] == {
            "connectDomains": [],
            "resourceDomains": [],
            "frameDomains": [],
            "baseUriDomains": [],
        }

    def test_view_never_writes_untrusted_text_as_markup(self, view):
        """Message bodies, chat names and JIDs are third-party text. They reach the
        DOM through textContent; an innerHTML assignment here would be an injection
        sink fed straight from WhatsApp."""
        found = MARKUP_SINKS.search(view)
        assert found is None, f"the view writes markup through {found.group(0)!r}"


class TestTwoPanes:
    """Both halves of the app are present however the view was opened."""

    def test_both_panes_exist_in_one_document(self, view):
        assert 'class="pane index"' in view
        assert 'class="pane chat"' in view

    def test_the_empty_pane_fills_itself(self, view):
        """Opened by list_messages the index would be blank, and opened by list_chats
        the conversation would be; each is filled by a read-only call of its own."""
        assert 'callTool("list_chats"' in view
        assert 'callTool("list_messages"' in view

    def test_a_chat_opens_in_pane_rather_than_via_the_model(self, view):
        """Clicking a chat used to send the model a sentence asking it to fetch the
        transcript. The view can fetch it itself; sendToChat stays for the button
        that deliberately hands the conversation over."""
        assert "function openChat" in view
        assert "sendToChat" in view


class TestHostTheming:
    """The chrome is the host's; which messages are mine stays WhatsApp's.

    A view that hardcodes its surfaces looks like a foreign page pasted into its
    host. These pin the arrangement, because the failure is purely visual and
    nothing else in the suite would notice it.
    """

    # An assignment, not a read: `--color-x: value` defines the name, while
    # `var(--color-x, fallback)` consumes it. Only the first is wrong here.
    DEFINES_STANDARD_NAME = re.compile(r"--color-(?:background|text|border|ring)-[a-z]+\s*:")

    CHROME_HOOKS = (
        "var(--color-background-primary,",
        "var(--color-background-secondary,",
        "var(--color-background-tertiary,",
        "var(--color-text-primary,",
        "var(--color-text-secondary,",
        "var(--color-border-primary,",
        "var(--color-ring-primary,",
        "var(--font-sans,",
    )

    def test_chrome_reads_the_host_variables(self, view):
        missing = [hook for hook in self.CHROME_HOOKS if hook not in view]
        assert not missing, f"the view hardcodes what the host should supply: {missing}"

    def test_never_defines_a_name_the_host_owns(self, view):
        """Defining these locally put the fallback in two places and read as though
        this server, not the host, were supplying them."""
        found = self.DEFINES_STANDARD_NAME.search(view)
        assert found is None, f"the view defines {found.group(0)!r} instead of reading it"

    def test_outgoing_bubbles_stay_whatsapp_green(self, view):
        """Which messages are mine is meaning, not decoration -- it is how a
        transcript is read at a glance -- and no host variable means "my own
        message", so this one colour does not follow the host. Incoming does: it
        takes the host's raised surface, which is what keeps it legible anywhere."""
        assert "background: var(--wa-out);" in view
        assert "background: var(--color-background-tertiary, var(--wa-in));" in view


class TestToolBindings:
    def test_both_view_tools_are_bound(self, apps):
        names = {binding.fn.__name__ for binding in apps.tools()}
        assert names == {"list_messages", "list_chats"}

    def test_both_tools_point_at_the_one_client(self, apps):
        """Either tool opens the same two-pane client; the view routes the payload it
        receives into the matching pane and fills the other itself."""
        bound = {binding.fn.__name__: binding.meta for binding in apps.tools()}
        assert bound["list_messages"]["ui"]["resourceUri"] == CLIENT_URI
        assert bound["list_chats"]["ui"]["resourceUri"] == CLIENT_URI

    def test_each_tool_carries_the_chatgpt_alias(self, apps):
        """ChatGPT implements MCP Apps but reads the resource through its own key;
        emitting both costs one field and widens the set of hosts that render."""
        bound = {binding.fn.__name__: binding.meta for binding in apps.tools()}
        assert bound["list_messages"]["openai/outputTemplate"] == CLIENT_URI
        assert bound["list_chats"]["openai/outputTemplate"] == CLIENT_URI

    def test_a_fresh_extension_carries_the_resource_but_no_tools(self):
        """`build_apps()` only registers the view; the tools are bound by the
        decorators in `main`. Anything asserting bindings must use `main.apps`."""
        fresh = build_apps()

        assert {binding.resource.uri for binding in fresh.resources()} == {CLIENT_URI}
        assert list(fresh.tools()) == []


class TestOpenAIAlias:
    def test_alias_is_a_single_key(self):
        assert openai_alias("ui://x/y.html") == {"openai/outputTemplate": "ui://x/y.html"}


class TestAssembly:
    def test_a_view_without_its_placeholder_is_rejected(self, tmp_path, monkeypatch):
        naked = tmp_path / "naked.html"
        naked.write_text("<!doctype html><html></html>", encoding="utf-8")
        monkeypatch.setattr(apps_ui, "UI_DIR", tmp_path)

        with pytest.raises(ValueError, match="placeholder"):
            apps_ui._document("naked.html")

    def test_a_non_ui_scheme_is_rejected(self, apps):
        with pytest.raises(ValueError):
            apps.add_html_resource("https://example.test/app.html", "<html></html>")
