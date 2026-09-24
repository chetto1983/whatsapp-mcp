package main

import (
	"bytes"
	"testing"
)

func TestDownloadableMedia(t *testing.T) {
	const url = "https://mmg.whatsapp.net/m1/v/t24/abc.enc?ccb=11-4&oh=x&oe=y"
	key := bytes.Repeat([]byte{0x01}, 32)
	sha := bytes.Repeat([]byte{0x02}, 32)
	encSHA := bytes.Repeat([]byte{0x03}, 32)
	const length = 1234

	cases := []struct {
		name          string
		url           string
		mediaKey      []byte
		fileSHA256    []byte
		fileEncSHA256 []byte
		fileLength    uint64
		wantOK        bool
		wantKey       []byte // only checked when wantOK; nil means "must be nil"
		wantEnc       []byte
	}{
		{"encrypted", url, key, sha, encSHA, length, true, key, encSHA},
		{"unencrypted, NULL keys", url, nil, sha, nil, length, true, nil, nil},
		// A BLOB that was stored empty scans as a non-nil empty slice; whatsmeow's
		// unencrypted branch compares against nil, so it must be normalized.
		{"unencrypted, empty keys", url, []byte{}, sha, []byte{}, length, true, nil, nil},
		{"media key without enc hash", url, key, sha, nil, length, false, nil, nil},
		{"enc hash without media key", url, nil, sha, encSHA, length, false, nil, nil},
		{"encrypted, no url", "", key, sha, encSHA, length, false, nil, nil},
		{"encrypted, no file hash", url, key, nil, encSHA, length, false, nil, nil},
		{"encrypted, zero length", url, key, sha, encSHA, 0, false, nil, nil},
		{"unencrypted, no url", "", nil, sha, nil, length, false, nil, nil},
		{"unencrypted, no file hash", url, nil, nil, nil, length, false, nil, nil},
		{"unencrypted, zero length", url, nil, sha, nil, 0, false, nil, nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			gotKey, gotEnc, err := downloadableMedia(tc.url, tc.mediaKey, tc.fileSHA256, tc.fileEncSHA256, tc.fileLength)
			if !tc.wantOK {
				if err == nil {
					t.Fatal("expected an error, got nil")
				}
				if want := "incomplete media information for download"; err.Error() != want {
					t.Fatalf("error = %q, want %q", err, want)
				}
				if gotKey != nil || gotEnc != nil {
					t.Fatalf("expected no keys on error, got key=%v enc=%v", gotKey, gotEnc)
				}
				return
			}
			if err != nil {
				t.Fatalf("expected accept, got error: %v", err)
			}
			if tc.wantKey == nil && gotKey != nil {
				t.Fatalf("mediaKey = %#v, want nil (not an empty slice)", gotKey)
			}
			if tc.wantEnc == nil && gotEnc != nil {
				t.Fatalf("fileEncSHA256 = %#v, want nil (not an empty slice)", gotEnc)
			}
			if !bytes.Equal(gotKey, tc.wantKey) || !bytes.Equal(gotEnc, tc.wantEnc) {
				t.Fatalf("keys = (%v, %v), want (%v, %v)", gotKey, gotEnc, tc.wantKey, tc.wantEnc)
			}
		})
	}
}
