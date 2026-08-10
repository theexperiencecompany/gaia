#!/usr/bin/env bash
#
# Regenerate tools/semgrep/p-python.yaml — the vendored copy of Semgrep's
# `p/python` registry pack that the CI security lane scans with.
#
# WHY VENDOR IT
#   `--config p/python` resolves the ruleset from the Semgrep registry on every
#   run, so the lane's verdict could change without a commit — an upstream rule
#   addition would red an unrelated PR, and nothing in the repo would explain
#   why. That is the reason the lane sat informational for so long. Pinning the
#   scanner image by digest fixes the engine but not the rules; this file fixes
#   the rules. Every change to what CI enforces now arrives as a reviewable diff.
#
# WHEN TO RUN IT
#   Periodically, to pick up new upstream rules. Treat the result as a normal
#   PR: the diff shows exactly which rules were added, changed or dropped, and
#   any new finding it surfaces is a real one to fix rather than a surprise on
#   someone else's branch.
#
# Usage:  bash tools/semgrep/refresh-p-python.sh
#
set -euo pipefail

# Same digest the CI lane runs (.github/workflows/code-quality.yml). Fetching
# through the pinned image rather than the host keeps the request identical to
# the one the scanner itself would make.
IMAGE="semgrep/semgrep@sha256:b68f9b68483955b85042dac7b4533757779625a02dcf91e470da4c2df1b430be"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/p-python.yaml"

echo "Fetching p/python via $IMAGE ..."
docker run --rm -v "$SCRIPT_DIR:/out" "$IMAGE" python -c "
import urllib.request
req = urllib.request.Request('https://semgrep.dev/c/p/python',
                             headers={'User-Agent': 'Semgrep/1.145.0'})
data = urllib.request.urlopen(req, timeout=120).read()
if not data.lstrip().startswith(b'rules:'):
    raise SystemExit('registry did not return a rule document — refusing to overwrite')
open('/out/p-python.yaml', 'wb').write(data)
print('bytes:', len(data))
"

rules=$(grep -c '^- id:' "$OUT")
echo "p-python.yaml: $rules rules"
# A pack that suddenly collapses to a handful of rules means a bad fetch, not a
# quiet upstream deletion — better to fail here than to silently weaken CI.
if [ "$rules" -lt 100 ]; then
  echo "ERROR: only $rules rules — refusing a suspiciously small pack." >&2
  exit 1
fi
