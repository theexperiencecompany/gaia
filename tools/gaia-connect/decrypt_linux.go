//go:build linux

package main

import (
	"fmt"
	"time"

	"github.com/godbus/dbus/v5"
)

// Chromium stores its Safe Storage password in the freedesktop Secret Service
// under the schema "chrome_libsecret_os_crypt_password_v2" with an
// "application" attribute naming the browser ("chrome", "brave", …). That is a
// schema lookup, not the service/username pair a generic keyring wrapper
// searches, so we speak to org.freedesktop.secrets over D-Bus directly.
const (
	secretServiceName   = "org.freedesktop.secrets"
	secretServicePath   = "/org/freedesktop/secrets"
	secretServiceIface  = "org.freedesktop.Secret.Service"
	secretItemIface     = "org.freedesktop.Secret.Item"
	secretPromptIface   = "org.freedesktop.Secret.Prompt"
	secretAppAttribute  = "application"
	secretPromptTimeout = 60 * time.Second
	noPrompt            = dbus.ObjectPath("/")
)

// extractChromiumCookies reads and decrypts every cookie for a Chromium-family
// browser, asking the desktop keyring for the browser's Safe Storage password.
func extractChromiumCookies(b Browser, p Profile) ([]Cookie, error) {
	if b.SecretApp == "" {
		return nil, fmt.Errorf("%s has no known Linux keyring identity", b.Name)
	}
	decrypt, err := newLinuxDecrypter(dbusSecretService{}, b.SecretApp)
	if err != nil {
		return nil, err
	}
	return decryptCookieRows(p.Dir, decrypt)
}

// dbusSecretService is the real secretProvider, backed by org.freedesktop.secrets.
type dbusSecretService struct{}

func (dbusSecretService) Secret(application string) (string, bool, error) {
	conn, err := dbus.SessionBus()
	if err != nil {
		return "", false, fmt.Errorf("connect to the session bus: %w", err)
	}
	service := conn.Object(secretServiceName, secretServicePath)

	var sessionOutput dbus.Variant
	var session dbus.ObjectPath
	if err := service.Call(secretServiceIface+".OpenSession", 0, "plain", dbus.MakeVariant("")).
		Store(&sessionOutput, &session); err != nil {
		return "", false, fmt.Errorf("open a Secret Service session: %w", err)
	}
	defer conn.Object(secretServiceName, session).Call("org.freedesktop.Secret.Session.Close", 0)

	var unlocked, locked []dbus.ObjectPath
	if err := service.Call(secretServiceIface+".SearchItems", 0,
		map[string]string{secretAppAttribute: application}).Store(&unlocked, &locked); err != nil {
		return "", false, fmt.Errorf("search the keyring for %q: %w", application, err)
	}
	if len(unlocked) == 0 && len(locked) > 0 {
		if unlocked, err = unlockItems(conn, service, locked); err != nil {
			return "", false, err
		}
	}
	if len(unlocked) == 0 {
		return "", false, nil
	}

	var secret struct {
		Session     dbus.ObjectPath
		Parameters  []byte
		Value       []byte
		ContentType string
	}
	if err := conn.Object(secretServiceName, unlocked[0]).
		Call(secretItemIface+".GetSecret", 0, session).Store(&secret); err != nil {
		return "", false, fmt.Errorf("read the %q keyring item: %w", application, err)
	}
	return string(secret.Value), true, nil
}

// unlockItems unlocks keyring items, following the prompt the service may hand
// back (the desktop asks the user for their login password).
func unlockItems(conn *dbus.Conn, service dbus.BusObject, locked []dbus.ObjectPath) ([]dbus.ObjectPath, error) {
	var unlocked []dbus.ObjectPath
	var prompt dbus.ObjectPath
	if err := service.Call(secretServiceIface+".Unlock", 0, locked).Store(&unlocked, &prompt); err != nil {
		return nil, fmt.Errorf("unlock the keyring: %w", err)
	}
	if prompt == noPrompt {
		return unlocked, nil
	}

	signals := make(chan *dbus.Signal, 1)
	conn.Signal(signals)
	defer conn.RemoveSignal(signals)
	if err := conn.AddMatchSignal(
		dbus.WithMatchObjectPath(prompt),
		dbus.WithMatchInterface(secretPromptIface),
		dbus.WithMatchMember("Completed"),
	); err != nil {
		return nil, fmt.Errorf("watch the keyring unlock prompt: %w", err)
	}
	if call := conn.Object(secretServiceName, prompt).Call(secretPromptIface+".Prompt", 0, ""); call.Err != nil {
		return nil, fmt.Errorf("show the keyring unlock prompt: %w", call.Err)
	}

	for {
		select {
		case sig := <-signals:
			if sig.Path != prompt || len(sig.Body) != 2 {
				continue
			}
			dismissed, _ := sig.Body[0].(bool)
			if dismissed {
				return nil, fmt.Errorf("keyring unlock was dismissed")
			}
			result, _ := sig.Body[1].(dbus.Variant)
			paths, _ := result.Value().([]dbus.ObjectPath)
			return paths, nil
		case <-time.After(secretPromptTimeout):
			return nil, fmt.Errorf("timed out waiting for the keyring unlock prompt")
		}
	}
}
