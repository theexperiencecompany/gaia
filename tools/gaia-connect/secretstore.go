package main

import (
	"crypto/cipher"
	"fmt"
)

// Chromium on Linux keeps its "<Browser> Safe Storage" password in the
// freedesktop Secret Service. When no keyring is available it falls back to its
// basic store, whose password is this public literal.
const basicStorePassword = "peanuts"

// secretProvider looks up a Safe Storage password by the Secret Service
// "application" attribute Chromium stores it under. The D-Bus client is the
// only real implementation; tests use a fake.
type secretProvider interface {
	// Secret reports the password, whether an item was found at all, and any
	// error reaching the store. An unreachable store is not fatal on its own:
	// Chromium then used its basic store, so "v10" cookies still decrypt.
	Secret(application string) (secret string, found bool, err error)
}

// newLinuxDecrypter builds the per-row decrypter for a Linux Chromium profile.
// "v10" values always use the basic-store password; "v11" values need the
// keyring secret, and fail loud when it cannot be read rather than yielding
// empty cookies that would look like a successful but logged-out sync.
func newLinuxDecrypter(sp secretProvider, application string) (chromiumDecrypter, error) {
	basic, err := cbcBlockFromSecret(basicStorePassword, linuxPBKDF2Iterations)
	if err != nil {
		return nil, err
	}

	secret, found, lookupErr := sp.Secret(application)
	var keyring cipher.Block
	if found {
		if keyring, err = cbcBlockFromSecret(secret, linuxPBKDF2Iterations); err != nil {
			return nil, err
		}
	}

	return func(enc []byte, host string) (string, bool, error) {
		switch cookieVersion(enc) {
		case "v10":
			value, ok := decryptCBCBody(basic, enc[3:], host)
			return value, ok, nil
		case "v11":
			if keyring == nil {
				return "", false, fmt.Errorf(
					"cookies are encrypted with the %q Safe Storage password from your keyring, "+
						"which could not be read (%s) — unlock your login keyring (GNOME Keyring / KWallet) and retry",
					application, secretLookupReason(lookupErr))
			}
			value, ok := decryptCBCBody(keyring, enc[3:], host)
			return value, ok, nil
		case "v20":
			return "", false, fmt.Errorf("cookie uses App-Bound Encryption (v20), which is not supported on Linux")
		}
		return "", false, nil // plaintext or empty — skip rather than corrupt
	}, nil
}

func secretLookupReason(err error) string {
	if err != nil {
		return err.Error()
	}
	return "no matching Secret Service item"
}
