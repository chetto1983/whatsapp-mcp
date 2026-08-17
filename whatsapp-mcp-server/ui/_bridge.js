/**
 * A dependency-free MCP Apps view client: JSON-RPC 2.0 over postMessage.
 *
 * The ext-apps SDK is TypeScript and expects a bundler. A `ui://` resource is a
 * single self-contained HTML document, so this file is inlined into each app
 * instead — the spec is explicit that no SDK is needed to talk to the host
 * (ext-apps specification/2026-01-26/apps.mdx §"Transport Layer").
 *
 * It deliberately differs from the sample in that section on one point: the
 * sample's listener rejects the pending promise on *any* message that is not
 * its own response, which fails every request as soon as the host sends a
 * notification. Here an unrelated message is simply not ours, and is ignored.
 */
(function () {
  "use strict";

  const pending = new Map();
  const onNotification = new Map();
  const onRequest = new Map();
  let nextId = 1;

  function post(message) {
    window.parent.postMessage(message, "*");
  }

  function request(method, params) {
    const id = nextId++;
    return new Promise(function (resolve, reject) {
      pending.set(id, { resolve: resolve, reject: reject });
      post({ jsonrpc: "2.0", id: id, method: method, params: params || {} });
    });
  }

  function notify(method, params) {
    post({ jsonrpc: "2.0", method: method, params: params || {} });
  }

  window.addEventListener("message", function (event) {
    const msg = event.data;
    if (!msg || msg.jsonrpc !== "2.0") return;

    // A response carries an id and no method.
    if (msg.method === undefined) {
      const slot = pending.get(msg.id);
      if (!slot) return;
      pending.delete(msg.id);
      if (msg.error) slot.reject(new Error(msg.error.message || "request failed"));
      else slot.resolve(msg.result);
      return;
    }

    // A request from the host carries both. It MUST be answered — an
    // unanswered ui/resource-teardown leaves the host waiting on us.
    if (msg.id !== undefined) {
      const handler = onRequest.get(msg.method);
      Promise.resolve(handler ? handler(msg.params || {}) : {})
        .then(function (result) {
          post({ jsonrpc: "2.0", id: msg.id, result: result || {} });
        })
        .catch(function (err) {
          post({
            jsonrpc: "2.0",
            id: msg.id,
            error: { code: -32000, message: String((err && err.message) || err) },
          });
        });
      return;
    }

    const handler = onNotification.get(msg.method);
    if (handler) handler(msg.params || {});
  });

  /**
   * Adopt the host's look where it offers one. The host's variables win over the
   * app's palette so a View sits inside its host rather than beside it; every
   * variable the host omits falls through to the app's own definition.
   */
  function applyHostContext(ctx) {
    if (!ctx) return;
    const root = document.documentElement;
    if (ctx.theme) root.setAttribute("data-theme", ctx.theme);
    const styles = ctx.styles || {};
    const variables = styles.variables || {};
    Object.keys(variables).forEach(function (key) {
      if (variables[key] != null) root.style.setProperty(key, variables[key]);
    });
    const fonts = styles.css && styles.css.fonts;
    if (fonts) {
      const sheet = document.createElement("style");
      sheet.textContent = fonts;
      document.head.appendChild(sheet);
    }
    const insets = ctx.safeAreaInsets;
    if (insets) {
      ["top", "right", "bottom", "left"].forEach(function (side) {
        if (insets[side] != null) root.style.setProperty("--safe-" + side, insets[side] + "px");
      });
    }
  }

  /**
   * Register handlers, then perform the ui/initialize → ui/notifications/initialized
   * handshake. Handlers are registered BEFORE the handshake because the host may
   * send ui/notifications/tool-input the moment initialize resolves.
   */
  async function start(options) {
    const opts = options || {};
    onRequest.set("ui/resource-teardown", opts.onTeardown || function () { return {}; });
    onNotification.set("ui/notifications/tool-input", opts.onToolInput || function () {});
    onNotification.set("ui/notifications/tool-input-partial", opts.onToolInputPartial || function () {});
    onNotification.set("ui/notifications/tool-result", opts.onToolResult || function () {});
    onNotification.set("ui/notifications/tool-cancelled", opts.onToolCancelled || function () {});
    onNotification.set("ui/notifications/host-context-changed", function (params) {
      applyHostContext(params && params.hostContext ? params.hostContext : params);
    });

    const result = await request("ui/initialize", {
      protocolVersion: "2026-01-26",
      clientInfo: { name: opts.name || "mcp-app", version: opts.version || "1.0.0" },
      appCapabilities: { availableDisplayModes: ["inline", "fullscreen"] },
    });
    applyHostContext(result && result.hostContext);
    notify("ui/notifications/initialized", {});
    return result;
  }

  /**
   * A tool result carries its payload three ways depending on the server's return
   * type and the host's wrapping. Read them in order of fidelity and stop at the
   * first that yields a list — never guess from a single shape.
   */
  function payloadOf(result) {
    if (!result) return null;
    const structured = result.structuredContent;
    if (structured) {
      if (Array.isArray(structured)) return structured;
      if (Array.isArray(structured.result)) return structured.result;
      return structured;
    }
    const content = result.content;
    if (Array.isArray(content)) {
      for (let i = 0; i < content.length; i++) {
        if (content[i] && content[i].type === "text") {
          try {
            return JSON.parse(content[i].text);
          } catch (_) {
            /* not JSON — the next block may be */
          }
        }
      }
    }
    return null;
  }

  window.McpApp = {
    start: start,
    payloadOf: payloadOf,
    callTool: function (name, args) {
      return request("tools/call", { name: name, arguments: args || {} });
    },
    sendToChat: function (text) {
      return request("ui/message", { role: "user", content: { type: "text", text: text } });
    },
    openLink: function (url) {
      return request("ui/open-link", { url: url });
    },
    requestDisplayMode: function (mode) {
      return request("ui/request-display-mode", { mode: mode });
    },
    log: function (level, data) {
      notify("notifications/message", { level: level, data: data });
    },
  };
})();
