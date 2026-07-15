@echo off
REM Launch dashboard strictly inside the project venv. Avoids the situation
REM where Streamlit's file-watcher fork lands on a different Python (the
REM machine's global install lacks streamlit/akshare/yaml, which silently
REM disabled the news_data import in the dashboard).

setlocal
set ROOT=%~dp0
set ROOT=%ROOT:~0,-1%
set VENV=%ROOT%\venvs\finance-agent-engineering
set PYTHONPATH=%VENV%\Lib\site-packages;%ROOT%\backend;%ROOT%\frontend
set VIRTUAL_ENV=%VENV%
set PATH=%VENV%\Scripts;%PATH%
set PYTHONIOENCODING=utf-8
REM Disable the file-watcher: in some Windows setups it forks to py.exe / a
REM different Python and reloads the app under that interpreter, which then
REM lacks the venv site-packages. Restart manually after edits instead.
set STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

cd /d "%ROOT%"

if not exist "%VENV%\Scripts\python.exe" (
    echo Optional Streamlit debug console environment not found:
    echo   %VENV%
    echo Create it and install the complete optional console environment:
    echo   python -m venv "%VENV%"
    echo   "%VENV%\Scripts\python.exe" -m pip install -r requirements-streamlit.txt
    exit /b 1
)

"%VENV%\Scripts\python.exe" -c "import streamlit, plotly" >nul 2>nul
if errorlevel 1 (
    echo Streamlit debug console dependencies are not installed.
    echo Install with:
    echo   "%VENV%\Scripts\python.exe" -m pip install -r requirements-streamlit.txt
    echo Or for an editable package install:
    echo   "%VENV%\Scripts\python.exe" -m pip install -e ".[streamlit]"
    exit /b 1
)

echo Using python: %VENV%\Scripts\python.exe
echo Optional debug console dependencies: requirements-streamlit.txt
echo File-watcher disabled. Stop with Ctrl+C and rerun this .bat after code edits.

"%VENV%\Scripts\python.exe" -m streamlit run frontend\dashboard.py ^
    --server.port 8501 ^
    --server.headless true ^
    --logger.level info

endlocal
