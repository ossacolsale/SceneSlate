#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
python3 -m pip install --upgrade pyinstaller numpy
python3 -m PyInstaller --noconfirm --clean --onefile --windowed --name SceneSlate --paths . --add-data "sceneslate_icon.png:." --add-data "sceneslate_logo.ico:." scene_slate.py
printf 'Created: dist/SceneSlate\n'
