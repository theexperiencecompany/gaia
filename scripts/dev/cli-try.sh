#!/usr/bin/env bash
# cli-try.sh — try this tree's CLI on a fresh machine without CI or a publish.
#
# Builds and packs packages/cli, builds the self-host bundle with the release's
# own code (scripts/ci/release.sh selfhost-bundle), serves both and this
# branch's install.sh over HTTP, and prints the commands to paste in the VM.
# The images are a published release's (GAIA_VERSION, default the newest
# cli-v* tag on origin), so nothing is built: the bundle is labelled with that
# release, and the CLI installs it because GAIA_VERSION names it.
#
# Env: GAIA_VERSION (optional, e.g. v0.7.0-beta.3), CLI_TRY_PORT (default 8790).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${CLI_TRY_PORT:-8790}"
OUT="$ROOT/dist/cli-try"

newest_release() {
  git -C "$ROOT" ls-remote --tags --refs origin 'cli-v*' |
    sed -n 's|.*refs/tags/cli-||p' |
    node -e '
      const semver = require(process.argv[1]);
      const tags = require("fs").readFileSync(0, "utf8").split("\n").filter((t) => semver.valid(t));
      if (!tags.length) process.exit(1);
      console.log(semver.rsort(tags)[0]);
    ' "$ROOT/packages/cli/node_modules/semver"
}

IMAGES="${GAIA_VERSION:-$(newest_release)}"
[[ "$IMAGES" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || {
  echo "cli-try: GAIA_VERSION must be a release tag like v0.7.0-beta.3, got '$IMAGES'" >&2
  exit 1
}

rm -rf "$OUT"
mkdir -p "$OUT"

echo "==> Building the CLI"
pnpm --dir "$ROOT/packages/cli" run build
(cd "$ROOT/packages/cli" && pnpm pack --pack-destination "$OUT" >/dev/null)
TARBALL="$(basename "$(ls "$OUT"/*.tgz)")"

echo "==> Building the self-host bundle for $IMAGES"
VERSION="${IMAGES#v}" OUT_DIR="$OUT" bash "$ROOT/scripts/ci/release.sh" selfhost-bundle

cp -f "$ROOT/packages/cli/install.sh" "$OUT/install.sh"

paste_commands() {
  local base="http://$1:$PORT"
  echo "    curl -fsSL $base/install.sh | GAIA_CLI_TARBALL=$base/$TARBALL GAIA_BUNDLE_BASE_URL=$base GAIA_VERSION=$IMAGES sh"
  echo "  and, for later commands (gaia update) in that shell:"
  echo "    export GAIA_BUNDLE_BASE_URL=$base GAIA_VERSION=$IMAGES"
}

echo
echo "Serving $OUT on port $PORT. In an OrbStack VM, paste:"
paste_commands host.orb.internal
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
if [[ -n "$LAN_IP" ]]; then
  echo
  echo "On another machine on your network:"
  paste_commands "$LAN_IP"
fi
echo
echo "Ctrl-C stops the server."
exec python3 -m http.server "$PORT" --bind 0.0.0.0 --directory "$OUT"
