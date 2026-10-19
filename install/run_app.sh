#!/bin/bash
# Mac / Linux: start the app. Run in Terminal, in the app folder:  bash install/run_app.sh
cd "$(dirname "$0")/.." || exit 1
source .venv/bin/activate
streamlit run app.py
