#!/usr/bin/env bash
# build.sh — run a pptxgenjs Node program to produce a .pptx, then validate it.
#
# Usage:  bash build.sh <source.mjs> <output.pptx>
# Output: "OK: <output> (slides=N)" on success, or "ERROR: <message>".
#
# SEAM (toolchain): ensure_node_pkg provisions `pptxgenjs` into DOCGEN_HOME/node.
# Replace with the JuiceFS symlink layout when ready; keep run + validate intact.
set -euo pipefail

DOCGEN_HOME="${DOCGEN_HOME:-/workspace/.gaia/docgen}"
NODE_HOME="$DOCGEN_HOME/node"

SRC="${1:?usage: build.sh <source.mjs> <output.pptx>}"
OUT="${2:?usage: build.sh <source.mjs> <output.pptx>}"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- SEAM: toolchain provisioning (idempotent) ---------------------------------
ensure_node_pkg() {
  local pkg="$1"
  mkdir -p "$NODE_HOME"
  [ -f "$NODE_HOME/package.json" ] || ( cd "$NODE_HOME" && npm init -y >/dev/null 2>&1 )
  [ -d "$NODE_HOME/node_modules/$pkg" ] && return 0
  ( cd "$NODE_HOME" && npm install "$pkg" >/dev/null 2>&1 ) || fail "npm install $pkg failed"
}

# Validate OOXML + count slides. Uses system python3 (base image) — no deps.
validate_pptx() {
  local out="$1"
  [ -s "$out" ] || fail "output is empty or missing: $out"
  local slides
  slides="$(python3 - "$out" <<'PY' || true
import sys, zipfile, re
try:
    z = zipfile.ZipFile(sys.argv[1])
    if z.testzip() is not None: raise ValueError("corrupt zip")
    names = z.namelist()
    if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
        raise ValueError("not a pptx")
    print(sum(1 for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)))
except Exception as e:
    print("ERR:" + str(e), file=sys.stderr)
PY
)"
  case "$slides" in
    ""|ERR:*) fail "produced file is not a valid PowerPoint" ;;
  esac
  [ "${slides:-0}" -ge 1 ] 2>/dev/null || fail "presentation has no slides"
  echo "OK: $OUT (slides=$slides)"
}
# --- end SEAM ------------------------------------------------------------------

[ -f "$SRC" ] || fail "source not found: $SRC"
mkdir -p "$(dirname "$OUT")"
ensure_node_pkg pptxgenjs
# ESM bare imports ("pptxgenjs") resolve by walking up from the SOURCE file's
# dir — NODE_PATH applies only to CommonJS require(), not ESM. Symlink the
# shared install next to the source (the session scratch dir is writable) so
# `import pptxgen from "pptxgenjs"` resolves without a per-job npm install.
ln -sfn "$NODE_HOME/node_modules" "$(dirname "$SRC")/node_modules"

err="$(mktemp)"; trap 'rm -f "$err"' EXIT
if ! node "$SRC" "$OUT" 2>"$err"; then
  # `|| true`: under `set -euo pipefail` a no-match grep exits 1, which would
  # abort the script before `fail` runs and swallow the error message.
  msg="$(grep -m1 -E 'Error|error' "$err" | sed 's/^[[:space:]]*//' | cut -c1-200 || true)"
  fail "${msg:-node failed to run $SRC (see source)}"
fi

validate_pptx "$OUT"
