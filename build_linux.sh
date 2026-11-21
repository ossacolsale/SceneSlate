#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
python3 -m pip install --upgrade pyinstaller
python3 -m PyInstaller --noconfirm --clean --onefile --windowed --name SceneSlate --paths . scene_slate.py
printf 'Creato: dist/SceneSlate\n'
