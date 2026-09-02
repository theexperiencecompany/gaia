//go:build darwin

package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/sha256"
	"testing"
)

// encryptLikeChrome mirrors macOS Chrome: AES-128-CBC, IV = 16 spaces, PKCS7
// pad, "v10" tag. Proves decryptValue is correct without touching the Keychain.
func encryptLikeChrome(t *testing.T, key, plaintext []byte) []byte {
	t.Helper()
	pad := aes.BlockSize - len(plaintext)%aes.BlockSize
	padded := append(plaintext, bytes.Repeat([]byte{byte(pad)}, pad)...)
	block, err := aes.NewCipher(key)
	if err != nil {
		t.Fatal(err)
	}
	out := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, cookieIV).CryptBlocks(out, padded)
	return append([]byte("v10"), out...)
}

func testBlock(t *testing.T) cipher.Block {
	t.Helper()
	block, err := aes.NewCipher(bytes.Repeat([]byte{0x11}, 16))
	if err != nil {
		t.Fatal(err)
	}
	return block
}

func TestDecryptValueRoundTrips(t *testing.T) {
	key := bytes.Repeat([]byte{0x11}, 16)
	enc := encryptLikeChrome(t, key, []byte("session=abc123"))
	got, ok := decryptValue(testBlock(t), enc, "github.com")
	if !ok || got != "session=abc123" {
		t.Fatalf("round-trip failed: got %q ok=%v", got, ok)
	}
}

func TestDecryptValueStripsDomainHashPrefix(t *testing.T) {
	// Recent Chrome prepends a 32-byte binary SHA256 domain hash to the value.
	key := bytes.Repeat([]byte{0x11}, 16)
	host := "accounts.google.com"
	hash := sha256.Sum256([]byte(host))
	enc := encryptLikeChrome(t, key, append(hash[:], []byte("realvalue")...))
	got, ok := decryptValue(testBlock(t), enc, host)
	if !ok || got != "realvalue" {
		t.Fatalf("hash prefix not stripped: got %q ok=%v", got, ok)
	}
}

func TestDecryptValueRejectsUntaggedData(t *testing.T) {
	// A plaintext (unencrypted) cookie has no v10/v11 tag — skip, never emit garbage.
	if _, ok := decryptValue(testBlock(t), []byte("plainvalue"), "x"); ok {
		t.Fatal("untagged value should be rejected")
	}
}

func TestDecryptValueDoesNotStripALongValueThatIsNotTheHostHash(t *testing.T) {
	// A 40-byte value whose first 32 bytes are not SHA256(host) must survive whole.
	key := bytes.Repeat([]byte{0x11}, 16)
	value := bytes.Repeat([]byte("a"), 40)
	enc := encryptLikeChrome(t, key, value)
	got, ok := decryptValue(testBlock(t), enc, "example.com")
	if !ok || got != string(value) {
		t.Fatalf("long non-hash value was wrongly truncated: got %q", got)
	}
}
