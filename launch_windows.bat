@echo off
cd /d "%~dp0"
REM Troubleshooting launcher. Prefer SceneSlate.vbs for a console-free launch.
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 "%~dp0scene_slate.pyw" %*
  exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0scene_slate.pyw" %*
  exit /b 0
)
echo Python GUI launcher not found. Install Python 3 with Tkinter from python.org.
pause
