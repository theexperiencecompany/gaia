package main

import "flag"

func flagSet(o *options) *flag.FlagSet {
	fs := flag.NewFlagSet("gaia-connect", flag.ContinueOnError)
	fs.StringVar(&o.api, "api", "http://localhost:8510", "GAIA API base URL")
	fs.StringVar(&o.token, "token", "", "single-use import code from GAIA (auto-minted on localhost)")
	fs.StringVar(&o.browser, "browser", "", "browser name (skips the picker)")
	fs.StringVar(&o.profile, "profile", "", "profile name or directory (skips the picker)")
	fs.StringVar(&o.sites, "sites", "", "comma-separated registrable domains to sync (default: all)")
	fs.BoolVar(&o.jsonMode, "json", false, "robot mode: no TUI, structured JSON on stdout")
	fs.BoolVar(&o.list, "list", false, "with --json: list browsers, or sessions when --browser is set")
	return fs
}
