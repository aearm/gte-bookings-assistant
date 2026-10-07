#!/bin/bash
# Mac / Linux setup. Run in Terminal:  bash setup.sh
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 not found. Install it from https://www.python.org/downloads/macos/ first."
  exit 1
fi

echo "Creating Python environment..."
python3 -m venv .venv || exit 1
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt || exit 1
[ -f .env ] || cp .env.example .env
[ -f business_notes.md ] || cp business_notes.example.md business_notes.md
chmod +x run_app.sh 2>/dev/null

echo ""
echo "Done. Now add your Claude API key:  open -e .env"
echo "Then start the app:                  bash run_app.sh"
