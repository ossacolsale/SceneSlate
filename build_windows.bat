@echo off
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || exit /b 1
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name SceneSlate --paths . scene_slate.pyw
if errorlevel 1 pause
