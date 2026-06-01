@echo off
cd /d "%~dp0"
echo Starting S/MIME Google Workspace Loader GUI...
.\venv\Scripts\python.exe gui_sync.py
set EXIT_CODE=%errorlevel%
if %EXIT_CODE% neq 0 (
    echo.
    echo [ERROR] GUI exited with error code: %EXIT_CODE%
    echo Check that your venv is set up: .\venv\Scripts\pip install -r requirements.txt
) else (
    echo.
    echo GUI closed normally.
)
pause
