@echo off
cd /d "%~dp0"
rem Fallback console launcher for troubleshooting; prefer SceneSlate.vbs.
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
echo Python GUI non trovato. Installa Python 3 con Tkinter da python.org.
pause
