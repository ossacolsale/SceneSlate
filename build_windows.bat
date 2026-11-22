@echo off
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller numpy pefile || exit /b 1
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name SceneSlate-v3.9.0 --paths . --icon sceneslate_logo.ico --add-data "sceneslate_icon.png;." --add-data "sceneslate_logo.ico;." scene_slate.pyw
if errorlevel 1 pause

py -3 scripts\verify_windows_icon.py "dist\SceneSlate-v3.9.0.exe" sceneslate_logo.ico
if errorlevel 1 pause
