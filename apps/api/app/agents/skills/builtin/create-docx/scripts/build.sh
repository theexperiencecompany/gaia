#!/usr/bin/env bash
# build.sh — run a docx-js Node program to produce a .docx, then validate it.
#
# Usage:  bash build.sh <source.mjs> <output.docx>
# Output: "OK: <output>" on success, or "ERROR: <message>" (exit non-zero).
#
# SEAM (toolchain): ensure_node_pkg provisions the `docx` library into
# DOCGEN_HOME/node. Replace this with the JuiceFS symlink layout when ready;
# keep run + validate intact. Override the root with DOCGEN_HOME.
set -euo pipefail

DOCGEN_HOME="${DOCGEN_HOME:-/workspace/.gaia/docgen}"
NODE_HOME="$DOCGEN_HOME/node"

SRC="${1:?usage: build.sh <source.mjs> <output.docx>}"
OUT="${2:?usage: build.sh <source.mjs> <output.docx>}"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- SEAM: toolchain provisioning (idempotent) ---------------------------------
ensure_node_pkg() {
  local pkg="$1"
  mkdir -p "$NODE_HOME"
  [ -f "$NODE_HOME/package.json" ] || ( cd "$NODE_HOME" && npm init -y >/dev/null 2>&1 )
  [ -d "$NODE_HOME/node_modules/$pkg" ] && return 0
  ( cd "$NODE_HOME" && npm install "$pkg" >/dev/null 2>&1 ) || fail "npm install $pkg failed"
}

# Validate an OOXML file: valid zip + required member present. Uses system
# python3 (present in the sandbox base image) — no extra deps.
validate_ooxml() {
  local out="$1" member="$2"
  [ -s "$out" ] || fail "output is empty or missing: $out"
  python3 - "$out" "$member" <<'PY' || fail "produced file is not a valid Office document"
import sys, zipfile
path, member = sys.argv[1], sys.argv[2]
try:
    z = zipfile.ZipFile(path)
    if z.testzip() is not None:
        raise ValueError("corrupt zip entry")
    names = set(z.namelist())
    for required in ("[Content_Types].xml", member):
        if required not in names:
            raise ValueError(f"missing {required}")
except Exception as e:
    print(e, file=sys.stderr); sys.exit(1)
PY
}
# --- end SEAM ------------------------------------------------------------------

[ -f "$SRC" ] || fail "source not found: $SRC"
mkdir -p "$(dirname "$OUT")"
ensure_node_pkg docx
# ESM bare imports ("docx") resolve by walking up from the SOURCE file's dir —
# NODE_PATH applies only to CommonJS require(), not ESM. Symlink the shared
# install next to the source (the session scratch dir is writable) so
# `import ... from "docx"` resolves without a per-job npm install.
ln -sfn "$NODE_HOME/node_modules" "$(dirname "$SRC")/node_modules"

err="$(mktemp)"; trap 'rm -f "$err"' EXIT
if ! node "$SRC" "$OUT" 2>"$err"; then
  # `|| true`: under `set -euo pipefail` a no-match grep exits 1, which would
  # abort the script before `fail` runs and swallow the error message.
  msg="$(grep -m1 -E 'Error|error' "$err" | sed 's/^[[:space:]]*//' | cut -c1-200 || true)"
  fail "${msg:-node failed to run $SRC (see source)}"
fi

validate_ooxml "$OUT" "word/document.xml"
echo "OK: $OUT"
