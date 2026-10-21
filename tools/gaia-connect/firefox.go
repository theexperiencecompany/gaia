package main

import (
	"bufio"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// firefoxProfiles lists a Firefox root's profiles from profiles.ini, which is
// the source of truth: a headless first run creates a directory like
// "<hash>.default-esr", so no name pattern can be relied on. The [Install…]
// section names the profile Firefox actually launches, which we list first so
// it is the one picked when the user does not choose. Profiles that have never
// stored a cookie are skipped, exactly as for Chromium.
func firefoxProfiles(root string) []Profile {
	sections, err := parseINI(filepath.Join(root, "profiles.ini"))
	if err != nil {
		return firefoxProfilesByScan(root)
	}

	var defaultPath string
	for name, keys := range sections {
		if strings.HasPrefix(name, "Install") && keys["Default"] != "" {
			defaultPath = keys["Default"]
		}
	}

	var def, rest []Profile
	for _, name := range sortedSectionNames(sections) {
		keys := sections[name]
		if !strings.HasPrefix(name, "Profile") || keys["Path"] == "" {
			continue
		}
		dir := filepath.FromSlash(keys["Path"])
		if keys["IsRelative"] != "0" {
			dir = filepath.Join(root, dir)
		}
		if _, err := os.Stat(filepath.Join(dir, firefoxCookieDB)); err != nil {
			continue
		}
		p := Profile{Dir: dir, Name: profileLabel(keys["Name"], filepath.Base(dir))}
		if keys["Path"] == defaultPath || keys["Default"] == "1" {
			def = append(def, p)
			continue
		}
		rest = append(rest, p)
	}
	return append(def, rest...)
}

// firefoxProfilesByScan is the fallback for a root with no profiles.ini (a
// hand-copied or Flatpak-relocated profile directory).
func firefoxProfilesByScan(root string) []Profile {
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil
	}
	var out []Profile
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		dir := filepath.Join(root, e.Name())
		if _, err := os.Stat(filepath.Join(dir, firefoxCookieDB)); err != nil {
			continue
		}
		out = append(out, Profile{Dir: dir, Name: e.Name()})
	}
	return out
}

func profileLabel(name, fallback string) string {
	if name == "" {
		return fallback
	}
	return name
}

// parseINI reads a Mozilla profiles.ini into section → key → value.
func parseINI(path string) (map[string]map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	sections := map[string]map[string]string{}
	section := ""
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		switch {
		case line == "" || strings.HasPrefix(line, ";") || strings.HasPrefix(line, "#"):
		case strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]"):
			section = line[1 : len(line)-1]
			sections[section] = map[string]string{}
		case section != "":
			if key, value, ok := strings.Cut(line, "="); ok {
				sections[section][strings.TrimSpace(key)] = strings.TrimSpace(value)
			}
		}
	}
	return sections, scanner.Err()
}

// sortedSectionNames keeps profile order stable across runs (map iteration is not).
func sortedSectionNames(sections map[string]map[string]string) []string {
	out := make([]string, 0, len(sections))
	for name := range sections {
		out = append(out, name)
	}
	sort.Strings(out)
	return out
}

// Firefox keeps its cookies in cookies.sqlite in plain text — there is no
// keychain, no keyring and no DPAPI step, only the same copy-the-locked-db dance
// Chromium needs. Its timestamps are already unix seconds, so the only mapping
// work is naming.
func extractFirefoxCookies(p Profile) ([]Cookie, error) {
	db, cleanup, err := openCookieDB(filepath.Join(p.Dir, firefoxCookieDB))
	if err != nil {
		return nil, err
	}
	defer cleanup()

	rows, err := db.Query(`SELECT host, name, value, path,
		expiry, isSecure, isHttpOnly, sameSite FROM moz_cookies`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []Cookie
	for rows.Next() {
		var c Cookie
		var expiry, sameSite int64
		if err := rows.Scan(&c.Domain, &c.Name, &c.Value, &c.Path,
			&expiry, &c.Secure, &c.HTTPOnly, &sameSite); err != nil {
			return nil, err
		}
		c.Expires = firefoxExpires(expiry)
		c.Path = cookiePath(c.Path)
		c.SameSite = sameSiteLabel(sameSite)
		out = append(out, c)
	}
	return out, rows.Err()
}

// firefoxExpires maps moz_cookies.expiry (unix seconds, 0 for a session cookie)
// onto Playwright's convention of -1 for "expires with the session".
func firefoxExpires(expiry int64) float64 {
	if expiry <= 0 {
		return -1
	}
	return float64(expiry)
}
