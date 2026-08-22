package main

// Inbound media-path confinement.
//
// Incoming media is auto-downloaded (see downloadMedia) to
// store/<chat_jid>/<type>_<timestamp>_<message_id><ext>. Two of those
// components come off the wire: the chat JID, and the message ID — which
// whatsmeow takes verbatim from the stanza's id attribute
// (message.go: info.ID = types.MessageID(ag.String("id"))), so the sender
// picks it. Document messages get no extension appended, which means an ID
// such as "../../../../home/user/.ssh/authorized_keys" would turn the
// download into an arbitrary file write with sender-controlled content.
//
// Two independent guards, either of which is sufficient:
//  1. sanitizeStoreSegment reduces each component to one safe path segment
//     before it is joined.
//  2. every mkdir/stat/write goes through os.Root, which refuses to leave
//     the store directory even if (1) ever lets something through.

import (
	"fmt"
	"os"
	"strings"
)

// mediaStoreDir is the bridge's media directory, relative to the working
// directory the bridge was started from.
const mediaStoreDir = "store"

// maxStoreSegment caps a single path component. Real message IDs are 20-32
// characters and JIDs are shorter, so anything longer is already anomalous;
// the cap keeps us clear of the 255-byte per-component limit that ext4 and
// APFS enforce.
const maxStoreSegment = 128

// sanitizeStoreSegment reduces s to a single filesystem-safe path component.
//
// The allow-list is exactly the set of characters that occur in the names we
// write today — WhatsApp JIDs ("393331234567@s.whatsapp.net", "120363-16@g.us",
// "<random>@lid") and message IDs (hex) — so existing chat directories and
// media files keep their current names and nothing needs migrating. Everything
// else collapses to "_": both path separators, "..", NUL, and the characters
// Windows rejects in a filename.
func sanitizeStoreSegment(s string) string {
	if len(s) > maxStoreSegment {
		s = s[:maxStoreSegment]
	}

	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9',
			r == '.', r == '-', r == '_', r == '@':
			b.WriteRune(r)
		default:
			b.WriteByte('_')
		}
	}

	// "", "." and ".." are not usable as a component, and neither is any
	// other all-dots string.
	out := b.String()
	if strings.Trim(out, ".") == "" {
		return "_"
	}
	return out
}

// openMediaStoreRoot opens the store directory as an os.Root. Every path
// operation performed on the returned root is confined to it, including
// through symlinks planted inside the store. Callers must Close it.
func openMediaStoreRoot() (*os.Root, error) {
	if err := os.MkdirAll(mediaStoreDir, 0755); err != nil {
		return nil, fmt.Errorf("create %s: %w", mediaStoreDir, err)
	}
	return os.OpenRoot(mediaStoreDir)
}
