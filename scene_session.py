"""Durable, machine-local window/session state (separate from footage catalogs)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


def config_dir():
    override = os.environ.get('SCENESLATE_CONFIG_DIR')
    if override:
        return Path(override).expanduser()
    # Always store user preferences outside the application directory.
    # Replacing the application folder never deletes preferences or drafts.
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA', str(Path.home() / 'AppData' / 'Roaming'))) / 'SceneSlate'
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'sceneslate'


def read_state(directory=None):
    file = Path(directory or config_dir()) / 'session.json'
    try:
        with file.open(encoding='utf-8') as stream:
            state = json.load(stream)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _atomic_json(file, document):
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=file.parent,
                                         prefix='.sceneslate-', suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, file)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def write_state(state, directory=None):
    _atomic_json(Path(directory or config_dir()) / 'session.json', state)


def draft_file(directory=None):
    return Path(directory or config_dir()) / 'autosaved_draft.sceneslate.json'


def legacy_draft_file(directory=None):
    # Used by versions through 3.1 for non-destructive recovery.
    return Path(directory or config_dir()) / 'bozza_autosalvata.sceneslate.json'
