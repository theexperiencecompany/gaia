// Command gaia-connect syncs a local browser's logins to GAIA.
//
// It reads the browser's own encrypted cookies (prompting the OS keychain once),
// lets you choose which sites to sync, and uploads them to GAIA's import endpoint
// with a single-use code. Two frontends over one pure core: an interactive huh
// form, and a --json robot mode for agents that drives the same steps by flags.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/charmbracelet/huh"
)

// Fixed viewport heights so a long list scrolls in place instead of
// flooding the terminal — hundreds of sites is normal.
const (
	sessionListHeight = 15
	browserListHeight = 8
	profileListHeight = 8
)

type options struct {
	api      string
	token    string
	browser  string
	profile  string
	sites    string
	jsonMode bool
	list     bool
}

// result is the machine-readable envelope emitted in --json mode.
type result struct {
	OK          bool          `json:"ok"`
	Error       string        `json:"error,omitempty"`
	Browsers    []string      `json:"browsers,omitempty"`
	Profiles    []Profile     `json:"profiles,omitempty"`
	Sessions    []HostSummary `json:"sessions,omitempty"`
	Imported    []string      `json:"imported,omitempty"`
	HostCount   int           `json:"host_count,omitempty"`
	CookieCount int           `json:"cookie_count,omitempty"`
}

func main() {
	opts := parseFlags()
	if opts.jsonMode {
		emit(runRobot(opts))
		return
	}
	if err := runInteractive(opts); err != nil {
		fmt.Fprintf(os.Stderr, "\nerror: %v\n", err)
		os.Exit(1)
	}
}

func parseFlags() options {
	var o options
	fs := flagSet(&o)
	_ = fs.Parse(os.Args[1:])
	if o.jsonMode || os.Getenv("GAIA_CONNECT_JSON") != "" {
		o.jsonMode = true
	}
	return o
}

// ---- robot (JSON) mode: no TUI, flags in, structured JSON out ----

func runRobot(o options) result {
	browsers := DetectBrowsers()
	if len(browsers) == 0 {
		return result{Error: "no Chromium-family browser found"}
	}
	if o.browser == "" && o.list {
		return result{OK: true, Browsers: browserNames(browsers)}
	}
	b, err := pickBrowserByName(browsers, o.browser)
	if err != nil {
		return result{Error: err.Error(), Browsers: browserNames(browsers)}
	}
	profiles := ListProfiles(b.UserDataDir)
	if len(profiles) == 0 {
		return result{Error: fmt.Sprintf("no profiles with cookies found for %s", b.Name)}
	}
	p, err := pickProfileByName(profiles, o.profile)
	if err != nil {
		// In list mode an ambiguous profile isn't fatal: hand back the profiles
		// so the caller can pick one and re-run with --profile.
		if o.list {
			return result{OK: true, Profiles: profiles}
		}
		return result{Error: err.Error(), Profiles: profiles}
	}
	cookies, err := ExtractCookies(b, p)
	if err != nil {
		return result{Error: err.Error()}
	}
	if o.list {
		return result{OK: true, Profiles: profiles, Sessions: summarizeSites(cookies)}
	}
	if o.sites != "" {
		cookies = filterBySites(cookies, splitCSV(o.sites))
	}
	if len(cookies) == 0 {
		return result{Error: "no cookies matched the selected sites"}
	}
	token, err := resolveToken(o)
	if err != nil {
		return result{Error: err.Error()}
	}
	resp, err := Upload(o.api, token, b.Name, cookies)
	if err != nil {
		return result{Error: err.Error()}
	}
	return result{
		OK: true, Imported: importedDomains(resp),
		HostCount: resp.HostCount, CookieCount: resp.CookieCount,
	}
}

// ---- interactive mode: huh Select + filterable MultiSelect ----

func runInteractive(o options) error {
	browsers := DetectBrowsers()
	if len(browsers) == 0 {
		return fmt.Errorf("no Chromium-family browser found under your profile directory")
	}

	b, err := selectBrowser(browsers)
	if err != nil {
		return err
	}
	profiles := ListProfiles(b.UserDataDir)
	if len(profiles) == 0 {
		return fmt.Errorf("no profiles with cookies found in %s", b.Name)
	}
	p, err := selectProfile(profiles)
	if err != nil {
		return err
	}
	fmt.Printf("Reading %s — approve the keychain prompt to continue…\n", b.Name)
	cookies, err := ExtractCookies(b, p)
	if err != nil {
		return err
	}
	sites := summarizeSites(cookies)
	if len(sites) == 0 {
		return fmt.Errorf("no decryptable logins found in %s", b.Name)
	}

	picked, err := selectSites(sites)
	if err != nil {
		return err
	}
	if len(picked) == 0 {
		fmt.Println("Nothing selected — done.")
		return nil
	}
	cookies = filterBySites(cookies, picked)

	token, err := resolveToken(o)
	if err != nil {
		return err
	}
	resp, err := Upload(o.api, token, b.Name, cookies)
	if err != nil {
		return err
	}
	fmt.Printf("\n✓ Synced %d sites to GAIA — they'll stay logged in for your tasks.\n", resp.HostCount)
	return nil
}

func selectBrowser(browsers []Browser) (Browser, error) {
	if len(browsers) == 1 {
		return browsers[0], nil
	}
	options := make([]huh.Option[string], len(browsers))
	for i, b := range browsers {
		options[i] = huh.NewOption(b.Name, b.Name)
	}
	var choice string
	form := huh.NewForm(huh.NewGroup(
		huh.NewSelect[string]().Title("Which browser's logins?").Options(options...).Height(browserListHeight).Value(&choice),
	)).WithAccessible(os.Getenv("ACCESSIBLE") != "")
	if err := form.Run(); err != nil {
		return Browser{}, err
	}
	return pickBrowserByName(browsers, choice)
}

func selectProfile(profiles []Profile) (Profile, error) {
	if len(profiles) == 1 {
		return profiles[0], nil
	}
	options := make([]huh.Option[string], len(profiles))
	for i, p := range profiles {
		options[i] = huh.NewOption(p.Name, p.Dir) // key on Dir — display names can repeat
	}
	var choice string
	form := huh.NewForm(huh.NewGroup(
		huh.NewSelect[string]().Title("Which profile?").Options(options...).Height(profileListHeight).Value(&choice),
	)).WithAccessible(os.Getenv("ACCESSIBLE") != "")
	if err := form.Run(); err != nil {
		return Profile{}, err
	}
	for _, p := range profiles {
		if p.Dir == choice {
			return p, nil
		}
	}
	return Profile{}, fmt.Errorf("selected profile not found")
}

func selectSites(sites []HostSummary) ([]string, error) {
	options := make([]huh.Option[string], len(sites))
	for i, s := range sites {
		label := fmt.Sprintf("%s  (%d cookies)", s.Site, s.Cookies)
		options[i] = huh.NewOption(label, s.Site).Selected(true)
	}
	var picked []string
	form := huh.NewForm(huh.NewGroup(
		huh.NewMultiSelect[string]().
			Title("Sync which logins? (all selected — type to search, space to toggle)").
			Options(options...).
			Filterable(true).
			Height(sessionListHeight).
			Value(&picked),
	)).WithAccessible(os.Getenv("ACCESSIBLE") != "")
	if err := form.Run(); err != nil {
		return nil, err
	}
	return picked, nil
}

// ---- shared helpers ----

func resolveToken(o options) (string, error) {
	if o.token != "" {
		return o.token, nil
	}
	if isLocalhost(o.api) {
		return MintToken(o.api) // dev convenience: localhost mints via the dev-bypass
	}
	return "", fmt.Errorf("no --token given; mint one in GAIA → Settings → Connect browser")
}

func pickBrowserByName(browsers []Browser, name string) (Browser, error) {
	if name == "" {
		if len(browsers) == 1 {
			return browsers[0], nil
		}
		return Browser{}, fmt.Errorf("multiple browsers found; pass --browser (%s)", strings.Join(browserNames(browsers), ", "))
	}
	for _, b := range browsers {
		if strings.EqualFold(b.Name, name) {
			return b, nil
		}
	}
	return Browser{}, fmt.Errorf("browser %q not found among %s", name, strings.Join(browserNames(browsers), ", "))
}

func pickProfileByName(profiles []Profile, name string) (Profile, error) {
	if name == "" {
		if len(profiles) == 1 {
			return profiles[0], nil
		}
		return Profile{}, fmt.Errorf("multiple profiles found; pass --profile (%s)", strings.Join(profileNames(profiles), ", "))
	}
	for _, p := range profiles {
		if strings.EqualFold(p.Name, name) || strings.EqualFold(filepath.Base(p.Dir), name) {
			return p, nil
		}
	}
	return Profile{}, fmt.Errorf("profile %q not found among %s", name, strings.Join(profileNames(profiles), ", "))
}

func profileNames(profiles []Profile) []string {
	out := make([]string, len(profiles))
	for i, p := range profiles {
		out[i] = p.Name
	}
	return out
}

func browserNames(browsers []Browser) []string {
	out := make([]string, len(browsers))
	for i, b := range browsers {
		out[i] = b.Name
	}
	return out
}

func importedDomains(r importResponse) []string {
	out := make([]string, len(r.Imported))
	for i, h := range r.Imported {
		out[i] = h.Domain
	}
	return out
}

func isLocalhost(api string) bool {
	return strings.Contains(api, "localhost") || strings.Contains(api, "127.0.0.1")
}

func splitCSV(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func emit(r result) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(r)
	if !r.OK {
		os.Exit(1)
	}
}
