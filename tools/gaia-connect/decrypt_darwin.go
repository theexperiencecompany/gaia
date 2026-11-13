//go:build darwin

package main

import (
	"fmt"
	"os/exec"
	"strings"
)

// extractChromiumCookies reads and decrypts every cookie for a Chromium-family
// browser. The Keychain read prompts the user once — that prompt is the consent
// for this sync.
func extractChromiumCookies(b Browser, p Profile) ([]Cookie, error) {
	secret, err := keychainSecret(b.KeychainService, b.KeychainAccount)
	if err != nil {
		return nil, err
	}
	block, err := cbcBlockFromSecret(secret, macPBKDF2Iterations)
	if err != nil {
		return nil, err
	}
	return decryptCookieRows(p.Dir, func(enc []byte, host string) (string, bool, error) {
		value, ok := decryptValue(block, enc, host)
		return value, ok, nil // plaintext, empty, or undecryptable — skip rather than corrupt
	})
}

func keychainSecret(service, account string) (string, error) {
	cmd := exec.Command("security", "find-generic-password", "-w", "-s", service, "-a", account)
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("read %q from Keychain (declined or not installed): %w", service, err)
	}
	return strings.TrimSpace(string(out)), nil
}
