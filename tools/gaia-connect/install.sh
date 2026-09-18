#!/bin/sh
set -e

# gaia-connect installer
# Usage: curl -fsSL https://heygaia.io/connect.sh | sh -s -- --token <code>
#
# Downloads the gaia-connect binary for this OS from the cli-v<version> GitHub
# release, verifies its SHA-256, caches it in ~/.gaia/bin/ and runs it with
# every argument passed after `sh -s --`. This is the Node-free twin of
# `npx @heygaia/cli connect` — same release tag, asset names, checksum manifest
# and cache location (packages/cli/src/commands/connect/asset.ts).
#
# NOTE: Do not rename this file. The web app serves it at heygaia.io/connect.sh
# by fetching it from GitHub using this exact path: tools/gaia-connect/install.sh

REPO="theexperiencecompany/gaia"
RELEASES_API="https://api.github.com/repos/${REPO}/releases?per_page=30"
RELEASE_BASE="https://github.com/${REPO}/releases/download"
CHECKSUMS_ASSET="gaia-connect-SHA256SUMS"
INSTALL_DIR="${HOME}/.gaia/bin"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

info() { printf "${BLUE}[info]${NC} %s\n" "$1" >&2; }
success() { printf "${GREEN}[ok]${NC} %s\n" "$1" >&2; }
error() { printf "${RED}[error]${NC} %s\n" "$1" >&2; exit 1; }

detect_os() {
  case "$(uname -s)" in
    Linux*)   echo "linux" ;;
    Darwin*)  echo "darwin" ;;
    MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
    *)        echo "unknown" ;;
  esac
}

detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64)   echo "amd64" ;;
    aarch64|arm64)  echo "arm64" ;;
    *)              echo "unknown" ;;
  esac
}

# Release asset for this OS/CPU. No fallback: an unsupported pair is fatal.
resolve_asset() {
  case "$1-$2" in
    darwin-arm64) echo "gaia-connect-darwin-arm64" ;;
    darwin-amd64) echo "gaia-connect-darwin-amd64" ;;
    linux-amd64)  echo "gaia-connect-linux-amd64" ;;
    linux-arm64)  echo "gaia-connect-linux-arm64" ;;
    windows*)
      error "gaia-connect has no shell installer for Windows. Run: npx @heygaia/cli connect --token <code>"
      ;;
    *)
      error "gaia-connect is not available for $1/$2. Supported: darwin/arm64, darwin/amd64, linux/amd64, linux/arm64."
      ;;
  esac
}

download() {
  url="$1"
  dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$dest" || error "Download failed: $url"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$dest" "$url" || error "Download failed: $url"
  else
    error "Neither curl nor wget is available. Install one and retry."
  fi
}

# Newest cli-v* tag. `releases/latest` is unusable here: the repo's releases mix
# cli-v*, desktop-v* and other tags, so the newest release is often not a CLI
# one. The API returns releases newest-first, so the first cli-v match wins.
latest_cli_tag() {
  tmp_json="$1"
  download "$RELEASES_API" "$tmp_json"
  tag=$(grep -o '"tag_name"[[:space:]]*:[[:space:]]*"cli-v[^"]*"' "$tmp_json" \
    | sed -e 's/.*"cli-v/cli-v/' -e 's/"$//' \
    | head -n 1)
  [ -n "$tag" ] || error "No cli-v* release found on ${REPO}. Set GAIA_CONNECT_VERSION to pin one."
  echo "$tag"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    error "Neither sha256sum nor shasum is available; cannot verify the download."
  fi
}

# Digest for one asset out of a `sha256sum` manifest (`<hex>  <name>` per line).
digest_for_asset() {
  digest=$(awk -v name="$2" '{ sub(/^\*/, "", $2); if ($2 == name) { print $1; exit } }' "$1")
  [ -n "$digest" ] || error "$CHECKSUMS_ASSET has no entry for $2."
  echo "$digest"
}

main() {
  OS=$(detect_os)
  ARCH=$(detect_arch)
  ASSET=$(resolve_asset "$OS" "$ARCH")

  TMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

  if [ -n "${GAIA_CONNECT_VERSION:-}" ]; then
    TAG="${GAIA_CONNECT_VERSION}"
    case "$TAG" in cli-v*) ;; *) TAG="cli-v${TAG}" ;; esac
  else
    TAG=$(latest_cli_tag "$TMP_DIR/releases.json")
  fi
  VERSION="${TAG#cli-v}"
  BIN="${INSTALL_DIR}/gaia-connect-${VERSION}"

  SUMS="$TMP_DIR/$CHECKSUMS_ASSET"
  download "${RELEASE_BASE}/${TAG}/${CHECKSUMS_ASSET}" "$SUMS"
  EXPECTED=$(digest_for_asset "$SUMS" "$ASSET")

  if [ -x "$BIN" ] && [ "$(sha256_of "$BIN")" = "$EXPECTED" ]; then
    info "Using cached gaia-connect ${TAG}"
  else
    info "Downloading gaia-connect ${TAG} (${ASSET})..."
    download "${RELEASE_BASE}/${TAG}/${ASSET}" "$TMP_DIR/$ASSET"
    ACTUAL=$(sha256_of "$TMP_DIR/$ASSET")
    if [ "$ACTUAL" != "$EXPECTED" ]; then
      error "Checksum mismatch for ${ASSET}: expected ${EXPECTED}, got ${ACTUAL}. Refusing to run the download."
    fi
    # Stage inside the install dir so the rename is atomic (same filesystem):
    # a concurrent run never sees a half-written binary.
    mkdir -p "$INSTALL_DIR"
    STAGED="${BIN}.$$.tmp"
    cp "$TMP_DIR/$ASSET" "$STAGED"
    chmod 755 "$STAGED"
    mv -f "$STAGED" "$BIN"
    success "Installed ${BIN}"
  fi

  if [ -n "${GAIA_CONNECT_INSTALL_ONLY:-}" ]; then
    echo "$BIN"
    exit 0
  fi

  trap - EXIT INT TERM
  rm -rf "$TMP_DIR"
  exec "$BIN" "$@"
}

main "$@"
