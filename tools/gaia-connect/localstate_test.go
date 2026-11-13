package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"strings"
	"testing"
)

// windowsKey is a fixed 32-byte AES key standing in for the one DPAPI unseals.
var windowsKey = bytes.Repeat([]byte{0x22}, gcmKeyLen)

// encryptLikeWindowsChromium mirrors Chromium on Windows: "v10" tag, 12-byte
// nonce, AES-256-GCM ciphertext+tag.
func encryptLikeWindowsChromium(t *testing.T, key, nonce, plaintext []byte) []byte {
	t.Helper()
	block, err := aes.NewCipher(key)
	if err != nil {
		t.Fatal(err)
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		t.Fatal(err)
	}
	return append(append([]byte("v10"), nonce...), aead.Seal(nil, nonce, plaintext, nil)...)
}

func localStateJSON(encryptedKey []byte) []byte {
	return []byte(`{"os_crypt":{"encrypted_key":"` +
		base64.StdEncoding.EncodeToString(encryptedKey) + `"}}`)
}

func TestMasterKeyFromLocalState(t *testing.T) {
	sealed := append([]byte(dpapiPrefix), []byte("sealed")...)
	unseal := func(blob []byte) ([]byte, error) {
		if string(blob) != "sealed" {
			return nil, errors.New("the DPAPI prefix was not stripped")
		}
		return windowsKey, nil
	}

	for _, tc := range []struct {
		name    string
		state   []byte
		unseal  dpapiUnprotect
		wantErr string
	}{
		{name: "happy path", state: localStateJSON(sealed), unseal: unseal},
		{name: "not json", state: []byte("{nope"), unseal: unseal, wantErr: "parse Local State"},
		{name: "no key", state: []byte(`{"os_crypt":{}}`), unseal: unseal, wantErr: "no os_crypt.encrypted_key"},
		{
			name: "missing DPAPI prefix", state: localStateJSON([]byte("raw-blob")),
			unseal: unseal, wantErr: "not a DPAPI blob",
		},
		{
			name: "DPAPI refuses", state: localStateJSON(sealed),
			unseal:  func([]byte) ([]byte, error) { return nil, errors.New("access denied") },
			wantErr: "access denied",
		},
		{
			name: "wrong key length", state: localStateJSON(sealed),
			unseal:  func([]byte) ([]byte, error) { return []byte("short"), nil },
			wantErr: "cookie key is 5 bytes",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			key, err := masterKeyFromLocalState(tc.state, tc.unseal)
			if tc.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("err = %v, want it to mention %q", err, tc.wantErr)
				}
				return
			}
			if err != nil || !bytes.Equal(key, windowsKey) {
				t.Fatalf("key = %x err = %v", key, err)
			}
		})
	}
}

func TestGCMDecrypter(t *testing.T) {
	decrypt, err := newGCMDecrypter(windowsKey)
	if err != nil {
		t.Fatal(err)
	}
	nonce := bytes.Repeat([]byte{0x07}, gcmNonceEnd-gcmNonceStart)
	hostHash := sha256.Sum256([]byte("accounts.google.com"))

	t.Run("v10 round trip", func(t *testing.T) {
		enc := encryptLikeWindowsChromium(t, windowsKey, nonce, []byte("sid=win"))
		value, ok, err := decrypt(enc, "example.com")
		if err != nil || !ok || value != "sid=win" {
			t.Fatalf("= %q ok=%v err=%v", value, ok, err)
		}
	})

	t.Run("host hash prefix stripped", func(t *testing.T) {
		enc := encryptLikeWindowsChromium(t, windowsKey, nonce, append(hostHash[:], []byte("realvalue")...))
		value, ok, err := decrypt(enc, "accounts.google.com")
		if err != nil || !ok || value != "realvalue" {
			t.Fatalf("= %q ok=%v err=%v", value, ok, err)
		}
	})

	t.Run("tampered ciphertext is skipped not corrupted", func(t *testing.T) {
		enc := encryptLikeWindowsChromium(t, windowsKey, nonce, []byte("sid=win"))
		enc[len(enc)-1] ^= 0xff
		if value, ok, err := decrypt(enc, "example.com"); ok || err != nil {
			t.Fatalf("= %q ok=%v err=%v, want skipped", value, ok, err)
		}
	})

	t.Run("app-bound v20 fails loud", func(t *testing.T) {
		_, _, err := decrypt(append([]byte("v20"), make([]byte, 32)...), "example.com")
		if err == nil || !strings.Contains(err.Error(), "App-Bound Encryption") {
			t.Fatalf("err = %v, want an App-Bound Encryption failure", err)
		}
	})

	t.Run("plaintext row skipped", func(t *testing.T) {
		if _, ok, err := decrypt([]byte("plainvalue"), "x"); ok || err != nil {
			t.Fatalf("ok=%v err=%v, want skipped", ok, err)
		}
	})
}
