#!/bin/bash
# Legacy setup script - now handled by mise
# Run: mise setup

echo "⚠️  This script is deprecated. Please use mise instead:"
echo ""
echo "  mise setup"
echo ""
echo "Or install mise first if you haven't:"
echo "  curl https://mise.run | sh"
echo ""
echo "Redirecting to mise setup..."
echo ""

# Check if mise is installed
if ! command -v mise &> /dev/null; then
    echo "❌ mise is not installed. Install it first:"
    echo "   curl https://mise.run | sh"
    echo ""
    echo "Or visit: https://mise.jdx.dev/getting-started.html"
    exit 1
fi

# Run mise setup
mise setup
