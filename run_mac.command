#!/bin/bash
# Double-click this file on a Mac to start the Investment Dashboard.
cd "$(dirname "$0")"
echo "Starting the Investment Dashboard..."
if ! command -v python3 >/dev/null 2>&1; then
  echo ""
  echo "Python is not installed. Install it from https://www.python.org/downloads/ and then double-click this file again."
  read -p "Press Enter to close."
  exit 1
fi
# First run only: create a private Python environment for this app.
if [ ! -d .venv ]; then
  echo "First-time setup: this takes a few minutes..."
  python3 -m venv .venv || { read -p "Setup failed. Press Enter to close."; exit 1; }
fi
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt || { read -p "Installing packages failed. Check your internet connection. Press Enter to close."; exit 1; }
# Skip Streamlit's one-time "enter your email" question.
mkdir -p ~/.streamlit
[ -f ~/.streamlit/credentials.toml ] || printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml
echo ""
echo "The dashboard will open in your web browser. Keep this window open while you use it."
echo "To stop the dashboard, close this window."
python -m streamlit run app.py --browser.gatherUsageStats false
