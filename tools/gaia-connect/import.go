package main

import (
	"errors"
	"fmt"
)

// loginPicker chooses what an import reads and syncs: flags in robot mode, prompts
// in interactive mode. The import itself is the same either way.
type loginPicker interface {
	browser(browsers []Browser) (Browser, error)
	profile(profiles []Profile) (Profile, error)
	// reading is told which browser is about to be read, before any keychain prompt.
	reading(b Browser)
	sites(available []HostSummary) ([]string, error)
}

var (
	errNoBrowser = errors.New("no supported browser found")
	// errNothingPicked is a picker that chose no sites: nothing is uploaded.
	errNothingPicked = errors.New("no sites selected")
	// errBrowserUnnamed is a robot listing run given no --browser: the browsers are the answer.
	errBrowserUnnamed = errors.New("no --browser given")
)

// choiceError is a browser or profile the picker could not settle on, with the choices it had.
type choiceError struct {
	err      error
	browsers []Browser
	profiles []Profile
}

func (e *choiceError) Error() string { return e.err.Error() }
func (e *choiceError) Unwrap() error { return e.err }

// browserLogins is one profile's cookies, read from the browser the picker chose.
type browserLogins struct {
	browser  Browser
	profiles []Profile
	cookies  []Cookie
}

// readLogins reads the cookies of the browser and profile pick chooses among browsers.
func readLogins(browsers []Browser, pick loginPicker) (browserLogins, error) {
	if len(browsers) == 0 {
		return browserLogins{}, errNoBrowser
	}
	b, err := pick.browser(browsers)
	if err != nil {
		return browserLogins{}, &choiceError{err: err, browsers: browsers}
	}
	profiles := ListProfiles(b)
	if len(profiles) == 0 {
		return browserLogins{}, fmt.Errorf("no profiles with cookies found for %s", b.Name)
	}
	p, err := pick.profile(profiles)
	if err != nil {
		return browserLogins{}, &choiceError{err: err, profiles: profiles}
	}
	pick.reading(b)
	cookies, err := ExtractCookies(b, p)
	if err != nil {
		return browserLogins{}, err
	}
	return browserLogins{browser: b, profiles: profiles, cookies: cookies}, nil
}

// syncLogins uploads the sites pick chooses from logins to GAIA's import endpoint.
func syncLogins(o options, logins browserLogins, pick loginPicker) (importResponse, error) {
	available := summarizeSites(logins.cookies)
	if len(available) == 0 {
		return importResponse{}, fmt.Errorf("no decryptable logins found in %s", logins.browser.Name)
	}
	sites, err := pick.sites(available)
	if err != nil {
		return importResponse{}, err
	}
	if len(sites) == 0 {
		return importResponse{}, errNothingPicked
	}
	cookies := filterBySites(logins.cookies, sites)
	if len(cookies) == 0 {
		return importResponse{}, errors.New("no cookies matched the selected sites")
	}
	token, err := resolveToken(o)
	if err != nil {
		return importResponse{}, err
	}
	return Upload(o.api, token, logins.browser.Name, cookies)
}
