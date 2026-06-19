#!/usr/bin/env bash
set -e

# ── Fennec local dev script ──────────────────────────────────
# Usage:
#   ./dev.sh          → scrape fresh news.json then start Vite
#   ./dev.sh --skip   → skip scraping, just start Vite (uses existing news.json)
#   ./dev.sh --setup  → install all dependencies only

SKIP_SCRAPE=false
SETUP_ONLY=false

for arg in "$@"; do
  case $arg in
    --skip)   SKIP_SCRAPE=true ;;
    --setup)  SETUP_ONLY=true ;;
  esac
done

echo ""
echo "🦊 Fennec Dev Environment"
echo "──────────────────────────"

# ── 1. Check for .env ────────────────────────────────────────
if [ ! -f ".env" ] && [ "$SKIP_SCRAPE" = false ]; then
  echo ""
  echo "⚠️  No .env file found. Creating template..."
  cat > .env << 'EOF'
# Get your key from https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key_here
EOF
  echo "   → .env created. Add your GEMINI_API_KEY and re-run."
  echo ""
  exit 1
fi

# ── 2. Install Python deps ───────────────────────────────────
echo ""
echo "📦 Checking Python dependencies..."
if ! python3 -c "import google.genai, langgraph, pydantic" 2>/dev/null; then
  echo "   → Installing from requirements.txt..."
  pip3 install -r requirements.txt --quiet
else
  echo "   ✓ Python deps already installed"
fi

# ── 3. Install Node deps ─────────────────────────────────────
echo ""
echo "📦 Checking Node dependencies..."
if [ ! -d "node_modules" ]; then
  echo "   → Running npm install..."
  npm install --silent
else
  echo "   ✓ node_modules present"
fi

if [ "$SETUP_ONLY" = true ]; then
  echo ""
  echo "✅ Setup complete. Run ./dev.sh to start."
  exit 0
fi

# ── 4. Run scraper ───────────────────────────────────────────
if [ "$SKIP_SCRAPE" = false ]; then
  echo ""
  echo "🕷️  Running scraper..."
  echo "──────────────────────────"
  python3 scrape.py
  echo "──────────────────────────"
fi

# ── 5. Start Vite ────────────────────────────────────────────
echo ""
echo "🚀 Starting Vite dev server..."
echo "   → http://localhost:5173"
echo ""
npm run dev
