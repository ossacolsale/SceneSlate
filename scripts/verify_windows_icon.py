"""Verify that a Windows EXE embeds *SceneSlate's actual icon*, not Python's.

Usage: python scripts/verify_windows_icon.py dist/SceneSlate-v3.9.0.exe sceneslate_logo.ico
Install pefile first: python -m pip install pefile
"""
from __future__ import annotations

from pathlib import Path
import struct
import sys

import pefile


def icon_payloads(ico: Path) -> set[bytes]:
    raw = ico.read_bytes()
    if len(raw) < 6 or struct.unpack_from('<HH', raw, 0) != (0, 1):
        raise ValueError('Invalid ICO header')
    count = struct.unpack_from('<H', raw, 4)[0]
    if count < 4:
        raise ValueError('SceneSlate icon should contain multiple sizes')
    blobs = set()
    for i in range(count):
        at = 6 + 16 * i
        if at + 16 > len(raw):
            raise ValueError('Truncated ICO directory')
        width, height, colors, reserved, planes, bits, length, offset = struct.unpack_from(
            '<BBBBHHII', raw, at)
        if length < 40 or offset + length > len(raw):
            raise ValueError('Invalid ICO image reference')
        blobs.add(raw[offset:offset + length])
    return blobs


def check(executable: Path, ico: Path) -> tuple[int, int]:
    expected = icon_payloads(ico)
    pe = pefile.PE(str(executable), fast_load=False)
    try:
        icon_groups = 0
        embedded = []
        for entry in getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', []).entries:
            if entry.id == 14:
                icon_groups += len(entry.directory.entries)
            if entry.id != 3:
                continue
            for group in entry.directory.entries:
                for item in group.directory.entries:
                    data = item.data.struct
                    embedded.append(pe.get_data(data.OffsetToData, data.Size))
        if icon_groups < 1:
            raise AssertionError('EXE has no Windows RT_GROUP_ICON resource')
        matches = sum(blob in expected for blob in embedded)
        if matches < 4:
            raise AssertionError(f'EXE contains only {matches} SceneSlate icon images: expected >= 4')
        return icon_groups, matches
    finally:
        pe.close()


if __name__ == '__main__':
    groups, matches = check(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f'Verified SceneSlate EXE icon: {groups} group(s), {matches} matching images')
