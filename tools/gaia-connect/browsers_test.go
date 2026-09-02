package main

import (
	"os"
	"path/filepath"
	"testing"
)

// writeProfile lays down a fake profile directory with a Cookies file and,
// optionally, a Preferences JSON carrying a display name.
func writeProfile(t *testing.T, userDataDir, dir, displayName string) {
	t.Helper()
	p := filepath.Join(userDataDir, dir)
	if err := os.MkdirAll(p, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(p, "Cookies"), []byte("db"), 0o644); err != nil {
		t.Fatal(err)
	}
	if displayName != "" {
		prefs := `{"profile":{"name":"` + displayName + `"}}`
		if err := os.WriteFile(filepath.Join(p, "Preferences"), []byte(prefs), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestListProfilesReadsDisplayNames(t *testing.T) {
	dir := t.TempDir()
	writeProfile(t, dir, "Default", "Alice")
	writeProfile(t, dir, "Profile 1", "Work")

	profiles := ListProfiles(dir)
	if len(profiles) != 2 {
		t.Fatalf("expected 2 profiles, got %d: %+v", len(profiles), profiles)
	}
	// os.ReadDir sorts by filename: "Default" before "Profile 1".
	if profiles[0].Name != "Alice" || filepath.Base(profiles[0].Dir) != "Default" {
		t.Errorf("profile[0] = %+v, want Default/Alice", profiles[0])
	}
	if profiles[1].Name != "Work" || filepath.Base(profiles[1].Dir) != "Profile 1" {
		t.Errorf("profile[1] = %+v, want Profile 1/Work", profiles[1])
	}
}

func TestListProfilesFallsBackToDirNameWithoutPreferences(t *testing.T) {
	dir := t.TempDir()
	writeProfile(t, dir, "Profile 2", "") // no Preferences file

	profiles := ListProfiles(dir)
	if len(profiles) != 1 || profiles[0].Name != "Profile 2" {
		t.Fatalf("expected fallback to dir name, got %+v", profiles)
	}
}

func TestListProfilesFallsBackWhenPreferencesUnparseable(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "Default")
	if err := os.MkdirAll(p, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(p, "Cookies"), []byte("db"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(p, "Preferences"), []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}

	profiles := ListProfiles(dir)
	if len(profiles) != 1 || profiles[0].Name != "Default" {
		t.Fatalf("expected fallback to dir name on bad JSON, got %+v", profiles)
	}
}

func TestListProfilesSkipsDirsWithoutCookies(t *testing.T) {
	dir := t.TempDir()
	writeProfile(t, dir, "Default", "Alice")
	// A sibling dir with no Cookies file (e.g. "System Profile") must be ignored.
	if err := os.MkdirAll(filepath.Join(dir, "System Profile"), 0o755); err != nil {
		t.Fatal(err)
	}

	profiles := ListProfiles(dir)
	if len(profiles) != 1 || filepath.Base(profiles[0].Dir) != "Default" {
		t.Fatalf("expected only Default, got %+v", profiles)
	}
}

func TestPickProfileByNameMatchesNameOrDirectory(t *testing.T) {
	dir := t.TempDir()
	writeProfile(t, dir, "Default", "Alice")
	writeProfile(t, dir, "Profile 1", "Work")
	profiles := ListProfiles(dir)

	byName, err := pickProfileByName(profiles, "work")
	if err != nil || filepath.Base(byName.Dir) != "Profile 1" {
		t.Fatalf("match by display name failed: %+v err=%v", byName, err)
	}
	byDir, err := pickProfileByName(profiles, "Default")
	if err != nil || byDir.Name != "Alice" {
		t.Fatalf("match by directory name failed: %+v err=%v", byDir, err)
	}
	if _, err := pickProfileByName(profiles, "nope"); err == nil {
		t.Fatal("expected error for unknown profile")
	}
	if _, err := pickProfileByName(profiles, ""); err == nil {
		t.Fatal("expected error when profile is ambiguous and unspecified")
	}
}
