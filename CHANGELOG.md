# Changelog

## 3.8.0 — Review ergonomics and filtering

- Windows executable icon included in published binaries.
- Sync Editor undo/redo and stoppable continuous playback across the whole camera recording using bounded chunks.
- Review counter ignores intentional one-sided takes.
- Combinable sync-status and take-presence filters, including SINGLE on mixed subtrees.
- Collapsible descriptions/notes panel with persistent state.
- Inline link destination summaries in the scene tree.
- Improved high-confidence waveform consensus while retaining ambiguity checks.


## 3.7.0 — Multiresolution audio synchronization

- Replaced single global low-rate peak matching with a multi-stage search: waveform correlation, log-amplitude envelope, high-resolution window consensus and partially whitened GCC-PHAT when NumPy is available.
- Refined automatic offset resolution to 0.125 ms before optional sub-sample interpolation; included protection against repetitive material, polarity reversal, quiet passages and conflicting independent windows.
- Added adaptive high-energy verification windows to reduce false `REVIEW` due to speech pauses, and preserved `REVIEW` when multiple plausible offsets or drift exist.
- Added sync diagnostics and explicit FCP7 XML quantization warnings: at 25 fps audio in-points are rounded to 40-ms frames, which is a separate limitation from waveform precision.
- Automatically reanalyze older non-manual synchronization records, while retaining manually verified matches and the original media files.
- Bundled optional NumPy acceleration in standalone release executables; included tests for real AAC media, <5-ms alignment, unrelated tracks, repetitive content and the pure-standard-library fallback.

## 3.6.0 — Logo, take cascading and linked containers

- Added a new SceneSlate logo asset (`sceneslate_logo.png`) and wired it into the desktop UI as the window/app branding.
- Added take-number cascading: when a take number is edited manually, later conflicting take numbers shift upward coherently instead of blocking the edit.
- Added link groups for scenes, shots and sub-shots. Linked items of the same level mirror descriptions and take-level changes automatically.
- Added a **Links… / Collegamenti…** management dialog and tree indicators (`⇄`) so linked items can be selected or unlinked from any member.
- Pasted content no longer carries link-group metadata into the destination.

## 3.5.0 — Precision manual synchronization editor

- Added a bilingual, modal editor with stacked camera and recorder waveforms, pan/zoom, draggable external-audio offset, direct seconds input and 1/10/100 ms plus 1-second nudges.
- Added non-destructive stereo listening previews with simultaneous left-camera/right-recorder monitoring, mixed audio or independent source audition.
- Added explicit manual confirmation (`method: manual`, `manual_verified: true`), source fingerprint checks and protection against background workers overwriting approved offsets.
- Manual OK uses existing take statuses, filters and XML exports; requires no schema migration and no extra Python packages. FFmpeg/ffprobe remain necessary for decoding; a WAV player is required on Linux.
- Added integration, persistence, UI and signed-offset preview tests. The FCP7 XML interchange remains frame-based, even though manually stored offsets are millisecond-precise.

## 3.4 — Opt-in FFmpeg setup on Windows

- Consent-based user-local FFmpeg/ffprobe installation from the Windows builds provider linked by ffmpeg.org, after matching its published SHA-256 checksum.
- Non-blocking download and extraction with a progress dialog and cancellation; installation requires no administrator rights or changes to PATH.
- Per-user `Do not ask again` preference; the setup prompt is shown at subsequent launches when tools are missing unless disabled, with a recovery command under Tools.
- Windows-managed FFmpeg is found automatically; after installation, missing-dependency KO synchronization results are automatically retried.
- Installer works with the existing English/Italian UI, including translated setup and progress messages.
- Offline installer tests cover integrity, cancellation, missing members, settings persistence, and recovery, without network access.

## 3.3 — Waveform sync and non-destructive review timelines

- Background audio synchronization for explicitly paired files using embedded camera audio versus external sound via FFmpeg, without modifying media.
- Per-take waveform offset, confidence score, fingerprint, diagnostics, and conservative OK / REVIEW / KO / PENDING / SINGLE statuses.
- Sync status columns for takes and the scene / shot / sub-shot hierarchy, with an unsynced-only filter and per-take retry/details controls.
- Four selectable exports: existing CSV metadata/reports, individual take FCP7 XML sequences, shot review sequences, and scene review sequences.
- Audio is included in XML only when its waveform match is confidently OK; otherwise no invented alignment and a clear report warning.
- Catalog schema 5; compatibility with schema 1–4 and upgrade backups.
- Regression tests for waveform lag direction, silence/unrelated audio rejection, fallback without NumPy, real FFmpeg media, XML in/out points, migration and GUI statuses.

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
