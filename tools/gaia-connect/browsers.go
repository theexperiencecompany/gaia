package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
)

// browserFamily is how a browser stores its cookies — the two families differ in
// database schema and in whether the values are encrypted at all, so every
// per-browser decision hangs off this rather than off the browser's name.
type browserFamily string

const (
	familyChromium browserFamily = "chromium"
	familyFirefox  browserFamily = "firefox"
)

// Browser is one installed browser we can read a profile from.
type Browser struct {
	Name            string        // display name
	Family          browserFamily // how its cookies are stored
	UserDataDir     string        // root holding the profile directories
	KeychainService string        // macOS Keychain generic-password service ("<Name> Safe Storage")
	KeychainAccount string        // macOS Keychain account (usually the browser name)
	SecretApp       string        // Linux Secret Service "application" attribute
}

// candidate is a browser we know how to locate, before checking it exists on
// disk. Each OS field lists every place that browser's profile root can live;
// the first one that actually holds profiles wins.
type candidate struct {
	name       string
	family     browserFamily
	secretApp  string   // Linux Secret Service "application" attribute
	mac        []string // under ~/Library/Application Support
	linux      []string // under $HOME
	winLocal   []string // under %LOCALAPPDATA%
	winRoaming []string // under %APPDATA%
}

var candidates = []candidate{
	{
		// Arc ships no Linux build, so it needs no Secret Service attribute.
		name: "Arc", family: familyChromium,
		mac:      []string{"Arc/User Data"},
		winLocal: []string{"Arc/User Data"},
	},
	{
		name: "Chrome", family: familyChromium, secretApp: "chrome",
		mac:      []string{"Google/Chrome"},
		linux:    []string{".config/google-chrome"},
		winLocal: []string{"Google/Chrome/User Data"},
	},
	{
		name: "Chromium", family: familyChromium, secretApp: "chromium",
		mac:      []string{"Chromium"},
		linux:    []string{".config/chromium"},
		winLocal: []string{"Chromium/User Data"},
	},
	{
		// Helium is a Chromium fork; its Secret Service "application" attribute is
		// the lowercased product name, which we assume is "helium" (UNVERIFIED —
		// no Helium Linux build was available to check).
		name: "Helium", family: familyChromium, secretApp: "helium",
		mac:      []string{"net.imput.helium"},
		linux:    []string{".config/helium", ".config/net.imput.helium"},
		winLocal: []string{"Helium/User Data"},
	},
	{
		name: "Brave", family: familyChromium, secretApp: "brave",
		mac:      []string{"BraveSoftware/Brave-Browser"},
		linux:    []string{".config/BraveSoftware/Brave-Browser"},
		winLocal: []string{"BraveSoftware/Brave-Browser/User Data"},
	},
	{
		name: "Edge", family: familyChromium, secretApp: "microsoft-edge",
		mac:      []string{"Microsoft Edge"},
		linux:    []string{".config/microsoft-edge"},
		winLocal: []string{"Microsoft/Edge/User Data"},
	},
	{
		// Firefox cookies are plaintext, so it needs no keyring secret anywhere.
		name: "Firefox", family: familyFirefox,
		mac: []string{"Firefox/Profiles"},
		linux: []string{
			".mozilla/firefox",
			"snap/firefox/common/.mozilla/firefox",
			".var/app/org.mozilla.firefox/.mozilla/firefox",
		},
		winRoaming: []string{"Mozilla/Firefox/Profiles"},
	},
}

// The file that marks a directory as a usable profile of each family.
const (
	chromiumCookieDB = "Cookies"
	firefoxCookieDB  = "cookies.sqlite"
)

// DetectBrowsers returns every candidate whose profile actually exists on disk.
func DetectBrowsers() []Browser {
	home, _ := os.UserHomeDir()
	var out []Browser
	for _, c := range candidates {
		for _, dir := range userDataDirs(home, c) {
			b := Browser{
				Name:            c.name,
				Family:          c.family,
				UserDataDir:     dir,
				KeychainService: c.name + " Safe Storage",
				KeychainAccount: c.name,
				SecretApp:       c.secretApp,
			}
			if len(ListProfiles(b)) == 0 {
				continue
			}
			out = append(out, b)
			break // first location that holds profiles wins
		}
	}
	return out
}

// Profile is one browser profile under a user-data dir (Chrome's "Default",
// "Profile 1", Firefox's "abcd1234.default-release", …). Dir is the absolute
// path to that profile's directory; Name is its display name from Preferences,
// falling back to the directory name.
type Profile struct {
	Dir  string `json:"dir"`
	Name string `json:"name"`
}

// ListProfiles returns every profile under a browser's user-data dir that has a
// cookie database, each with its display name. os.ReadDir sorts by filename,
// so "Default" comes first and the order is stable for pickers and robots.
func ListProfiles(b Browser) []Profile {
	if b.Family == familyFirefox {
		return firefoxProfiles(b.UserDataDir)
	}
	entries, err := os.ReadDir(b.UserDataDir)
	if err != nil {
		return nil
	}
	var out []Profile
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		dir := filepath.Join(b.UserDataDir, e.Name())
		if _, err := os.Stat(filepath.Join(dir, chromiumCookieDB)); err != nil {
			continue
		}
		out = append(out, Profile{Dir: dir, Name: profileDisplayName(dir, e.Name())})
	}
	return out
}

// profileDisplayName reads profile.name from a profile's Preferences JSON,
// falling back to the directory name when it's absent or unparseable.
func profileDisplayName(profileDir, dirName string) string {
	data, err := os.ReadFile(filepath.Join(profileDir, "Preferences"))
	if err != nil {
		return dirName
	}
	var prefs struct {
		Profile struct {
			Name string `json:"name"`
		} `json:"profile"`
	}
	if err := json.Unmarshal(data, &prefs); err != nil || prefs.Profile.Name == "" {
		return dirName
	}
	return prefs.Profile.Name
}

// userDataDirs expands a candidate's per-OS locations to absolute paths.
func userDataDirs(home string, c candidate) []string {
	switch runtime.GOOS {
	case "darwin":
		return joinAll(filepath.Join(home, "Library", "Application Support"), c.mac)
	case "linux":
		return joinAll(home, c.linux)
	case "windows":
		return append(
			joinAll(os.Getenv("LOCALAPPDATA"), c.winLocal),
			joinAll(os.Getenv("APPDATA"), c.winRoaming)...,
		)
	}
	return nil
}

func joinAll(base string, subs []string) []string {
	if base == "" || len(subs) == 0 {
		return nil
	}
	out := make([]string, len(subs))
	for i, s := range subs {
		out[i] = filepath.Join(base, filepath.FromSlash(s))
	}
	return out
}
