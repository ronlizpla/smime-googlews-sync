@echo off
cd /d "%~dp0"
echo Starting S/MIME Google Workspace Loader GUI...
.\venv\Scripts\python.exe gui_sync.py
if %errorlevel% neq 0 (
    echo.
    echo An error occurred while running the GUI.
    pause
)
