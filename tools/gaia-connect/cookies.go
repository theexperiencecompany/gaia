package main

import (
	"database/sql"
	"fmt"
	"io"
	"os"
	"path/filepath"

	_ "modernc.org/sqlite"
)

// Cookie is one entry in a Playwright storage_state. JSON tags match Playwright's
// camelCase exactly, so the upload is the shape GAIA's browser host seeds.
type Cookie struct {
	Name     string  `json:"name"`
	Value    string  `json:"value"`
	Domain   string  `json:"domain"`
	Path     string  `json:"path"`
	Expires  float64 `json:"expires"`
	Secure   bool    `json:"secure"`
	HTTPOnly bool    `json:"httpOnly"`
	SameSite string  `json:"sameSite"`
}

// chromeEpochOffsetMicros converts Chrome's 1601-based microsecond timestamps to unix seconds.
const chromeEpochOffsetMicros = 11644473600_000_000

var sameSiteName = map[int64]string{0: "None", 1: "Lax", 2: "Strict", -1: "Lax"}

// rawCookie is one DB row before its value is decrypted (per-OS).
type rawCookie struct {
	host, name, path string
	encrypted        []byte
	expires          int64
	secure, httpOnly bool
	sameSite         int64
}

// ExtractCookies reads every cookie from one profile, decrypting them when the
// browser's family stores them encrypted.
func ExtractCookies(b Browser, p Profile) ([]Cookie, error) {
	if b.Family == familyFirefox {
		return extractFirefoxCookies(p)
	}
	return extractChromiumCookies(b, p)
}

// walSuffixes are SQLite's write-ahead-log sidecars. Firefox runs cookies.sqlite
// in WAL mode, so the newest cookies live in the -wal file until a checkpoint:
// copying the main database alone silently loses this session's logins.
var walSuffixes = []string{"-wal", "-shm"}

// openCookieDB copies a (locked) cookie database — with its WAL sidecars — to a
// temp file and opens it. The copy is required because the browser holds a write
// lock on the live file; the copy is opened read-write so SQLite can replay the
// WAL into it. The returned cleanup closes the DB and removes the copies.
func openCookieDB(src string) (*sql.DB, func(), error) {
	tmp, err := os.CreateTemp("", "gaia-cookies-*")
	if err != nil {
		return nil, nil, err
	}
	remove := func() {
		os.Remove(tmp.Name())
		for _, s := range walSuffixes {
			os.Remove(tmp.Name() + s)
		}
	}
	if err := copyFile(src, tmp.Name()); err != nil {
		remove()
		return nil, nil, fmt.Errorf("copy cookie db: %w", err)
	}
	for _, s := range walSuffixes {
		if _, err := os.Stat(src + s); err != nil {
			continue // no WAL sidecar: the database is already self-contained
		}
		if err := copyFile(src+s, tmp.Name()+s); err != nil {
			remove()
			return nil, nil, fmt.Errorf("copy cookie db %s: %w", s, err)
		}
	}
	db, err := sql.Open("sqlite", "file:"+tmp.Name())
	if err != nil {
		remove()
		return nil, nil, err
	}
	return db, func() {
		db.Close()
		remove()
	}, nil
}

// readCookieRows returns every row of a Chromium profile's Cookies DB.
func readCookieRows(profileDir string) ([]rawCookie, error) {
	db, cleanup, err := openCookieDB(filepath.Join(profileDir, "Cookies"))
	if err != nil {
		return nil, err
	}
	defer cleanup()

	rows, err := db.Query(`SELECT host_key, name, encrypted_value, path,
		expires_utc, is_secure, is_httponly, samesite FROM cookies`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []rawCookie
	for rows.Next() {
		var r rawCookie
		if err := rows.Scan(&r.host, &r.name, &r.encrypted, &r.path,
			&r.expires, &r.secure, &r.httpOnly, &r.sameSite); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (r rawCookie) toCookie(value string) Cookie {
	expires := float64(-1)
	if r.expires > 0 {
		expires = float64(r.expires-chromeEpochOffsetMicros) / 1_000_000
	}
	return Cookie{
		Name: r.name, Value: value, Domain: r.host, Path: cookiePath(r.path),
		Expires: expires, Secure: r.secure, HTTPOnly: r.httpOnly,
		SameSite: sameSiteLabel(r.sameSite),
	}
}

// sameSiteLabel maps a stored SameSite enum to Playwright's spelling. Chromium
// and Firefox agree on 0/1/2; Chromium additionally uses -1 for "unspecified".
func sameSiteLabel(v int64) string {
	if name, ok := sameSiteName[v]; ok {
		return name
	}
	return "Lax"
}

func cookiePath(p string) string {
	if p == "" {
		return "/"
	}
	return p
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
