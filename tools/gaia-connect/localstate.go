package main

import (
	"crypto/aes"
	"crypto/cipher"
	"encoding/base64"
	"encoding/json"
	"fmt"
)

// On Windows the AES-256-GCM cookie key lives in the user-data dir's "Local
// State" JSON as os_crypt.encrypted_key: base64, prefixed with the 5 ASCII
// bytes "DPAPI", and sealed with the user's DPAPI master key.
const (
	dpapiPrefix   = "DPAPI"
	gcmNonceStart = 3
	gcmNonceEnd   = 15
	gcmKeyLen     = 32
)

// dpapiUnprotect unseals a DPAPI blob. The Windows build passes
// CryptUnprotectData; tests pass a fake so the unwrap is exercised off-Windows.
type dpapiUnprotect func(blob []byte) ([]byte, error)

// masterKeyFromLocalState extracts the AES-256 cookie key from a Local State file.
func masterKeyFromLocalState(localState []byte, unprotect dpapiUnprotect) ([]byte, error) {
	var state struct {
		OSCrypt struct {
			EncryptedKey string `json:"encrypted_key"`
		} `json:"os_crypt"`
	}
	if err := json.Unmarshal(localState, &state); err != nil {
		return nil, fmt.Errorf("parse Local State: %w", err)
	}
	if state.OSCrypt.EncryptedKey == "" {
		return nil, fmt.Errorf("Local State has no os_crypt.encrypted_key")
	}
	blob, err := base64.StdEncoding.DecodeString(state.OSCrypt.EncryptedKey)
	if err != nil {
		return nil, fmt.Errorf("decode os_crypt.encrypted_key: %w", err)
	}
	if len(blob) <= len(dpapiPrefix) || string(blob[:len(dpapiPrefix)]) != dpapiPrefix {
		return nil, fmt.Errorf("os_crypt.encrypted_key is not a DPAPI blob")
	}
	key, err := unprotect(blob[len(dpapiPrefix):])
	if err != nil {
		return nil, fmt.Errorf("unseal the cookie key with DPAPI: %w", err)
	}
	if len(key) != gcmKeyLen {
		return nil, fmt.Errorf("cookie key is %d bytes, want %d", len(key), gcmKeyLen)
	}
	return key, nil
}

// newGCMDecrypter builds the per-row decrypter for a Windows Chromium profile.
// "v10" values are AES-256-GCM with a 12-byte nonce at value[3:15]; "v20" values
// are App-Bound Encrypted and fail loud rather than silently dropping logins.
func newGCMDecrypter(key []byte) (chromiumDecrypter, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("cookie cipher: %w", err)
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("cookie cipher mode: %w", err)
	}
	return func(enc []byte, host string) (string, bool, error) {
		switch cookieVersion(enc) {
		case "v10", "v11":
			if len(enc) <= gcmNonceEnd {
				return "", false, nil
			}
			plain, err := aead.Open(nil, enc[gcmNonceStart:gcmNonceEnd], enc[gcmNonceEnd:], nil)
			if err != nil {
				return "", false, nil // wrong profile key or corrupt row — skip, never corrupt
			}
			return string(stripHostHash(plain, host)), true, nil
		case "v20":
			return "", false, fmt.Errorf(
				"cookies use App-Bound Encryption (v20, Chrome 127+): they can only be unsealed " +
					"from that browser's own elevated context, which gaia-connect does not do")
		}
		return "", false, nil // plaintext or empty — skip rather than corrupt
	}, nil
}
