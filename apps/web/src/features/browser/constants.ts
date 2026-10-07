/** Mirrors `BROWSER_PROFILE_TTL_DAYS` in apps/api/app/constants/browser.py —
 * saved-site session data auto-expires this long after its last use. */
export const SAVED_LOGIN_TTL_DAYS = 90;

/** The API the `gaia connect` tool talks to unless told otherwise — mirrors the
 * `--api` default in tools/gaia-connect/flags.go. The modal only spells out
 * `--api` when the web's own API origin differs (dev, self-hosted). */
export const GAIA_CONNECT_DEFAULT_API_ORIGIN = "https://api.heygaia.io";

/** The platform-detecting installer for the gaia-connect binary — the
 * Node-free twin of `gaia connect`, served from tools/gaia-connect/install.sh
 * the way heygaia.io/install.sh serves the CLI's. */
export const GAIA_CONNECT_INSTALL_URL = "https://heygaia.io/connect.sh";

/** Ways to run the tool, in the order the modal offers them; `source` only
 * makes sense against a developer's localhost API. */
export const CONNECT_RUNNERS = [
  "curl",
  "npx",
  "pnpm",
  "bun",
  "source",
] as const;
export type ConnectRunner = (typeof CONNECT_RUNNERS)[number];
