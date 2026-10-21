package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/pbkdf2"
	"crypto/sha1"
	"crypto/sha256"
	"fmt"
)

// Chromium's "v10"/"v11" cookie encryption is fixed and public, and identical on
// macOS and Linux apart from the PBKDF2 iteration count and where the password
// comes from:
//
//	key   = PBKDF2-HMAC-SHA1(secret, "saltysalt", iterations, 16)
//	value = AES-128-CBC(key, IV = 16 spaces) of encrypted_value[3:]
//
// macOS reads the secret from the Keychain and iterates 1003 times; Linux reads
// it from the Secret Service (or uses the literal "peanuts" for its basic store)
// and iterates once.
var (
	cookieSalt = []byte("saltysalt")
	cookieIV   = bytes.Repeat([]byte{' '}, 16)
)

const (
	macPBKDF2Iterations   = 1003
	linuxPBKDF2Iterations = 1
	cookieKeyLen          = 16
)

// cookieVersion returns the leading version tag of an encrypted value ("v10",
// "v11", "v20"), or "" when the value carries no tag (a plaintext cookie).
func cookieVersion(enc []byte) string {
	if len(enc) < 3 {
		return ""
	}
	switch tag := string(enc[:3]); tag {
	case "v10", "v11", "v20":
		return tag
	}
	return ""
}

// cookieKey derives the AES-128 key for a Safe Storage password.
func cookieKey(secret string, iterations int) ([]byte, error) {
	key, err := pbkdf2.Key(sha1.New, secret, cookieSalt, iterations, cookieKeyLen)
	if err != nil {
		return nil, fmt.Errorf("derive cookie key: %w", err)
	}
	return key, nil
}

// cbcBlockFromSecret derives the AES-128-CBC block for a Safe Storage password.
func cbcBlockFromSecret(secret string, iterations int) (cipher.Block, error) {
	key, err := cookieKey(secret, iterations)
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("cookie cipher: %w", err)
	}
	return block, nil
}

// decryptValue decrypts a whole tagged "v10"/"v11" CBC value.
func decryptValue(block cipher.Block, enc []byte, host string) (string, bool) {
	switch cookieVersion(enc) {
	case "v10", "v11":
		return decryptCBCBody(block, enc[3:], host)
	}
	return "", false
}

// decryptCBCBody decrypts an encrypted value with its version tag already stripped.
func decryptCBCBody(block cipher.Block, body []byte, host string) (string, bool) {
	if len(body) == 0 || len(body)%aes.BlockSize != 0 {
		return "", false
	}
	plain := make([]byte, len(body))
	cipher.NewCBCDecrypter(block, cookieIV).CryptBlocks(plain, body)

	plain, ok := stripPKCS7(plain)
	if !ok {
		return "", false
	}
	return string(stripHostHash(plain, host)), true
}

// stripHostHash removes the SHA256(host_key) integrity prefix recent Chrome
// prepends to a cookie's plaintext. It is stripped only when the prefix actually
// IS that hash — a value that merely happens to be >=32 bytes must be left whole.
func stripHostHash(plain []byte, host string) []byte {
	if len(plain) < sha256.Size {
		return plain
	}
	want := sha256.Sum256([]byte(host))
	if !bytes.Equal(plain[:sha256.Size], want[:]) {
		return plain
	}
	return plain[sha256.Size:]
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

// chromiumDecrypter turns one row's encrypted value into plaintext. ok=false
// means "skip this row" (plaintext, empty, or not a value we can read); a
// non-nil error is fatal and aborts the whole extraction — never a silent skip.
type chromiumDecrypter func(enc []byte, host string) (value string, ok bool, err error)

// decryptCookieRows reads a Chromium profile's cookie DB and decrypts every row.
func decryptCookieRows(profileDir string, decrypt chromiumDecrypter) ([]Cookie, error) {
	rows, err := readCookieRows(profileDir)
	if err != nil {
		return nil, err
	}
	out := make([]Cookie, 0, len(rows))
	for _, r := range rows {
		value, ok, err := decrypt(r.encrypted, r.host)
		if err != nil {
			return nil, err
		}
		if !ok {
			continue
		}
		out = append(out, r.toCookie(value))
	}
	return out, nil
}
