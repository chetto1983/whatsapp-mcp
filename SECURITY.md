# Security Policy

## Supported Versions

Security fixes ship on the latest minor release. Older minors are not patched.

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Reporting a Vulnerability

Please report vulnerabilities **privately** — do not open a public issue, PR, or discussion.

**Preferred:** Use GitHub's [private vulnerability reporting](https://github.com/verygoodplugins/whatsapp-mcp/security/advisories/new) on this repository. This creates a draft Security Advisory visible only to maintainers and you, and lets us collaborate on a fix in a private fork before disclosure.

**Alternative:** Email `security@verygoodplugins.com` with details.

When reporting, please include where possible:

- A description of the issue and its impact
- Affected versions
- Steps to reproduce or a proof of concept
- Any suggested mitigations

## What to Expect

- **Acknowledgment** within 72 hours of receipt
- **Initial triage and severity assessment** within 7 days
- **Fix and disclosure** for confirmed issues, typically within 30 days for high/critical severity, longer for lower-severity issues with mitigations
- A draft Security Advisory created on this repo, with you invited as a collaborator on the private fork if you'd like to participate in the fix
- A CVE requested through GitHub when the issue warrants one
- Credit in the published advisory and release notes (unless you'd prefer to remain anonymous)

If you don't hear back within 72 hours, please re-send — this is a solo-maintained project and occasional travel happens.

## Scope and Threat Model

The threat model assumes the human user of the host is trusted, but **does not** assume every process running on that host is trusted. In MCP environments, sibling MCP servers, IDE extensions, and tool-triggered flows can act as effective callers — issues that allow such callers to abuse the bridge are in scope.

**In scope:**

- The `whatsapp-bridge` Go binary and its REST/HTTP surface
- The `whatsapp-mcp-server` Python MCP server
- Published Docker images and release artifacts
- Documentation that materially affects security posture (e.g. install or configuration instructions)

**Out of scope:**

- WhatsApp itself, the WhatsApp Web protocol, or `whatsmeow` upstream (please report those upstream)
- Third-party MCP clients consuming this server
- Social engineering, physical attacks, or attacks requiring root/admin compromise of the host
- Denial of service via brute request volume
- Issues that require the user to deliberately install untrusted code outside this project's release artifacts

## Disclosure Policy

We follow coordinated disclosure. Once a fix is available and released, the Security Advisory is published and credit is given to the reporter. Disclosure dates are coordinated with the reporter where reasonable.

## Fixed Issues

### 0.2.1 — media path confinement

Two path-handling issues in the Go bridge, found while triaging CodeQL alerts and fixed in [#3](https://github.com/chetto1983/whatsapp-mcp/pull/3) and [#5](https://github.com/chetto1983/whatsapp-mcp/pull/5):

- **Remote file write via a sender-controlled path component.** Incoming media is downloaded automatically to `store/<chat_jid>/<name>`, and part of that name came from the message ID — which whatsmeow takes verbatim from the stanza's `id` attribute, so the sender picks it. Document messages get no extension appended, leaving the tail of the path under the sender's control: a crafted ID could place sender-supplied bytes outside `store/`, with no action by the user. Each component is now reduced to a single path segment, and every mkdir/stat/write goes through an `os.Root` anchored at `store/`.
- **Check-then-read window on `/api/send`.** `media_path` was confined to `WHATSAPP_MEDIA_ROOTS` by a prefix comparison and then read with `os.ReadFile`, leaving a window in which a path component could be swapped for a symlink after the check. The read now goes through an `os.Root` anchored at the matching root.

Both are fixed in 0.2.1. Upgrading needs no migration: file and directory names on disk are unchanged.

### Upstream status

This project descends from [`lharries/whatsapp-mcp`](https://github.com/lharries/whatsapp-mcp), which reaches the same class of issue by a different route and has not fixed it. That repository has merged no pull request since March 2025 and its last commit is from July 2025, so a fix there should not be expected. If you run it, or a fork taken from it, apply the equivalent change — the patch here is a reasonable starting point.

## Acknowledgments

Researchers who responsibly disclose vulnerabilities are credited here once the corresponding fix has shipped. Thanks to everyone who keeps this project safer.
