//go:build darwin

package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/pbkdf2"
	"crypto/sha1"
	"crypto/sha256"
	"fmt"
	"os/exec"
	"strings"
)

// macOS Chromium cookie encryption is fixed and public:
//
//	key = PBKDF2-HMAC-SHA1(keychainSecret, "saltysalt", 1003, 16)
//	value = AES-128-CBC(key, IV = 16 spaces) of encrypted_value[3:] (after the "v10" tag)
var (
	cookieSalt = []byte("saltysalt")
	cookieIV   = bytes.Repeat([]byte{' '}, 16)
)

const pbkdf2Iterations = 1003

// ExtractCookies reads and decrypts every cookie for a browser. The Keychain
// read prompts the user once — that prompt is the consent for this sync.
func ExtractCookies(b Browser) ([]Cookie, error) {
	secret, err := keychainSecret(b.KeychainService, b.KeychainAccount)
	if err != nil {
		return nil, err
	}
	key, err := pbkdf2.Key(sha1.New, secret, cookieSalt, pbkdf2Iterations, 16)
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}

	rows, err := readCookieRows(b.UserDataDir)
	if err != nil {
		return nil, err
	}
	var out []Cookie
	for _, r := range rows {
		value, ok := decryptValue(block, r.encrypted, r.host)
		if !ok {
			continue // plaintext, empty, or undecryptable — skip rather than corrupt
		}
		out = append(out, r.toCookie(value))
	}
	return out, nil
}

func keychainSecret(service, account string) (string, error) {
	cmd := exec.Command("security", "find-generic-password", "-w", "-s", service, "-a", account)
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("read %q from Keychain (declined or not installed): %w", service, err)
	}
	return strings.TrimSpace(string(out)), nil
}

func decryptValue(block cipher.Block, enc []byte, host string) (string, bool) {
	if len(enc) < 3 || (string(enc[:3]) != "v10" && string(enc[:3]) != "v11") {
		return "", false
	}
	body := enc[3:]
	if len(body) == 0 || len(body)%aes.BlockSize != 0 {
		return "", false
	}
	plain := make([]byte, len(body))
	cipher.NewCBCDecrypter(block, cookieIV).CryptBlocks(plain, body)

	plain, ok := stripPKCS7(plain)
	if !ok {
		return "", false
	}
	// Recent Chrome prepends SHA256(host_key) to the plaintext as an integrity
	// binding. Strip it only when the prefix actually IS that hash — a value that
	// merely happens to be >=32 bytes must be left whole.
	if len(plain) >= 32 {
		want := sha256.Sum256([]byte(host))
		if bytes.Equal(plain[:32], want[:]) {
			plain = plain[32:]
		}
	}
	return string(plain), true
}

func stripPKCS7(b []byte) ([]byte, bool) {
	if len(b) == 0 {
		return nil, false
	}
	pad := int(b[len(b)-1])
	if pad == 0 || pad > aes.BlockSize || pad > len(b) {
		return b, true // not padded the way we expect — keep as-is
	}
	return b[:len(b)-pad], true
}
