//go:build windows

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"unsafe"

	"golang.org/x/sys/windows"
)

// UNVERIFIED: this path is written from Chromium's documented os_crypt format
// but has never been run on a Windows machine. The DPAPI call and the Local
// State layout are covered by tests through the dpapiUnprotect interface; the
// end-to-end read of a real profile is not.

// extractChromiumCookies reads and decrypts every cookie for a Chromium-family
// browser, unsealing the profile's AES-256-GCM key with DPAPI.
func extractChromiumCookies(b Browser, p Profile) ([]Cookie, error) {
	localState, err := os.ReadFile(filepath.Join(b.UserDataDir, "Local State"))
	if err != nil {
		return nil, fmt.Errorf("read %s Local State: %w", b.Name, err)
	}
	key, err := masterKeyFromLocalState(localState, cryptUnprotectData)
	if err != nil {
		return nil, err
	}
	decrypt, err := newGCMDecrypter(key)
	if err != nil {
		return nil, err
	}
	return decryptCookieRows(p.Dir, decrypt)
}

// cryptUnprotectData unseals a DPAPI blob for the current user.
func cryptUnprotectData(blob []byte) ([]byte, error) {
	if len(blob) == 0 {
		return nil, fmt.Errorf("empty DPAPI blob")
	}
	in := windows.DataBlob{Size: uint32(len(blob)), Data: &blob[0]}
	var out windows.DataBlob
	if err := windows.CryptUnprotectData(&in, nil, nil, 0, nil, 0, &out); err != nil {
		return nil, err
	}
	defer windows.LocalFree(windows.Handle(unsafe.Pointer(out.Data)))
	return append([]byte(nil), unsafe.Slice(out.Data, out.Size)...), nil
}
