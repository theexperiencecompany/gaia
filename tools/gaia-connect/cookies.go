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

// readCookieRows copies the (locked) Cookies DB and returns every row. The copy
// is required because the browser holds a write lock on the live file.
func readCookieRows(profileDir string) ([]rawCookie, error) {
	src := filepath.Join(profileDir, "Cookies")
	tmp, err := os.CreateTemp("", "gaia-cookies-*")
	if err != nil {
		return nil, err
	}
	defer os.Remove(tmp.Name())
	if err := copyFile(src, tmp.Name()); err != nil {
		return nil, fmt.Errorf("copy cookie db: %w", err)
	}

	db, err := sql.Open("sqlite", "file:"+tmp.Name()+"?mode=ro")
	if err != nil {
		return nil, err
	}
	defer db.Close()

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
	path := r.path
	if path == "" {
		path = "/"
	}
	ss, ok := sameSiteName[r.sameSite]
	if !ok {
		ss = "Lax"
	}
	return Cookie{
		Name: r.name, Value: value, Domain: r.host, Path: path,
		Expires: expires, Secure: r.secure, HTTPOnly: r.httpOnly, SameSite: ss,
	}
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
