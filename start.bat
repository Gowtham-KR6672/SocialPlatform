@echo off
setlocal enableextensions
REM ============================================================
REM  Social Media Production Dashboard - Version 23  (Windows)
REM ============================================================
cd /d "%~dp0"

echo.
echo   Social Media Production Dashboard - Version 23
echo   =============================================
echo.

REM -- locate Python even if it is NOT on PATH (PATH, py launcher, common dirs)
set "PYEXE="
call :FINDPY
if not defined PYEXE (
    echo   [!] Python was not found on this PC.
    echo       Install Python 3 from https://www.python.org/downloads/
    echo       ^(tick "Add Python to PATH" during install^), then run this file again.
    echo.
    pause
    exit /b 1
)
echo   Using Python: %PYEXE%

REM -- ensure required packages (verify the EXACT imports the app uses) ------
"%PYEXE%" -c "import flask; from docx import Document; from fpdf import FPDF" >nul 2>nul
if errorlevel 1 (
    echo   Installing required packages...
    "%PYEXE%" -m pip install --quiet -r requirements.txt
    REM the old, broken 'docx' package clashes with python-docx (both import as 'docx').
    REM if Word support still fails, remove the clashing package and reinstall python-docx.
    "%PYEXE%" -c "from docx import Document" >nul 2>nul
    if errorlevel 1 (
        echo   Repairing Word support ^(python-docx^)...
        "%PYEXE%" -m pip uninstall -y docx >nul 2>nul
        "%PYEXE%" -m pip install --quiet --force-reinstall python-docx
    )
)

REM -- locate the AI Model (Ollama) even if it is not on PATH ---------------
set "OLLAMA_EXE="
where ollama >nul 2>nul && set "OLLAMA_EXE=ollama"
if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "%ProgramW6432%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramW6432%\Ollama\ollama.exe"

REM -- start the AI Model engine + load its model in the background ---------
if not defined OLLAMA_EXE (
    echo   [i] AI Model not found - AI features will use the built-in fallback.
    echo       Install the AI Model from the Setup window, then run this file again.
) else (
    echo   Starting the AI Model engine in the background...
    start "AI Model Engine" /min cmd /c ""%OLLAMA_EXE%" serve"
    REM give the engine a moment to come up
    timeout /t 3 >nul
    echo   Loading the AI Model ^(runs in the background^)...
    start "AI Model" /min cmd /c ""%OLLAMA_EXE%" pull qwen3-vl:8b ^&^& "%OLLAMA_EXE%" run qwen3-vl:8b """
)

echo.
echo   Starting the dashboard...
echo   A browser window will open at http://127.0.0.1:5000
echo   ^(Keep this window open while you use the dashboard. Close it to stop.^)
echo.

start "" http://127.0.0.1:5000
"%PYEXE%" app.py

pause
exit /b 0

REM ======================================================================
REM  :FINDPY  -- sets PYEXE to a working Python (single token or full path)
REM ======================================================================
:FINDPY
REM 1) python / python3 already on PATH that actually runs
python  --version >nul 2>nul && ( set "PYEXE=python"  & goto :eof )
python3 --version >nul 2>nul && ( set "PYEXE=python3" & goto :eof )
REM 2) the Windows Python launcher (installed with most python.org builds)
py --version >nul 2>nul && ( set "PYEXE=py" & goto :eof )
REM 3) common per-user install folders
if not defined PYEXE for /d %%G in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%G\python.exe" set "PYEXE=%%G\python.exe"
if defined PYEXE goto :eof
REM 4) common all-users install folders
if not defined PYEXE for /d %%G in ("%ProgramFiles%\Python3*") do if exist "%%G\python.exe" set "PYEXE=%%G\python.exe"
if defined PYEXE goto :eof
if not defined PYEXE for /d %%G in ("%ProgramFiles(x86)%\Python3*") do if exist "%%G\python.exe" set "PYEXE=%%G\python.exe"
if defined PYEXE goto :eof
REM 5) classic root installs
for %%D in ("C:\Python313\python.exe" "C:\Python312\python.exe" "C:\Python311\python.exe" "C:\Python310\python.exe" "C:\Python39\python.exe") do if not defined PYEXE if exist %%D set "PYEXE=%%~D"
goto :eof
