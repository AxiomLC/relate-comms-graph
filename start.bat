@echo off
REM ============================================================================
REM  relate-comms — start everything
REM
REM  Double-click this file. A console window opens, the server starts, and the
REM  browser opens at http://127.0.0.1:8100.
REM
REM  CLOSING THE WINDOW STOPS THE APP. That is the whole lifecycle: one window,
REM  one process. There is no background service, no tray icon, no autostart.
REM
REM  Nothing here reaches the internet. The server binds 127.0.0.1 only.
REM ============================================================================

setlocal
cd /d "%~dp0"

set PORT=8100
set URL=http://127.0.0.1:%PORT%

echo.
echo   relate-comms
echo   ------------
echo.

REM --- 1. Python present? -----------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
  echo   [X] Python was not found on PATH.
  echo       Install Python 3.11+ and tick "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

REM --- 2. Dependencies present? ----------------------------------------------
REM  Checked by import, not by pip list: an import is what actually matters.
python -c "import fastapi, uvicorn, relate" >nul 2>&1
if errorlevel 1 (
  echo   [X] Dependencies are missing.
  echo.
  echo       Run this once, then start again:
  echo         pip install -e ".[app]"
  echo.
  pause
  exit /b 1
)

REM --- 3. Build the UI --------------------------------------------------------
REM  JSX is source; the browser cannot run it. esbuild compiles app/ui/src/**
REM  into app/static/dist/app.js, and THAT is what the browser loads. So the
REM  build is part of starting the app, not an optional extra.
REM
REM  It runs on EVERY start when npm is present. A timestamp check was tried and
REM  dropped: batch cannot compare file times reliably (dir /o-d sorts within each
REM  pattern group, not globally, and the file-time substitution is empty in some
REM  contexts), and a check that silently fails to fire is worse than no check at
REM  all. esbuild takes about a second, so always building is simpler and correct.
REM
REM  dist/app.js is committed, so a clone with no Node still runs — it just uses
REM  whatever bundle is on disk.
where npm >nul 2>&1
if errorlevel 1 (
  if not exist "app\static\dist\app.js" (
    echo   [X] No npm, and no built UI at app\static\dist\app.js.
    echo       Install Node, or restore that file from git.
    echo.
    pause
    exit /b 1
  )
  echo   [!] npm not found - using the committed UI bundle as-is.
  echo       Edits to app\ui\src will NOT appear until you install Node.
  echo.
) else (
  echo   Building the UI...
  call npm run build
  if errorlevel 1 (
    echo   [X] The UI build failed. See the errors above.
    echo.
    pause
    exit /b 1
  )
)

REM --- 4. Port free? ---------------------------------------------------------
REM  8000 is taken on this machine by another app, which is why this uses 8100.
REM  A stale server from a previous run is the usual cause of a bind failure.
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo   [!] Port %PORT% is already in use.
  echo.
  echo       If this app is already running in another window, use that one.
  echo       Otherwise close whatever holds the port, or run:
  echo         python -m app --port 8110
  echo.
  pause
  exit /b 1
)

REM --- 5. Store present? -----------------------------------------------------
if not exist "store\graph.rl" (
  echo   [!] No graph yet — store\graph.rl does not exist.
  echo       The app will start, but the canvas will be empty.
  echo       Use the Ingest button to bring in an export.
  echo.
)

REM --- 6. Open the browser, then serve ---------------------------------------
REM  The browser is opened first so the window is not blocked while the server
REM  warms up; the page retries its own API calls until the server answers.
start "" "%URL%"

echo   Serving on %URL%
echo   Close this window to stop.
echo.

REM  `python -m app` runs in THIS console. Closing the window kills it, which is
REM  the requested behaviour: one window, one process, no orphans.
REM
REM  NO `--reload`, deliberately. The editor auto-saves every few seconds, so a
REM  watcher restarts the server mid-request while you are still typing — and it
REM  watches the whole repo, so a `pytest` run makes it thrash (one test run took
REM  38 minutes instead of 39 seconds). Restarting is a two-second manual act:
REM  close this window, run start.bat again. The UI bundle is a static file, so a
REM  JS edit only needs `npm run build` and a browser refresh.
python -m app --port %PORT%

REM --- 7. If the server exits on its own, say so and hold the window ---------
echo.
echo   The server stopped.
pause
endlocal
