package main

import (
	"errors"
	"strings"
	"testing"
)

// fakeSecretService stands in for org.freedesktop.secrets so the Linux decrypt
// logic is exercised on any OS.
type fakeSecretService struct {
	secret string
	found  bool
	err    error
}

func (f fakeSecretService) Secret(string) (string, bool, error) {
	return f.secret, f.found, f.err
}

func TestLinuxDecrypterBasicStoreValues(t *testing.T) {
	basic, err := cbcBlockFromSecret(basicStorePassword, linuxPBKDF2Iterations)
	if err != nil {
		t.Fatal(err)
	}
	enc := encryptLikeChromium(t, basic, "v10", []byte("sid=basic"))

	// A "v10" cookie decrypts with "peanuts" whether or not a keyring answered.
	for _, sp := range []secretProvider{
		fakeSecretService{},
		fakeSecretService{err: errors.New("no session bus")},
		fakeSecretService{secret: "keyring-secret", found: true},
	} {
		decrypt, err := newLinuxDecrypter(sp, "chrome")
		if err != nil {
			t.Fatal(err)
		}
		value, ok, err := decrypt(enc, "example.com")
		if err != nil || !ok || value != "sid=basic" {
			t.Fatalf("v10 with %+v = %q ok=%v err=%v", sp, value, ok, err)
		}
	}
}

func TestLinuxDecrypterUsesKeyringSecretForV11(t *testing.T) {
	keyring, err := cbcBlockFromSecret("keyring-secret", linuxPBKDF2Iterations)
	if err != nil {
		t.Fatal(err)
	}
	enc := encryptLikeChromium(t, keyring, "v11", []byte("sid=keyring"))

	decrypt, err := newLinuxDecrypter(fakeSecretService{secret: "keyring-secret", found: true}, "chrome")
	if err != nil {
		t.Fatal(err)
	}
	value, ok, err := decrypt(enc, "example.com")
	if err != nil || !ok || value != "sid=keyring" {
		t.Fatalf("v11 = %q ok=%v err=%v", value, ok, err)
	}
}

func TestLinuxDecrypterFailsLoudOnV11WithoutSecret(t *testing.T) {
	enc := append([]byte("v11"), make([]byte, 32)...)
	for _, tc := range []struct {
		name     string
		provider secretProvider
		wantIn   string
	}{
		{"item absent", fakeSecretService{}, "no matching Secret Service item"},
		{"store unreachable", fakeSecretService{err: errors.New("no session bus")}, "no session bus"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			decrypt, err := newLinuxDecrypter(tc.provider, "chrome")
			if err != nil {
				t.Fatal(err)
			}
			value, ok, err := decrypt(enc, "example.com")
			if err == nil {
				t.Fatalf("v11 without a keyring secret must fail loud, got %q ok=%v", value, ok)
			}
			if !strings.Contains(err.Error(), tc.wantIn) {
				t.Fatalf("error %q does not explain why (want %q)", err, tc.wantIn)
			}
		})
	}
}

func TestLinuxDecrypterSkipsPlaintextAndRejectsAppBound(t *testing.T) {
	decrypt, err := newLinuxDecrypter(fakeSecretService{}, "chrome")
	if err != nil {
		t.Fatal(err)
	}
	if _, ok, err := decrypt([]byte("plainvalue"), "x"); ok || err != nil {
		t.Fatalf("untagged value should be skipped, got ok=%v err=%v", ok, err)
	}
	if _, _, err := decrypt(append([]byte("v20"), make([]byte, 32)...), "x"); err == nil {
		t.Fatal("v20 on Linux must fail loud")
	}
}
