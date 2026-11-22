@echo off
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller numpy || exit /b 1
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name SceneSlate --paths . --icon sceneslate_logo.ico --add-data "sceneslate_icon.png;." --add-data "sceneslate_logo.ico;." scene_slate.pyw
if errorlevel 1 pause
