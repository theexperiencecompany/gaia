#!/usr/bin/env bash
# install-alert-rule-tools.sh — pint + promtool for the alert-rules lane.
#
# Pinned GitHub release tarballs, not `go install`: Prometheus v3's go.mod
# declares `module github.com/prometheus/prometheus` (no `/v3` suffix), which
# the Go tool rejects at major version 3, and a lock-file-free `go install` is
# unpinned for transitive deps anyway. --proto '=https' keeps redirects from
# ever downgrading to http.
#
# Installs into $RUNNER_TEMP/bin and prepends it to $GITHUB_PATH: the lane runs
# on the home box as an unprivileged runner user (no /usr/local/bin), and
# $RUNNER_TEMP is per instance where /tmp is shared by twenty of them.
set -euo pipefail

PINT_VERSION="0.87.0"
PROMETHEUS_VERSION="3.1.0"

BIN="${RUNNER_TEMP:?RUNNER_TEMP is required}/bin"
WORK="$(mktemp -d "${RUNNER_TEMP}/alert-rule-tools.XXXXXX")"
mkdir -p "$BIN"

echo "::group::install"
curl -sSL --proto '=https' -o "$WORK/pint.tar.gz" \
  "https://github.com/cloudflare/pint/releases/download/v${PINT_VERSION}/pint-${PINT_VERSION}-linux-amd64.tar.gz"
tar -xzf "$WORK/pint.tar.gz" -C "$WORK"
install -m 0755 "$WORK/pint-linux-amd64" "$BIN/pint"

curl -sSL --proto '=https' -o "$WORK/prometheus.tar.gz" \
  "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz"
tar -xzf "$WORK/prometheus.tar.gz" -C "$WORK"
install -m 0755 "$WORK/prometheus-${PROMETHEUS_VERSION}.linux-amd64/promtool" "$BIN/promtool"
rm -rf "$WORK"
echo "::endgroup::"

echo "$BIN" >> "$GITHUB_PATH"
echo "pint v${PINT_VERSION} + promtool v${PROMETHEUS_VERSION} installed in $BIN"
