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

## 3.1 — Optional sub-shots, reusing media, notes

- Scene/shot/sub-shot hierarchy; arbitrary sub-shot names.
- Copy/paste catalog content across scene-tree nodes without duplicating media.
- Take-level description and annotation; scene/shot/sub-shot descriptions.
- Sequential take numbers, optional manual overrides.
- Source and build scripts, GitHub Actions tests for Windows and Linux.
