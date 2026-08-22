package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Names the bridge already writes must survive untouched: changing them would
// orphan every chat directory and media file downloaded so far.
func TestSanitizeStoreSegmentPreservesExistingNames(t *testing.T) {
	for _, s := range []string{
		"393331234567@s.whatsapp.net",
		"120363012345678901@g.us",
		"185098765432101@lid",
		"status@broadcast",
		"3EB0C767D26A1D8E4F2B",
		"BAE5F1A2B3C4D5E6",
		"image_20260822_101112_ABC.jpg",
	} {
		if got := sanitizeStoreSegment(s); got != s {
			t.Errorf("sanitizeStoreSegment(%q) = %q, want it unchanged", s, got)
		}
	}
}

// A colon is illegal in a Windows filename and used to be stripped by hand in
// downloadMedia; keep that behaviour.
func TestSanitizeStoreSegmentReplacesColonAsBefore(t *testing.T) {
	const in = "393331234567:12@s.whatsapp.net"
	const want = "393331234567_12@s.whatsapp.net"
	if got := sanitizeStoreSegment(in); got != want {
		t.Errorf("sanitizeStoreSegment(%q) = %q, want %q", in, got, want)
	}
}

func TestSanitizeStoreSegmentNeutralizesTraversal(t *testing.T) {
	hostile := []string{
		"../../../../etc/cron.d/evil",
		"../../../../home/user/.ssh/authorized_keys",
		`..\..\..\Windows\System32\drivers\etc\hosts`,
		"..",
		".",
		"...",
		"",
		"/absolute/path",
		"a/b",
		"C:evil",
		"id\x00.jpg",
		strings.Repeat("A", 4096),
	}

	for _, in := range hostile {
		got := sanitizeStoreSegment(in)

		if got == "" || got == "." || got == ".." {
			t.Errorf("sanitizeStoreSegment(%q) = %q, not a usable path component", in, got)
		}
		if strings.ContainsAny(got, `/\:`+"\x00") {
			t.Errorf("sanitizeStoreSegment(%q) = %q, still contains a separator", in, got)
		}
		if len(got) > maxStoreSegment {
			t.Errorf("sanitizeStoreSegment(%q) is %d bytes, cap is %d", in, len(got), maxStoreSegment)
		}

		// The property that matters: joining the result under a directory
		// cannot land anywhere but in that directory.
		parent := filepath.Join(mediaStoreDir, "chat")
		if joined := filepath.Join(parent, got); filepath.Dir(joined) != parent {
			t.Errorf("sanitizeStoreSegment(%q) = %q escapes its directory: %q", in, got, joined)
		}
	}
}

// Second guard: even if a separator ever made it through sanitizeStoreSegment,
// os.Root refuses to act outside the store directory.
func TestMediaStoreRootRefusesToEscape(t *testing.T) {
	t.Chdir(t.TempDir())

	root, err := openMediaStoreRoot()
	if err != nil {
		t.Fatalf("openMediaStoreRoot() failed: %v", err)
	}
	defer func() { _ = root.Close() }()

	if err := root.WriteFile(filepath.Join("..", "escaped.txt"), []byte("nope"), 0o600); err == nil {
		t.Error("expected os.Root to reject a write above the store directory")
	}
	if _, err := os.Stat("escaped.txt"); err == nil {
		t.Error("write escaped the store directory")
	}

	// A well-formed write still lands where downloadMedia expects it.
	const chat = "393331234567@s.whatsapp.net"
	if err := root.MkdirAll(chat, 0755); err != nil {
		t.Fatalf("MkdirAll(%q) failed: %v", chat, err)
	}
	rel := filepath.Join(chat, "image_20260822_101112_ABC.jpg")
	if err := root.WriteFile(rel, []byte("jpeg"), 0644); err != nil {
		t.Fatalf("WriteFile(%q) failed: %v", rel, err)
	}
	if _, err := os.Stat(filepath.Join(mediaStoreDir, rel)); err != nil {
		t.Fatalf("expected the file inside the store: %v", err)
	}
}

// openMediaStoreRoot is called on a bridge whose store/ may not exist yet.
func TestOpenMediaStoreRootCreatesMissingDirectory(t *testing.T) {
	t.Chdir(t.TempDir())

	root, err := openMediaStoreRoot()
	if err != nil {
		t.Fatalf("openMediaStoreRoot() failed: %v", err)
	}
	defer func() { _ = root.Close() }()

	info, err := os.Stat(mediaStoreDir)
	if err != nil {
		t.Fatalf("stat %s: %v", mediaStoreDir, err)
	}
	if !info.IsDir() {
		t.Fatalf("%s is not a directory", mediaStoreDir)
	}
}
