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
  [ -x "$BIN/typst" ] && return 0
  local arch; arch="$(uname -m)"; local tgt
  case "$arch" in
    x86_64|amd64) tgt="x86_64-unknown-linux-musl" ;;
    aarch64|arm64) tgt="aarch64-unknown-linux-musl" ;;
    *) fail "0:0: unsupported arch for typst: $arch" ;;
  esac
  curl -fsSL "https://github.com/typst/typst/releases/latest/download/typst-${tgt}.tar.xz" \
    | tar -xJ -C "$BIN" --strip-components=1 "typst-${tgt}/typst" || fail "0:0: typst download failed"
  chmod +x "$BIN/typst"
}

ensure_tectonic() {
  command -v tectonic >/dev/null 2>&1 && return 0
  [ -x "$BIN/tectonic" ] && return 0
  ( cd "$BIN" && curl -fsSL https://drop-sh.fullyjustified.net | sh ) \
    || fail "0:0: tectonic install failed"
}

# pymupdf (fitz) gives an accurate page count; falls back to a %PDF/grep check.
validate_pdf() {
  local out="$1"
  [ -s "$out" ] || fail "0:0: output PDF is empty or missing"
  head -c 4 "$out" | grep -q '%PDF' || fail "0:0: output is not a valid PDF"
  local pages=""
  if [ -x "$VENV_PY" ]; then
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
  [ -z "$pages" ] && pages="$(grep -a -c '/Type[[:space:]]*/Page[^s]' "$out" 2>/dev/null || echo 0)"
  [ "${pages:-0}" -ge 1 ] 2>/dev/null || fail "0:0: PDF has no pages"
  echo "OK: $OUT (pages=$pages)"
}
# --- end SEAM ------------------------------------------------------------------

ensure_dirs
[ -f "$SRC" ] || fail "0:0: source not found: $SRC"
mkdir -p "$(dirname "$OUT")"

ext="${SRC##*.}"
err="$(mktemp)"
trap 'rm -f "$err"' EXIT

case "$ext" in
  typ)
    ensure_typst
    if ! typst compile --root / "$SRC" "$OUT" 2>"$err"; then
      # Typst errors look like: error: <msg>\n  ┌─ file:LINE:COL
      msg="$(grep -m1 '^error:' "$err" | sed 's/^error:[[:space:]]*//')"
      loc="$(grep -m1 -oE '[^ ]+:[0-9]+:[0-9]+' "$err" | head -1)"
      fail "${loc:-$SRC:0}: ${msg:-typst compile failed (see source)}"
    fi
    ;;
  tex)
    ensure_tectonic
    if ! tectonic -X compile --outdir "$(dirname "$OUT")" "$SRC" 2>"$err"; then
      msg="$(grep -m1 -iE 'error|! ' "$err" | sed 's/^[[:space:]]*//' | cut -c1-200)"
      fail "$SRC:0: ${msg:-tectonic compile failed}"
    fi
    # tectonic names output after the source stem; move to requested OUT.
    produced="$(dirname "$OUT")/$(basename "${SRC%.*}").pdf"
    [ "$produced" != "$OUT" ] && [ -f "$produced" ] && mv -f "$produced" "$OUT"
    ;;
  *)
    fail "0:0: unsupported source extension '.$ext' (use .typ or .tex)"
    ;;
esac

validate_pdf "$OUT"
