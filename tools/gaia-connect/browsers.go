package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
)

// Browser is one installed Chromium-family browser we can read a profile from.
type Browser struct {
	Name            string // display name
	UserDataDir     string // the browser's user-data root (holds Default/, Profile 1/, …)
	KeychainService string // macOS Keychain generic-password service ("<Name> Safe Storage")
	KeychainAccount string // macOS Keychain account (usually the browser name)
}

// candidate is a browser we know how to locate, before checking it exists on disk.
type candidate struct {
	name      string
	macSubdir string // under ~/Library/Application Support
	linuxSub  string // under ~/.config
	winSub    string // under %LOCALAPPDATA%
}

var candidates = []candidate{
	{"Arc", "Arc/User Data", "", "Arc/User Data"},
	{"Chrome", "Google/Chrome", "google-chrome", "Google/Chrome/User Data"},
	{"Helium", "net.imput.helium", "helium", "Helium/User Data"},
	{"Brave", "BraveSoftware/Brave-Browser", "BraveSoftware/Brave-Browser", "BraveSoftware/Brave-Browser/User Data"},
	{"Edge", "Microsoft Edge", "microsoft-edge", "Microsoft/Edge/User Data"},
}

// DetectBrowsers returns every candidate whose profile actually exists on disk.
func DetectBrowsers() []Browser {
	home, _ := os.UserHomeDir()
	var out []Browser
	for _, c := range candidates {
		dir := userDataDir(home, c)
		if dir == "" {
			continue
		}
		if _, err := os.Stat(filepath.Join(dir, "Default", "Cookies")); err != nil {
			continue
		}
		out = append(out, Browser{
			Name:            c.name,
			UserDataDir:     dir,
			KeychainService: c.name + " Safe Storage",
			KeychainAccount: c.name,
		})
	}
	return out
}

// Profile is one browser profile under a user-data dir (Chrome's "Default",
// "Profile 1", …). Dir is the absolute path to that profile's directory; Name
// is its display name from Preferences, falling back to the directory name.
type Profile struct {
	Dir  string `json:"dir"`
	Name string `json:"name"`
}

// ListProfiles returns every profile under a browser's user-data dir that has a
// Cookies database, each with its display name. os.ReadDir sorts by filename,
// so "Default" comes first and the order is stable for pickers and robots.
func ListProfiles(userDataDir string) []Profile {
	entries, err := os.ReadDir(userDataDir)
	if err != nil {
		return nil
	}
	var out []Profile
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		dir := filepath.Join(userDataDir, e.Name())
		if _, err := os.Stat(filepath.Join(dir, "Cookies")); err != nil {
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

func userDataDir(home string, c candidate) string {
	switch runtime.GOOS {
	case "darwin":
		if c.macSubdir == "" {
			return ""
		}
		return filepath.Join(home, "Library", "Application Support", c.macSubdir)
	case "linux":
		if c.linuxSub == "" {
			return ""
		}
		return filepath.Join(home, ".config", c.linuxSub)
	case "windows":
		if c.winSub == "" {
			return ""
		}
		return filepath.Join(os.Getenv("LOCALAPPDATA"), c.winSub)
	}
	return ""
}
