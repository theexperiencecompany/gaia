#!/bin/bash
# GAIA CLI Testing Script

set -e

CLI_DIR="/Users/aryan/Projects/GAIA/gaia-light-mode/packages/cli"
REPO_ROOT="/Users/aryan/Projects/GAIA/gaia-light-mode"

echo "🧪 GAIA CLI Testing Suite"
echo "=========================="
echo ""

# Test 1: Version and Help
echo "✓ Test 1: Version and Help Commands"
cd "$REPO_ROOT"
./packages/cli/dist/index.js --version
./packages/cli/dist/index.js --help
echo ""

# Test 2: Individual Command Help
echo "✓ Test 2: Individual Command Help"
./packages/cli/dist/index.js init --help
./packages/cli/dist/index.js setup --help
./packages/cli/dist/index.js status --help
./packages/cli/dist/index.js start --help
./packages/cli/dist/index.js stop --help
echo ""

# Test 3: Status Command (non-interactive)
echo "✓ Test 3: Status Command"
echo "This will check the health of running services..."
echo "Press Ctrl+C if it hangs"
echo ""
# Run status but timeout after 5 seconds if it hangs
timeout 10 ./packages/cli/dist/index.js status || echo "Status check completed or timed out"
echo ""

# Test 4: Dev Mode
echo "✓ Test 4: Dev Mode Test"
GAIA_CLI_DEV=true bun "$CLI_DIR/src/index.ts" --version
echo ""

echo "=========================="
echo "✅ Basic tests completed!"
echo ""
echo "📝 Manual Testing Steps:"
echo ""
echo "1. Test Setup Command (interactive):"
echo "   cd /tmp"
echo "   git clone https://github.com/heygaia/gaia.git test-gaia"
echo "   cd test-gaia"
echo "   $REPO_ROOT/packages/cli/dist/index.js setup"
echo ""
echo "2. Test Init Command (creates new clone):"
echo "   cd /tmp"
echo "   $REPO_ROOT/packages/cli/dist/index.js init"
echo ""
echo "3. Test Install Script:"
echo "   # View the install script"
echo "   cat $CLI_DIR/install.sh"
echo "   # Or test from web (after deploying)"
echo "   curl -fsSL https://heygaia.io/install.sh"
echo ""
echo "4. Test npm pack:"
echo "   cd $CLI_DIR"
echo "   npm pack"
echo "   # Install from tarball"
echo "   npm install -g heygaia-cli-*.tgz"
echo "   gaia --help"
echo ""
