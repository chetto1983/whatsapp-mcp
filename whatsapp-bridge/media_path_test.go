package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// helper: create a temporary file inside dir and return its path.
func writeFile(t *testing.T, dir, name, content string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", p, err)
	}
	return p
}

func TestPathHasPrefix(t *testing.T) {
	sep := string(os.PathSeparator)
	cases := []struct {
		child, parent string
		want          bool
	}{
		{"/a/b", "/a/b", true},
		{"/a/b" + sep + "c", "/a/b", true},
		{"/a/bbb", "/a/b", false}, // sibling-prefix attack
		{"/a", "/a/b", false},     // shorter
		{"", "/a", false},
	}
	for _, tc := range cases {
		t.Run(tc.child+"|"+tc.parent, func(t *testing.T) {
			if got := pathHasPrefix(tc.child, tc.parent); got != tc.want {
				t.Fatalf("pathHasPrefix(%q,%q) = %v, want %v", tc.child, tc.parent, got, tc.want)
			}
		})
	}
}

func TestValidateMediaPathAcceptsFileInsideRoot(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatalf("eval root: %v", err)
	}
	f := writeFile(t, root, "ok.txt", "hello")

	got, err := validateMediaPath(f, []string{resolvedRoot})
	if err != nil {
		t.Fatalf("expected accept, got error: %v", err)
	}
	resolvedFile, _ := filepath.EvalSymlinks(f)
	if got != resolvedFile {
		t.Fatalf("expected resolved path %q, got %q", resolvedFile, got)
	}
}

func TestValidateMediaPathRejectsOutsideRoot(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, _ := filepath.EvalSymlinks(root)
	other := t.TempDir()
	f := writeFile(t, other, "elsewhere.txt", "nope")

	if _, err := validateMediaPath(f, []string{resolvedRoot}); err == nil {
		t.Fatal("expected error for path outside root, got nil")
	}
}

func TestValidateMediaPathRejectsSymlinkEscape(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink semantics differ on Windows; covered by Unix CI")
	}
	root := t.TempDir()
	resolvedRoot, _ := filepath.EvalSymlinks(root)
	secrets := t.TempDir()
	target := writeFile(t, secrets, "id_rsa", "PRETEND-PRIVATE-KEY")

	// Drop a symlink inside the allowed root that points at a file outside.
	link := filepath.Join(root, "stolen")
	if err := os.Symlink(target, link); err != nil {
		t.Fatalf("symlink: %v", err)
	}

	if _, err := validateMediaPath(link, []string{resolvedRoot}); err == nil {
		t.Fatal("expected symlink escape to be rejected, got nil error")
	} else if !strings.Contains(err.Error(), "outside the configured media roots") {
		t.Fatalf("expected confinement error, got: %v", err)
	}
}

func TestValidateMediaPathRejectsRelative(t *testing.T) {
	if _, err := validateMediaPath("not/absolute.txt", []string{"/tmp"}); err == nil {
		t.Fatal("expected error for relative path")
	}
}

func TestReadMediaFileRejectsDirectory(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, _ := filepath.EvalSymlinks(root)
	subdir := filepath.Join(root, "sub")
	if err := os.Mkdir(subdir, 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if _, _, err := readMediaFile(subdir, []string{resolvedRoot}); err == nil {
		t.Fatal("expected error for directory, got nil")
	} else if !strings.Contains(err.Error(), "not a regular file") {
		t.Fatalf("expected a regular-file error, got: %v", err)
	}
}

func TestReadMediaFileReturnsContentsInsideRoot(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatalf("eval root: %v", err)
	}
	if err := os.Mkdir(filepath.Join(root, "nested"), 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	const want = "PRETEND-JPEG-BYTES"
	f := writeFile(t, filepath.Join(root, "nested"), "photo.jpg", want)

	data, canonical, err := readMediaFile(f, []string{resolvedRoot})
	if err != nil {
		t.Fatalf("expected accept, got error: %v", err)
	}
	if string(data) != want {
		t.Fatalf("data = %q, want %q", data, want)
	}
	resolvedFile, _ := filepath.EvalSymlinks(f)
	if canonical != resolvedFile {
		t.Fatalf("canonical = %q, want %q", canonical, resolvedFile)
	}
}

func TestReadMediaFileRejectsOutsideRoot(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, _ := filepath.EvalSymlinks(root)
	outside := t.TempDir()
	f := writeFile(t, outside, "id_rsa", "PRETEND-PRIVATE-KEY")

	data, _, err := readMediaFile(f, []string{resolvedRoot})
	if err == nil {
		t.Fatal("expected a file outside the root to be rejected")
	}
	if data != nil {
		t.Fatalf("expected no bytes on rejection, got %d", len(data))
	}
	if !strings.Contains(err.Error(), "outside the configured media roots") {
		t.Fatalf("expected the confinement error, got: %v", err)
	}
}

func TestReadMediaFileRejectsSymlinkEscape(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink semantics differ on Windows; covered by Unix CI")
	}
	root := t.TempDir()
	resolvedRoot, _ := filepath.EvalSymlinks(root)
	secrets := t.TempDir()
	target := writeFile(t, secrets, "id_rsa", "PRETEND-PRIVATE-KEY")

	link := filepath.Join(root, "stolen")
	if err := os.Symlink(target, link); err != nil {
		t.Fatalf("symlink: %v", err)
	}

	if _, _, err := readMediaFile(link, []string{resolvedRoot}); err == nil {
		t.Fatal("expected symlink escape to be rejected, got nil error")
	}
}

// The path handed to os.Root must be relative and free of "..", otherwise the
// root would reject legitimate files or be given something to climb with.
func TestOpenContainingRootRelativizesWithoutEscaping(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatalf("eval root: %v", err)
	}
	canonical := filepath.Join(resolvedRoot, "nested", "photo.jpg")

	opened, rel, err := openContainingRoot(canonical, []string{resolvedRoot})
	if err != nil {
		t.Fatalf("openContainingRoot failed: %v", err)
	}
	defer func() { _ = opened.Close() }()

	if filepath.IsAbs(rel) {
		t.Fatalf("rel = %q, want a relative path", rel)
	}
	if strings.HasPrefix(rel, "..") {
		t.Fatalf("rel = %q, want no parent traversal", rel)
	}
	if want := filepath.Join("nested", "photo.jpg"); rel != want {
		t.Fatalf("rel = %q, want %q", rel, want)
	}
}

func TestResolveMediaRootsRejectsRelativeEnv(t *testing.T) {
	t.Setenv("WHATSAPP_MEDIA_ROOTS", "relative/path")
	if _, err := resolveMediaRoots(); err == nil {
		t.Fatal("expected error for relative path in env, got nil")
	}
}

func TestResolveMediaRootsAcceptsEnvList(t *testing.T) {
	a := t.TempDir()
	b := t.TempDir()
	t.Setenv("WHATSAPP_MEDIA_ROOTS", a+string(os.PathListSeparator)+b)

	roots, err := resolveMediaRoots()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(roots) != 2 {
		t.Fatalf("expected 2 roots, got %d", len(roots))
	}
}

// The rejection for a path outside the roots must not double as a filesystem
// probe: an existing file and a missing one have to come back the same way.
func TestValidateMediaPathDoesNotLeakExistenceOutsideRoots(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, _ := filepath.EvalSymlinks(root)
	outside := t.TempDir()
	existing := writeFile(t, outside, "secret.txt", "PRETEND-SECRET")
	missing := filepath.Join(outside, "does-not-exist.txt")

	for _, tc := range []struct{ name, path string }{
		{"existing", existing},
		{"missing", missing},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := validateMediaPath(tc.path, []string{resolvedRoot})
			if err == nil {
				t.Fatalf("expected %s path outside the root to be rejected", tc.name)
			}
			if !strings.Contains(err.Error(), "outside the configured media roots") {
				t.Fatalf("expected the confinement error, got: %v", err)
			}
			for _, leak := range []string{"no such file", "cannot find", "stat media_path", "not a regular file"} {
				if strings.Contains(err.Error(), leak) {
					t.Fatalf("error leaks filesystem state (%q): %v", leak, err)
				}
			}
		})
	}
}

// Inside the root the caller owns the directory, so a missing file should
// still produce a useful error rather than the generic rejection.
func TestValidateMediaPathReportsMissingFileInsideRoot(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatalf("eval root: %v", err)
	}

	_, err = validateMediaPath(filepath.Join(resolvedRoot, "gone.txt"), []string{resolvedRoot})
	if err == nil {
		t.Fatal("expected an error for a missing file")
	}
	if !strings.Contains(err.Error(), "resolve media_path") {
		t.Fatalf("expected a resolve error inside the root, got: %v", err)
	}
}
