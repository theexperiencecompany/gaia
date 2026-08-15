#!/usr/bin/env bash
# build.sh — compile a Typst (.typ) or LaTeX (.tex) source to PDF, then validate.
#
# Usage:  bash build.sh <source.(typ|tex)> <output.pdf>
# Output: prints "OK: <output> (pages=N)" on success, or
#         "ERROR: <file>:<line>: <message>" (and exits non-zero) on failure.
#
# SEAM (toolchain): the ensure_* functions below provision Typst/tectonic into
# DOCGEN_HOME. This is the part that will be replaced once the toolchain is
# provided via the JuiceFS symlink layout — keep the rest (compile + validate)
# intact. Override the root with DOCGEN_HOME.
set -euo pipefail

DOCGEN_HOME="${DOCGEN_HOME:-/workspace/.gaia/docgen}"
BIN="$DOCGEN_HOME/bin"
VENV_PY="$DOCGEN_HOME/venv/bin/python"
export PATH="$BIN:$PATH"

SRC="${1:?usage: build.sh <source.(typ|tex)> <output.pdf>}"
OUT="${2:?usage: build.sh <source.(typ|tex)> <output.pdf>}"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- SEAM: toolchain provisioning (idempotent) ---------------------------------
ensure_dirs() { mkdir -p "$BIN" "$DOCGEN_HOME/venv" 2>/dev/null || true; }

ensure_typst() {
  command -v typst >/dev/null 2>&1 && return 0
  [[ -x "$BIN/typst" ]] && return 0
  # Pin the version (like tectonic below) so the fallback download is
  # reproducible — `latest` could pull a release with breaking syntax/CLI changes.
  local ver="0.13.1" arch tgt
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) tgt="x86_64-unknown-linux-musl" ;;
    aarch64|arm64) tgt="aarch64-unknown-linux-musl" ;;
    *) fail "0:0: unsupported arch for typst: $arch" ;;
  esac
  curl -fsSL "https://github.com/typst/typst/releases/download/v${ver}/typst-${tgt}.tar.xz" \
    | tar -xJ -C "$BIN" --strip-components=1 "typst-${tgt}/typst" || fail "0:0: typst download failed"
  chmod +x "$BIN/typst"
}

ensure_tectonic() {
  command -v tectonic >/dev/null 2>&1 && return 0
  [[ -x "$BIN/tectonic" ]] && return 0
  # Use the STATIC musl build, not the drop-sh installer's linux-gnu build: the
  # gnu binary needs a newer GLIBC (2.38+) than the sandbox base (Debian
  # bookworm, GLIBC 2.36) provides, so it fails to even start. musl is static.
  local ver="0.15.0" arch tgt
  arch="$(uname -m)"
  case "$arch" in
    x86_64 | amd64) tgt="x86_64-unknown-linux-musl" ;;
    aarch64 | arm64) tgt="aarch64-unknown-linux-musl" ;;
    *) fail "0:0: unsupported arch for tectonic: $arch" ;;
  esac
  curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${ver}/tectonic-${ver}-${tgt}.tar.gz" \
    | tar -xz -C "$BIN" 2>/dev/null || fail "0:0: tectonic download failed (arch $arch)"
  [[ -x "$BIN/tectonic" ]] || fail "0:0: tectonic binary missing after download"
}

# pymupdf (fitz) gives an accurate page count; falls back to a %PDF/grep check.
validate_pdf() {
  local out="$1"
  [[ -s "$out" ]] || fail "0:0: output PDF is empty or missing"
  head -c 4 "$out" | grep -q '%PDF' || fail "0:0: output is not a valid PDF"
  local pages=""
  if [[ -x "$VENV_PY" ]]; then
    pages="$("$VENV_PY" - "$out" <<'PY' 2>/dev/null || true
import sys
try:
    import fitz
    print(len(fitz.open(sys.argv[1])))
except Exception:
    pass
PY
)"
  fi
  # Typst writes compressed PDFs (page objects live inside object streams), so a
  # plaintext grep frequently finds nothing. Page count is therefore BEST-EFFORT:
  # report it when known, but never fail a PDF the compiler already produced
  # (exit 0) with a valid %PDF header — that is the real success signal.
  if [[ -z "$pages" ]]; then
    pages="$(grep -a -c '/Type[[:space:]]*/Page[^s]' "$out" 2>/dev/null || echo "")"
  fi
  if [[ -n "$pages" ]] && [[ "$pages" -ge 1 ]] 2>/dev/null; then
    echo "OK: $OUT (pages=$pages)"
  else
    echo "OK: $OUT"
  fi
}
# --- end SEAM ------------------------------------------------------------------

ensure_dirs
[[ -f "$SRC" ]] || fail "0:0: source not found: $SRC"
mkdir -p "$(dirname "$OUT")"

ext="${SRC##*.}"
err="$(mktemp)"
trap 'rm -f "$err"' EXIT

case "$ext" in
  typ)
    ensure_typst
    # Scope reads (#read/#include/image) to the source's own job directory, not
    # the whole filesystem. The .typ is LLM-generated, so --root / would let a
    # crafted document read arbitrary host files into the PDF.
    if ! typst compile --root "$(dirname "$SRC")" "$SRC" "$OUT" 2>"$err"; then
      # Typst errors look like: error: <msg>\n  ┌─ file:LINE:COL
      # `|| true`: a no-match grep exits 1 under `set -euo pipefail`, which would
      # abort before `fail` runs and swallow the diagnostic.
      msg="$(grep -m1 '^error:' "$err" | sed 's/^error:[[:space:]]*//' || true)"
      loc="$(grep -m1 -oE '[^ ]+:[0-9]+:[0-9]+' "$err" | head -1 || true)"
      fail "${loc:-$SRC:0}: ${msg:-typst compile failed (see source)}"
    fi
    ;;
  tex)
    ensure_tectonic
    if ! tectonic -X compile --outdir "$(dirname "$OUT")" "$SRC" 2>"$err"; then
      # `|| true`: a no-match grep exits 1 under `set -euo pipefail`, which would
      # abort before `fail` runs and swallow the diagnostic.
      msg="$(grep -m1 -iE 'error|! ' "$err" | sed 's/^[[:space:]]*//' | cut -c1-200 || true)"
      # Tectonic's failure line doesn't always contain "error"/"!" (e.g. bundle
      # fetch issues) — fall back to the last non-empty stderr line so the agent
      # sees the real reason instead of a generic message.
      [[ -z "$msg" ]] && msg="$(grep -v '^[[:space:]]*$' "$err" | tail -1 | cut -c1-200 || true)"
      fail "$SRC:0: ${msg:-tectonic compile failed}"
    fi
    # tectonic names output after the source stem; move to requested OUT.
    # Guard with `if` (not `[ ] && [ ] && mv`) — a false leading test would
    # return non-zero and abort under `set -e` when no move is needed.
    produced="$(dirname "$OUT")/$(basename "${SRC%.*}").pdf"
    if [[ "$produced" != "$OUT" ]] && [[ -f "$produced" ]]; then
      mv -f "$produced" "$OUT"
    fi
    ;;
  *)
    fail "0:0: unsupported source extension '.$ext' (use .typ or .tex)"
    ;;
esac

validate_pdf "$OUT"
