package main

import (
	"sort"
	"strings"

	"golang.org/x/net/publicsuffix"
)

// HostSummary is one selectable site: its registrable domain and cookie count.
type HostSummary struct {
	Site    string `json:"site"`    // registrable domain, e.g. "google.com"
	Cookies int    `json:"cookies"` // how many cookies roll up to it
}

// registrableSite collapses a cookie host to the site a user recognises —
// “mail.google.com“ and “accounts.google.com“ both become “google.com“ —
// using the public suffix list so multi-part TLDs (“co.uk“) are correct.
func registrableSite(host string) string {
	host = strings.TrimPrefix(strings.ToLower(host), ".")
	site, err := publicsuffix.EffectiveTLDPlusOne(host)
	if err != nil {
		return host // an IP or a bare host — key by itself rather than drop it
	}
	return site
}

// summarizeSites groups cookies by registrable domain, most cookies first.
func summarizeSites(cookies []Cookie) []HostSummary {
	counts := map[string]int{}
	for _, c := range cookies {
		counts[registrableSite(c.Domain)]++
	}
	out := make([]HostSummary, 0, len(counts))
	for site, n := range counts {
		out = append(out, HostSummary{Site: site, Cookies: n})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Cookies != out[j].Cookies {
			return out[i].Cookies > out[j].Cookies
		}
		return out[i].Site < out[j].Site
	})
	return out
}

// filterBySites keeps only cookies whose registrable domain was selected.
func filterBySites(cookies []Cookie, sites []string) []Cookie {
	want := make(map[string]bool, len(sites))
	for _, s := range sites {
		want[s] = true
	}
	out := make([]Cookie, 0, len(cookies))
	for _, c := range cookies {
		if want[registrableSite(c.Domain)] {
			out = append(out, c)
		}
	}
	return out
}
