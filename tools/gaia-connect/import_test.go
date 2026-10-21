package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

// firefoxWithLogins builds a Firefox install with one profile holding a GitHub and a Google login.
func firefoxWithLogins(t *testing.T) Browser {
	t.Helper()
	root := t.TempDir()
	profile := filepath.Join(root, "abcd1234.default-release")
	if err := os.MkdirAll(profile, 0o755); err != nil {
		t.Fatal(err)
	}
	writeFirefoxProfile(t, profile, [][]any{
		{".github.com", "sid", "gh", "/", 1893456000, 1, 1, 1},
		{"accounts.google.com", "SID", "goog", "/", 1893456000, 1, 1, 1},
	})
	return Browser{Name: "Firefox", Family: familyFirefox, UserDataDir: root}
}

// gaiaImport stands in for GAIA's import endpoint, recording every upload.
func gaiaImport(t *testing.T) (*httptest.Server, *[]importRequest) {
	t.Helper()
	var uploads []importRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req importRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatal(err)
		}
		uploads = append(uploads, req)
		_ = json.NewEncoder(w).Encode(importResponse{HostCount: 1, CookieCount: len(req.Cookies)})
	}))
	t.Cleanup(srv.Close)
	return srv, &uploads
}

func TestRobotImportUploadsOnlyTheSitesNamedByFlag(t *testing.T) {
	srv, uploads := gaiaImport(t)
	o := options{api: srv.URL, token: "code", sites: "github.com"}

	logins, err := readLogins([]Browser{firefoxWithLogins(t)}, flagPicker{o})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := syncLogins(o, logins, flagPicker{o}); err != nil {
		t.Fatal(err)
	}

	if len(*uploads) != 1 || len((*uploads)[0].Cookies) != 1 || (*uploads)[0].Cookies[0].Value != "gh" {
		t.Fatalf("expected only the GitHub login uploaded, got %+v", *uploads)
	}
	if (*uploads)[0].Token != "code" || (*uploads)[0].SourceBrowser != "Firefox" {
		t.Fatalf("upload not addressed with the token and browser: %+v", (*uploads)[0])
	}
}

func TestRobotImportWithoutSitesUploadsEveryLogin(t *testing.T) {
	srv, uploads := gaiaImport(t)
	o := options{api: srv.URL, token: "code"}

	logins, err := readLogins([]Browser{firefoxWithLogins(t)}, flagPicker{o})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := syncLogins(o, logins, flagPicker{o}); err != nil {
		t.Fatal(err)
	}

	if len(*uploads) != 1 || len((*uploads)[0].Cookies) != 2 {
		t.Fatalf("expected both logins uploaded, got %+v", *uploads)
	}
}

// pickNone is a user who deselected every site.
type pickNone struct{ flagPicker }

func (pickNone) sites([]HostSummary) ([]string, error) { return nil, nil }

func TestAnImportWithNoSitePickedUploadsNothing(t *testing.T) {
	srv, uploads := gaiaImport(t)
	o := options{api: srv.URL, token: "code"}
	logins, err := readLogins([]Browser{firefoxWithLogins(t)}, flagPicker{o})
	if err != nil {
		t.Fatal(err)
	}

	_, err = syncLogins(o, logins, pickNone{flagPicker{o}})

	if !errors.Is(err, errNothingPicked) || len(*uploads) != 0 {
		t.Fatalf("expected no upload and errNothingPicked, got %v and %+v", err, *uploads)
	}
}

func TestRobotListingWithoutABrowserNamesTheBrowsers(t *testing.T) {
	o := options{list: true}

	_, err := readLogins([]Browser{firefoxWithLogins(t)}, flagPicker{o})
	got := robotFailure(o, err)

	if !got.OK || got.Error != "" || len(got.Browsers) != 1 || got.Browsers[0] != "Firefox" {
		t.Fatalf("expected the browser list, got %+v", got)
	}
}

func TestRobotImportNamingAnUnknownBrowserFailsWithTheChoices(t *testing.T) {
	o := options{browser: "Netscape"}

	_, err := readLogins([]Browser{firefoxWithLogins(t)}, flagPicker{o})
	got := robotFailure(o, err)

	if got.OK || got.Error == "" || len(got.Browsers) != 1 {
		t.Fatalf("expected a failure listing the browsers, got %+v", got)
	}
}
