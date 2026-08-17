"""Tests for the MCP Apps views (`io.modelcontextprotocol/ui`)."""

import re

import pytest
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

import apps_ui
import main
from apps_ui import CHATS_URI, THREAD_URI, build_apps, openai_alias

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


class TestExtensionIdentity:
    def test_identifier_is_the_spec_one(self, apps):
        assert apps.identifier == EXTENSION_ID == "io.modelcontextprotocol/ui"


class TestResources:
    def test_both_views_are_registered(self, resources):
        assert set(resources) == {THREAD_URI, CHATS_URI}

    @pytest.mark.parametrize("uri", [THREAD_URI, CHATS_URI])
    def test_served_as_an_app_document(self, resources, uri):
        assert resources[uri].mime_type == APP_MIME_TYPE

    @pytest.mark.parametrize("uri", [THREAD_URI, CHATS_URI])
    def test_no_placeholder_survives_assembly(self, resources, uri):
        """A view that shipped with its placeholder intact would render, then never
        speak to the host — the failure is silent, so it is asserted."""
        html = resources[uri].text
        for marker, _ in apps_ui._INCLUDES:
            assert marker not in html

    @pytest.mark.parametrize("uri", [THREAD_URI, CHATS_URI])
    def test_bridge_and_theme_are_inlined(self, resources, uri):
        html = resources[uri].text
        assert "window.McpApp" in html, "the postMessage bridge is missing"
        assert "ui/notifications/initialized" in html, "the handshake is missing"
        assert "--font-wa" in html, "the shared theme is missing"

    @pytest.mark.parametrize("uri", [THREAD_URI, CHATS_URI])
    def test_declares_a_sealed_csp(self, resources, uri):
        """Neither view fetches anything, and says so: every domain list is empty,
        so a host sandbox seals the iframe instead of applying a default."""
        ui = resources[uri].meta["ui"]
        assert ui["csp"] == {
            "connectDomains": [],
            "resourceDomains": [],
            "frameDomains": [],
            "baseUriDomains": [],
        }

    @pytest.mark.parametrize("uri", [THREAD_URI, CHATS_URI])
    def test_view_never_writes_untrusted_text_as_markup(self, resources, uri):
        """Message bodies, chat names and JIDs are third-party text. They reach the
        DOM through textContent; an innerHTML assignment here would be an injection
        sink fed straight from WhatsApp."""
        found = MARKUP_SINKS.search(resources[uri].text)
        assert found is None, f"{uri} writes markup through {found.group(0)!r}"


class TestToolBindings:
    def test_both_view_tools_are_bound(self, apps):
        names = {binding.fn.__name__ for binding in apps.tools()}
        assert names == {"list_messages", "list_chats"}

    def test_each_tool_points_at_its_view(self, apps):
        bound = {binding.fn.__name__: binding.meta for binding in apps.tools()}
        assert bound["list_messages"]["ui"]["resourceUri"] == THREAD_URI
        assert bound["list_chats"]["ui"]["resourceUri"] == CHATS_URI

    def test_each_tool_carries_the_chatgpt_alias(self, apps):
        """ChatGPT implements MCP Apps but reads the resource through its own key;
        emitting both costs one field and widens the set of hosts that render."""
        bound = {binding.fn.__name__: binding.meta for binding in apps.tools()}
        assert bound["list_messages"]["openai/outputTemplate"] == THREAD_URI
        assert bound["list_chats"]["openai/outputTemplate"] == CHATS_URI

    def test_a_fresh_extension_carries_resources_but_no_tools(self):
        """`build_apps()` only registers the views; the tools are bound by the
        decorators in `main`. Anything asserting bindings must use `main.apps`."""
        fresh = build_apps()

        assert {binding.resource.uri for binding in fresh.resources()} == {THREAD_URI, CHATS_URI}
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
