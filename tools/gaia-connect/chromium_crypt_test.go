package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

// encryptLikeChromium mirrors what Chromium writes on macOS and Linux:
// AES-128-CBC, IV = 16 spaces, PKCS7 pad, version tag in front. Proves the
// shared decrypt is correct without touching a Keychain or a keyring.
func encryptLikeChromium(t *testing.T, block cipher.Block, tag string, plaintext []byte) []byte {
	t.Helper()
	pad := aes.BlockSize - len(plaintext)%aes.BlockSize
	padded := append(plaintext, bytes.Repeat([]byte{byte(pad)}, pad)...)
	out := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, cookieIV).CryptBlocks(out, padded)
	return append([]byte(tag), out...)
}

func testBlock(t *testing.T) cipher.Block {
	t.Helper()
	block, err := aes.NewCipher(bytes.Repeat([]byte{0x11}, cookieKeyLen))
	if err != nil {
		t.Fatal(err)
	}
	return block
}

// TestCookieKeyKnownAnswers pins both key derivations against vectors computed
// independently with Python's hashlib.pbkdf2_hmac('sha1', …). Change the salt,
// the digest, the length or an iteration count and these move.
func TestCookieKeyKnownAnswers(t *testing.T) {
	for _, tc := range []struct {
		name       string
		secret     string
		iterations int
		want       string
	}{
		{"linux basic store", basicStorePassword, linuxPBKDF2Iterations, "fd621fe5a2b402539dfa147ca9272778"},
		{"macOS keychain secret", "peanuts", macPBKDF2Iterations, "d9a09d499b4e1b7461f28e67972c6dbd"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			key, err := cookieKey(tc.secret, tc.iterations)
			if err != nil {
				t.Fatal(err)
			}
			if got := hex.EncodeToString(key); got != tc.want {
				t.Fatalf("cookieKey = %s, want %s", got, tc.want)
			}
		})
	}
}

func TestDecryptValue(t *testing.T) {
	block := testBlock(t)
	hostHash := sha256.Sum256([]byte("accounts.google.com"))

	for _, tc := range []struct {
		name  string
		enc   []byte
		host  string
		want  string
		wantK bool
	}{
		{
			name: "v10 round trip",
			enc:  encryptLikeChromium(t, block, "v10", []byte("session=abc123")),
			host: "github.com", want: "session=abc123", wantK: true,
		},
		{
			name: "v11 round trip",
			enc:  encryptLikeChromium(t, block, "v11", []byte("session=abc123")),
			host: "github.com", want: "session=abc123", wantK: true,
		},
		{
			// Recent Chrome prepends a 32-byte binary SHA256 domain hash.
			name: "host hash prefix stripped",
			enc:  encryptLikeChromium(t, block, "v10", append(hostHash[:], []byte("realvalue")...)),
			host: "accounts.google.com", want: "realvalue", wantK: true,
		},
		{
			// A 40-byte value whose first 32 bytes are not SHA256(host) survives whole.
			name: "long non-hash value untouched",
			enc:  encryptLikeChromium(t, block, "v10", bytes.Repeat([]byte("a"), 40)),
			host: "example.com", want: string(bytes.Repeat([]byte("a"), 40)), wantK: true,
		},
		{
			// A plaintext (unencrypted) cookie has no tag — skip, never emit garbage.
			name: "untagged value rejected",
			enc:  []byte("plainvalue"), host: "x", wantK: false,
		},
		{
			name: "v20 is not a CBC value",
			enc:  append([]byte("v20"), bytes.Repeat([]byte{0}, 32)...),
			host: "x", wantK: false,
		},
		{name: "empty value rejected", enc: nil, host: "x", wantK: false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, ok := decryptValue(block, tc.enc, tc.host)
			if ok != tc.wantK || got != tc.want {
				t.Fatalf("decryptValue = %q ok=%v, want %q ok=%v", got, ok, tc.want, tc.wantK)
			}
		})
	}
}

func TestCookieVersion(t *testing.T) {
	for _, tc := range []struct{ in, want string }{
		{"v10rest", "v10"},
		{"v11rest", "v11"},
		{"v20rest", "v20"},
		{"plain", ""},
		{"v9", ""},
	} {
		if got := cookieVersion([]byte(tc.in)); got != tc.want {
			t.Errorf("cookieVersion(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}
