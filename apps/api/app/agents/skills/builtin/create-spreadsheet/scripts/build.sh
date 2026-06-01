#!/usr/bin/env bash
# build.sh — run an openpyxl/pandas Python program to produce a .xlsx, then validate.
#
# Usage:  bash build.sh <source.py> <output.xlsx>
# Output: "OK: <output> (sheets=N)" on success, or "ERROR: <message>".
#
# SEAM (toolchain): ensure_venv provisions a Python venv with openpyxl + pandas
# into DOCGEN_HOME/venv. Replace with the JuiceFS symlink layout when ready;
# keep run + validate intact.
set -euo pipefail

DOCGEN_HOME="${DOCGEN_HOME:-/workspace/.gaia/docgen}"
VENV="$DOCGEN_HOME/venv"
VENV_PY="$VENV/bin/python"

SRC="${1:?usage: build.sh <source.py> <output.xlsx>}"
OUT="${2:?usage: build.sh <source.py> <output.xlsx>}"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- SEAM: toolchain provisioning (idempotent) ---------------------------------
ensure_venv() {
  if [ ! -x "$VENV_PY" ]; then
    python3 -m venv "$VENV" || fail "could not create venv"
  fi
  if ! "$VENV_PY" -c "import openpyxl, pandas" >/dev/null 2>&1; then
    "$VENV_PY" -m pip install --quiet --disable-pip-version-check openpyxl pandas \
      || fail "pip install openpyxl pandas failed"
  fi
}

# Validate OOXML + count sheets. Uses system python3 (no deps).
validate_xlsx() {
  local out="$1"
  [ -s "$out" ] || fail "output is empty or missing: $out"
  local sheets
  sheets="$(python3 - "$out" <<'PY' || true
import sys, zipfile, re
try:
    z = zipfile.ZipFile(sys.argv[1])
    if z.testzip() is not None: raise ValueError("corrupt zip")
    names = z.namelist()
    if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
        raise ValueError("not an xlsx")
    print(sum(1 for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)))
except Exception as e:
    print("ERR:" + str(e), file=sys.stderr)
PY
)"
  case "$sheets" in
    ""|ERR:*) fail "produced file is not a valid Excel workbook" ;;
  esac
  [ "${sheets:-0}" -ge 1 ] 2>/dev/null || fail "workbook has no sheets"
  echo "OK: $OUT (sheets=$sheets)"
}
# --- end SEAM ------------------------------------------------------------------

[ -f "$SRC" ] || fail "source not found: $SRC"
mkdir -p "$(dirname "$OUT")"
ensure_venv

err="$(mktemp)"; trap 'rm -f "$err"' EXIT
if ! "$VENV_PY" "$SRC" "$OUT" 2>"$err"; then
  # Surface the last line of the Python traceback (the actual error).
  msg="$(grep -E '^[A-Za-z_.]+(Error|Exception):' "$err" | tail -1 | cut -c1-200)"
  [ -z "$msg" ] && msg="$(tail -1 "$err" | cut -c1-200)"
  fail "${msg:-python failed to run $SRC (see source)}"
fi

validate_xlsx "$OUT"
