#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_PATH="$ROOT_DIR/libs/shared/ts/src/cli/command-manifest.ts"
CLI_PACKAGE_JSON="$ROOT_DIR/packages/cli/package.json"

if [[ ! -f "$MANIFEST_PATH" ]]; then
  echo "Missing command manifest: $MANIFEST_PATH"
  exit 1
fi

if [[ ! -f "$CLI_PACKAGE_JSON" ]]; then
  echo "Missing CLI package metadata: $CLI_PACKAGE_JSON"
  exit 1
fi

extract_manifest_array() {
  local array_name="$1"
  awk "/export const ${array_name} = \\[/,/\\] as const;/" "$MANIFEST_PATH" \
    | rg -o '"[^"]+"' \
    | tr -d '"'
}

DOC_COMMAND_FILES=(
  "$ROOT_DIR/docs/cli/commands.mdx"
  "$ROOT_DIR/docs/developers/commands.mdx"
  "$ROOT_DIR/docs/self-hosting/cli-setup.mdx"
  "$ROOT_DIR/apps/web/src/app/(landing)/install/InstallPageClient.tsx"
)

INSTALL_GUIDE_FILES=(
  "$ROOT_DIR/docs/cli/installation.mdx"
  "$ROOT_DIR/docs/developers/development-setup.mdx"
  "$ROOT_DIR/docs/self-hosting/overview.mdx"
  "$ROOT_DIR/docs/self-hosting/cli-setup.mdx"
  "$ROOT_DIR/docs/self-hosting/docker-setup.mdx"
  "$ROOT_DIR/apps/web/src/app/(landing)/install/InstallPageClient.tsx"
)

FAIL=0

REQUIRED_NODE_MAJOR="$(node -e "const pkg=require(process.argv[1]); const engine=pkg.engines?.node || ''; const m=engine.match(/\\d+/); if(!m){process.exit(2)}; process.stdout.write(m[0]);" "$CLI_PACKAGE_JSON")"

mapfile -t REQUIRED_DOC_COMMANDS < <(extract_manifest_array "REQUIRED_DOC_COMMANDS")
mapfile -t REQUIRED_INSTALL_COMMANDS < <(extract_manifest_array "REQUIRED_INSTALL_COMMANDS")

for file in "${DOC_COMMAND_FILES[@]}"; do
  for command in "${REQUIRED_DOC_COMMANDS[@]}"; do
    if ! rg -F --quiet "$command" "$file"; then
      echo "Missing command '$command' in $file"
      FAIL=1
    fi
  done
done

for file in "${INSTALL_GUIDE_FILES[@]}"; do
  for install_cmd in "${REQUIRED_INSTALL_COMMANDS[@]}"; do
    if ! rg -F --quiet "$install_cmd" "$file"; then
      echo "Missing install command '$install_cmd' in $file"
      FAIL=1
    fi
  done
done

VERSION_MATCH_FILES=(
  "$ROOT_DIR/README.md"
  "$ROOT_DIR/docs/cli/installation.mdx"
  "$ROOT_DIR/docs/self-hosting/overview.mdx"
)

for file in "${VERSION_MATCH_FILES[@]}"; do
  if ! rg --quiet "Node\\.js.*${REQUIRED_NODE_MAJOR}\\+" "$file"; then
    echo "Missing Node.js ${REQUIRED_NODE_MAJOR}+ requirement in $file"
    FAIL=1
  fi
done

FORBIDDEN_PATTERNS=(
  "@heygaia/cli@latest"
  "npx @heygaia/cli"
  "heygaia.io/install.sh"
)

CHECK_FILES=(
  "$ROOT_DIR/README.md"
  "$ROOT_DIR/docs"
  "$ROOT_DIR/apps/web/src/app/(landing)/install/InstallPageClient.tsx"
)

for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
  if rg -F --quiet "$pattern" "${CHECK_FILES[@]}"; then
    echo "Forbidden pattern '$pattern' detected in docs/frontend"
    FAIL=1
  fi
done

if [[ "$FAIL" -ne 0 ]]; then
  echo "CLI docs/frontend validation failed."
  exit 1
fi

echo "CLI docs/frontend validation passed."
