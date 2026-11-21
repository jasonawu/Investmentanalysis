@echo off
REM Double-click this file on Windows to start the Investment Dashboard.
cd /d "%~dp0"
echo Starting the Investment Dashboard...
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python is not installed. Install it from https://www.python.org/downloads/
  echo IMPORTANT: on the first installer screen, tick "Add python.exe to PATH".
  echo Then double-click this file again.
  pause
  exit /b 1
)
REM First run only: create a private Python environment for this app.
if not exist .venv (
  echo First-time setup: this takes a few minutes...
  python -m venv .venv
  if errorlevel 1 ( echo Setup failed. & pause & exit /b 1 )
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 ( echo Installing packages failed. Check your internet connection. & pause & exit /b 1 )
REM Skip Streamlit's one-time "enter your email" question.
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
  echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"
)
echo.
echo The dashboard will open in your web browser. Keep this window open while you use it.
echo To stop the dashboard, close this window.
python -m streamlit run app.py --browser.gatherUsageStats false
pause
