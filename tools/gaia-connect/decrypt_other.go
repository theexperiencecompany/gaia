//go:build !darwin

package main

import (
	"fmt"
	"runtime"
)

// ExtractCookies is macOS-only for now. Linux (Secret Service) and Windows
// (DPAPI/App-Bound Encryption) decrypt differently and are not implemented yet;
// the binary still builds and runs everywhere so those can be added in place.
func ExtractCookies(_ Browser) ([]Cookie, error) {
	return nil, fmt.Errorf("cookie extraction is not implemented on %s yet (macOS only for now)", runtime.GOOS)
}
