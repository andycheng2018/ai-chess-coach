#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "== AI Chess Coach setup =="

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install Python 3.10+ and rerun this script."
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required.")
print("Python", sys.version.split()[0])
PY

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js + npm are required. Install Node 20+ and rerun this script."
  exit 1
fi

node - <<'JS'
const [major, minor] = process.versions.node.split('.').map(Number);
const supported = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22;
if (!supported) {
  console.error('Vite requires Node 20.19+ or 22.12+. Current:', process.versions.node);
  process.exit(1);
}
console.log('Node', process.versions.node);
JS

if ! command -v stockfish >/dev/null 2>&1 && [[ ! -x /opt/homebrew/bin/stockfish ]] && [[ ! -x /usr/local/bin/stockfish ]]; then
  echo
  echo "Stockfish is required. On macOS with Homebrew run:"
  echo "  brew install stockfish"
  echo "Then rerun ./setup_mac.sh"
  exit 1
fi

echo "Creating Python environment..."
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo "Installing web dependencies..."
if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo
  echo "Created .env. Add LICHESS_BOT_TOKEN before starting the app."
fi

echo
echo "Setup complete."
echo "1) Edit .env and add the bot token."
echo "2) Run: ./dev.sh"
