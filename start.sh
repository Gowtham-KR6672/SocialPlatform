#!/usr/bin/env bash
# ============================================================
#  Social Media Production Dashboard - Version 23  (macOS/Linux)
# ============================================================
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] Python 3 not found. Install it from https://www.python.org/downloads/"
  exit 1
fi

if ! python3 -c "import flask, docx, fpdf" >/dev/null 2>&1; then
  echo "Installing required packages..."
  python3 -m pip install --quiet -r requirements.txt
fi

# start the AI Model engine + load its model in the background if installed
if command -v ollama >/dev/null 2>&1; then
  echo "Starting the AI Model engine in the background..."
  ( ollama serve >/dev/null 2>&1 & sleep 3; ollama pull qwen3-vl:8b >/dev/null 2>&1; ) &
else
  echo "[i] AI Model not found - AI features will use the built-in fallback."
fi

echo "Starting the dashboard at http://127.0.0.1:5000"
( sleep 1; (command -v open >/dev/null && open http://127.0.0.1:5000) || \
  (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:5000) ) &
python3 app.py
