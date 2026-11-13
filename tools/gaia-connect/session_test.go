package main

import "testing"

func TestRegistrableSiteCollapsesSubdomains(t *testing.T) {
	for _, tc := range []struct{ in, want string }{
		{"accounts.google.com", "google.com"},
		{"mail.google.com", "google.com"},
		{".github.com", "github.com"},
		{"www.bbc.co.uk", "bbc.co.uk"}, // multi-part TLD via public suffix list
	} {
		if got := registrableSite(tc.in); got != tc.want {
			t.Errorf("registrableSite(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestSummarizeSitesGroupsAndSorts(t *testing.T) {
	cookies := []Cookie{
		{Domain: ".google.com"}, {Domain: "accounts.google.com"}, {Domain: "mail.google.com"},
		{Domain: ".github.com"},
	}
	sites := summarizeSites(cookies)
	if len(sites) != 2 || sites[0].Site != "google.com" || sites[0].Cookies != 3 {
		t.Fatalf("expected google.com(3) first, got %+v", sites)
	}
}

func TestFilterBySitesKeepsOnlySelected(t *testing.T) {
	cookies := []Cookie{
		{Name: "g", Domain: ".google.com"}, {Name: "gh", Domain: ".github.com"},
	}
	got := filterBySites(cookies, []string{"github.com"})
	if len(got) != 1 || got[0].Name != "gh" {
		t.Fatalf("filter kept the wrong cookies: %+v", got)
	}
}
