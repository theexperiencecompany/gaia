package main

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

// writeFirefoxProfile builds a real cookies.sqlite with the columns Firefox uses.
func writeFirefoxProfile(t *testing.T, dir string, rows [][]any) {
	t.Helper()
	db, err := sql.Open("sqlite", filepath.Join(dir, "cookies.sqlite"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(`CREATE TABLE moz_cookies (
		id INTEGER PRIMARY KEY, host TEXT, name TEXT, value TEXT, path TEXT,
		expiry INTEGER, isSecure INTEGER, isHttpOnly INTEGER, sameSite INTEGER)`); err != nil {
		t.Fatal(err)
	}
	for _, r := range rows {
		if _, err := db.Exec(`INSERT INTO moz_cookies
			(host, name, value, path, expiry, isSecure, isHttpOnly, sameSite)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, r...); err != nil {
			t.Fatal(err)
		}
	}
}

func TestExtractFirefoxCookiesMapsRows(t *testing.T) {
	dir := t.TempDir()
	writeFirefoxProfile(t, dir, [][]any{
		{".github.com", "sid", "abc123", "/", 1893456000, 1, 1, 2},
		{"accounts.google.com", "session", "xyz", "", 0, 0, 0, 0}, // session cookie, empty path
	})

	cookies, err := extractFirefoxCookies(Profile{Dir: dir, Name: "default-release"})
	if err != nil {
		t.Fatal(err)
	}
	if len(cookies) != 2 {
		t.Fatalf("expected 2 cookies, got %+v", cookies)
	}

	want := Cookie{
		Name: "sid", Value: "abc123", Domain: ".github.com", Path: "/",
		Expires: 1893456000, Secure: true, HTTPOnly: true, SameSite: "Strict",
	}
	if cookies[0] != want {
		t.Errorf("cookie[0] = %+v, want %+v", cookies[0], want)
	}

	want = Cookie{
		Name: "session", Value: "xyz", Domain: "accounts.google.com", Path: "/",
		Expires: -1, Secure: false, HTTPOnly: false, SameSite: "None",
	}
	if cookies[1] != want {
		t.Errorf("cookie[1] = %+v, want %+v", cookies[1], want)
	}
}

func TestExtractCookiesRoutesFirefoxWithoutDecryption(t *testing.T) {
	dir := t.TempDir()
	writeFirefoxProfile(t, dir, [][]any{{"x.com", "sid", "plain", "/", 1893456000, 1, 0, 1}})

	b := Browser{Name: "Firefox", Family: familyFirefox, UserDataDir: filepath.Dir(dir)}
	cookies, err := ExtractCookies(b, Profile{Dir: dir})
	if err != nil {
		t.Fatal(err)
	}
	if len(cookies) != 1 || cookies[0].Value != "plain" {
		t.Fatalf("ExtractCookies via the firefox family = %+v", cookies)
	}
}

// Firefox runs cookies.sqlite in WAL mode, so the newest cookies sit in the
// -wal sidecar until a checkpoint. Copying the main file alone would silently
// drop exactly the login the user just made.
func TestExtractFirefoxCookiesReadsUncheckpointedWALRows(t *testing.T) {
	dir := t.TempDir()
	db, err := sql.Open("sqlite", filepath.Join(dir, "cookies.sqlite"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	for _, stmt := range []string{
		`PRAGMA journal_mode=WAL`,
		`CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, host TEXT, name TEXT,
			value TEXT, path TEXT, expiry INTEGER, isSecure INTEGER,
			isHttpOnly INTEGER, sameSite INTEGER)`,
		`INSERT INTO moz_cookies (host, name, value, path, expiry, isSecure, isHttpOnly, sameSite)
			VALUES ('probe.test', 'gaia_probe', 'hello-wal', '/', 1893456000, 0, 0, 1)`,
	} {
		if _, err := db.Exec(stmt); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "cookies.sqlite-wal")); err != nil {
		t.Skipf("this SQLite build did not produce a -wal sidecar: %v", err)
	}

	cookies, err := extractFirefoxCookies(Profile{Dir: dir})
	if err != nil {
		t.Fatal(err)
	}
	if len(cookies) != 1 || cookies[0].Value != "hello-wal" {
		t.Fatalf("uncheckpointed WAL row was lost: %+v", cookies)
	}
}

func TestFirefoxProfilesComeFromProfilesINIDefaultFirst(t *testing.T) {
	root := t.TempDir()
	for _, dir := range []string{"abc123.default-esr", "xyz789.dev", "never-launched"} {
		if err := os.MkdirAll(filepath.Join(root, dir), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	// "never-launched" has no cookies.sqlite and must be skipped.
	writeFirefoxProfile(t, filepath.Join(root, "abc123.default-esr"), nil)
	writeFirefoxProfile(t, filepath.Join(root, "xyz789.dev"), nil)
	ini := "[Profile0]\nName=dev\nIsRelative=1\nPath=xyz789.dev\n\n" +
		"[Profile1]\nName=default-esr\nIsRelative=1\nPath=abc123.default-esr\n\n" +
		"[Profile2]\nName=fresh\nIsRelative=1\nPath=never-launched\n\n" +
		"[Install4F96D1932A9F858E]\nDefault=abc123.default-esr\nLocked=1\n"
	if err := os.WriteFile(filepath.Join(root, "profiles.ini"), []byte(ini), 0o644); err != nil {
		t.Fatal(err)
	}

	profiles := ListProfiles(Browser{Family: familyFirefox, UserDataDir: root})
	if len(profiles) != 2 {
		t.Fatalf("expected the 2 profiles with cookies, got %+v", profiles)
	}
	// The [Install…] default is listed first so it is what an unattended run picks.
	if profiles[0].Name != "default-esr" || filepath.Base(profiles[0].Dir) != "abc123.default-esr" {
		t.Fatalf("expected the install default first, got %+v", profiles)
	}
	if profiles[1].Name != "dev" {
		t.Fatalf("expected the dev profile second, got %+v", profiles)
	}
}

func TestFirefoxProfilesHonourAbsolutePaths(t *testing.T) {
	root, elsewhere := t.TempDir(), t.TempDir()
	writeFirefoxProfile(t, elsewhere, nil)
	ini := "[Profile0]\nName=moved\nIsRelative=0\nPath=" + elsewhere + "\n"
	if err := os.WriteFile(filepath.Join(root, "profiles.ini"), []byte(ini), 0o644); err != nil {
		t.Fatal(err)
	}

	profiles := ListProfiles(Browser{Family: familyFirefox, UserDataDir: root})
	if len(profiles) != 1 || profiles[0].Dir != elsewhere {
		t.Fatalf("IsRelative=0 path not honoured: %+v", profiles)
	}
}

func TestListProfilesFindsFirefoxProfilesByCookiesSqlite(t *testing.T) {
	root := t.TempDir()
	profile := filepath.Join(root, "abcd1234.default-release")
	if err := os.MkdirAll(profile, 0o755); err != nil {
		t.Fatal(err)
	}
	writeFirefoxProfile(t, profile, nil)

	b := Browser{Name: "Firefox", Family: familyFirefox, UserDataDir: root}
	profiles := ListProfiles(b)
	if len(profiles) != 1 || profiles[0].Name != "abcd1234.default-release" {
		t.Fatalf("expected the Firefox profile dir, got %+v", profiles)
	}
	// The Chromium marker file must not make a Firefox profile appear.
	if got := ListProfiles(Browser{Family: familyChromium, UserDataDir: root}); len(got) != 0 {
		t.Fatalf("cookies.sqlite must not register as a Chromium profile: %+v", got)
	}
}
