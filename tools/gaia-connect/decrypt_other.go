//go:build !darwin && !linux && !windows

package main

import (
	"fmt"
	"runtime"
)

// Chromium's cookie encryption is OS-specific (Keychain, Secret Service, DPAPI)
// and the three supported systems each have their own file. This stub keeps the
// binary buildable on any other GOOS — where Firefox, whose cookies are
// plaintext, still works.
func extractChromiumCookies(b Browser, _ Profile) ([]Cookie, error) {
	return nil, fmt.Errorf("decrypting %s cookies is not supported on %s", b.Name, runtime.GOOS)
}
