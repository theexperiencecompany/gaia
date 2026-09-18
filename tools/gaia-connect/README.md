# gaia-connect

Sync a local browser's logins to GAIA so its server-side browser stays signed in
for your tasks. Reads the browser's own cookies — never passwords — lets you
choose which sites to sync, and uploads them to `POST /browser/import` with a
single-use code.

Browsers: the Chromium family (Chrome, Chromium, Brave, Edge, Arc, Helium) and
Firefox. Chromium cookies are encrypted with a key the OS guards, so reading them
asks once — the macOS Keychain prompt, or the GNOME Keyring / KWallet unlock on
Linux (a browser using Chromium's basic store needs no prompt); that prompt is
your consent. Firefox stores cookies in plaintext, so it never prompts.

Platforms: macOS and Linux are verified. Windows is implemented (DPAPI) but
unverified end to end, and Chrome 127+ on Windows uses App-Bound Encryption
(`v20` cookies), which needs the browser's own elevated context and fails with a
clear message. Arc has no Linux build.

## Users: run it via the CLI

Mint a single-use import code in GAIA → Settings → Browser → Import, then:

    npx @heygaia/cli connect --token <code>

Without Node, the shell installer does the same thing (macOS and Linux):

    curl -fsSL https://heygaia.io/connect.sh | sh -s -- --token <code>

Both paths download the matching `gaia-connect` binary for your OS from the
`cli-v<version>` GitHub release, verify its SHA-256, cache it in `~/.gaia/bin/`,
and forward every flag below to it untouched.

## Interactive (from source)

    go run .            # or: ./gaia-connect
    # pick a browser → approve the keychain/keyring prompt (none for Firefox) → search/toggle sites → sync

`--api` defaults to `https://api.heygaia.io`. For dev or self-hosting pass
`--api http://localhost:8510`, where the import code is auto-minted (dev bypass)
so `--token` can be omitted.

## Robot mode (agents)

No TUI, flags in, JSON out — decoupled from the View for programmatic use:

    ./gaia-connect --json --list                       # {"browsers":[...]}
    ./gaia-connect --json --browser Arc --list         # {"sessions":[{site,cookies}]}
    ./gaia-connect --json --browser Arc --sites github.com,x.com --token CODE

`GAIA_CONNECT_JSON=1` also enables robot mode; `ACCESSIBLE=1` switches the
interactive form to its screen-reader-friendly renderer.
