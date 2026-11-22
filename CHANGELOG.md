# Changelog

## 3.3 — Waveform sync and non-destructive review timelines

- Background audio synchronization for explicitly paired files using embedded camera audio versus external sound via FFmpeg, without modifying media.
- Per-take waveform offset, confidence score, fingerprint, diagnostics, and conservative OK / REVIEW / KO / PENDING / SINGLE statuses.
- Sync status columns for takes and the scene / shot / sub-shot hierarchy, with an unsynced-only filter and per-take retry/details controls.
- Four selectable exports: existing CSV metadata/reports, individual take FCP7 XML sequences, shot review sequences, and scene review sequences.
- Audio is included in XML only when its waveform match is confidently OK; otherwise no invented alignment and a clear report warning.
- Catalog schema 5; compatibility with schema 1–4 and upgrade backups.
- Regression tests for waveform lag direction, silence/unrelated audio rejection, fallback without NumPy, real FFmpeg media, XML in/out points, migration and GUI statuses.

# Changelog

## 3.2 — Bilingual interface and English output naming

- Added runtime **English / Italiano** selection, with English on first launch.
- Stored UI language in the per-user session; the catalog schema is language-independent.
- Translated interface controls, sorting options, prompts, status text and dialog labels.
- Standardized English-only export file names and headers: `full_catalog.csv`, `shot_summary.csv`, `resolve_metadata.csv`, `export_report.txt`.
- Standardized English-only Resolve comments, keywords and export warnings.
- Renamed `avvia_windows.bat` to `launch_windows.bat`, `avvia_linux.sh` to `launch_linux.sh`, and `esempio.sceneslate.json` to `example.sceneslate.json`.
- Renamed unnamed autosave `bozza_autosalvata.sceneslate.json` to `autosaved_draft.sceneslate.json`, with legacy draft recovery preserved.
- Added localization and legacy-compatibility tests. Existing catalog data and media paths remain untouched.
- Normalized Windows junction/8.3 short-path aliases for reliable file matching and relative media path recovery.

## 3.1 — Optional sub-shots, reusing media, notes

- Scene/shot/sub-shot hierarchy; arbitrary sub-shot names.
- Copy/paste catalog content across scene-tree nodes without duplicating media.
- Take-level description and annotation; scene/shot/sub-shot descriptions.
- Sequential take numbers, optional manual overrides.
- Source and build scripts, GitHub Actions tests for Windows and Linux.
