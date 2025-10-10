#!/bin/bash
set -e

# Check if .env files exist
if [ ! -f "backend/.env" ] || [ ! -f "frontend/.env" ]; then
    echo "❌ Environment files not found!"
    echo ""
    echo "Please copy the example environment files first:"
    echo "  cp backend/.env.example backend/.env"
    echo "  cp frontend/.env.example frontend/.env"
    echo ""
    echo "Then configure your environment variables and run this script again."
    exit 1
fi

echo "✅ Environment files found. Continuing with setup..."

# --- Docker Compose ---
echo "Starting Docker services in the background..."
docker-compose up -d

# --- Backend Setup ---
echo "⚙️ Setting up backend..."
cd backend
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    $PYTHON -m venv .venv --upgrade-deps
fi

# Activate venv
if [ -f ".venv/bin/activate" ]; then
    . .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    . .venv/Scripts/activate
else
    echo "Could not find virtual environment activation script."
    exit 1
fi

# Verify Python and pip are working in venv
if ! python -c "import sys; print('Python:', sys.version)" 2>/dev/null; then
    echo "Virtual environment seems corrupted, recreating..."
    cd ..
    rm -rf backend/.venv
    cd backend
    $PYTHON -m venv .venv --upgrade-deps
    if [ -f ".venv/bin/activate" ]; then
        . .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
        . .venv/Scripts/activate
    fi
fi

# Ensure uv is installed
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    # First ensure we have pip
    python -m ensurepip --upgrade 2>/dev/null || echo "ensurepip not available, trying alternative..."
    python -m pip install --upgrade pip || {
        echo "pip installation failed, downloading get-pip.py..."
        curl -sS https://bootstrap.pypa.io/get-pip.py | python
    }
    python -m pip install uv
fi

echo "Installing backend dependencies..."
uv sync
cd ..

# --- Frontend Setup ---
echo "⚙️ Setting up frontend..."
cd frontend
pnpm install
cd ..

# --- Payment Setup ---
echo "💳 Setting up payment plans..."
cd backend
if [ -f ".venv/bin/activate" ]; then
    . .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    . .venv/Scripts/activate
fi

# Check if DODO_PAYMENTS_API_KEY is set
if [ -z "$DODO_PAYMENTS_API_KEY" ]; then
    echo "⚠️  DODO_PAYMENTS_API_KEY not found in environment variables"
    echo "   Payment setup will be skipped. Configure your payment API key and run:"
    echo "   python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>"
else
    echo "   Payment API key found. You can run payment setup manually with:"
    echo "   python scripts/payment_setup.py --monthly-product-id <id> --yearly-product-id <id>"
fi
cd ..

# --- Seed Models ---
echo "🤖 Seeding AI models..."
cd backend
if [ -f ".venv/bin/activate" ]; then
    . .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    . .venv/Scripts/activate
fi

echo "   Running model seeding script..."
python scripts/seed_models.py --force
cd ..

# --- Done ---
echo ""
echo "Setup complete!"
echo ""
echo "🔑 IMPORTANT: Configure your environment variables"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Before running GAIA, you need to configure your API keys and environment variables."
echo ""
echo "📝 Configuration files created:"
echo "   • backend/.env  - Backend configuration (API keys, database settings)"
echo "   • frontend/.env - Frontend configuration (API URLs, tokens)"
echo ""
echo "📚 For detailed setup instructions, visit:"
echo "   Environment Variables: https://docs.heygaia.io/configuration/environment-variables"
echo ""
echo "💡 Quick start: At minimum, you'll need to configure:"
echo "   • OpenAI API key (or other AI model APIs)"
echo "   • Google OAuth credentials (if using authentication)"
echo "   • Infisical credentials (recommended for production)"
echo ""
echo "After configuring your environment variables, you can start the application!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
