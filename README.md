# SceneSlate 3.4

SceneSlate is a **cross-platform footage catalog** written in Python 3 and Tkinter. Its interface is available in **English and Italian**. A new installation starts in **English**; change the language using the **Language / Lingua** selector in the top toolbar. The preference survives restarts and upgrades, and switching languages does **not** rename files, modify a catalog or reset the scene selection.

Footage is organized as **scene → shot → optional sub-shot → take**. Every take has an optional video reference and an optional audio reference, each with independent ratings (`B` good, `R` reserve, `S` reject). Takes can have descriptions and annotations; scenes, shots and sub-shots have optional descriptions. **Original media files are never renamed, moved, deleted or duplicated.** When a video/audio pair is complete, SceneSlate attempts **background waveform synchronization** if FFmpeg is installed; the alignment metadata is stored per take, never written into the media.

## Automatic synchronization and optional FFmpeg setup

**Windows:** If FFmpeg and ffprobe are missing when SceneSlate starts, it offers an optional **Download and install** action. Nothing is downloaded without your explicit confirmation. The install uses the Windows FFmpeg essentials ZIP from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), a Windows build provider linked by [ffmpeg.org](https://ffmpeg.org/download.html). The vendor's published SHA-256 checksum is checked before extracting **only** `ffmpeg.exe` and `ffprobe.exe` into `%APPDATA%\SceneSlate\tools\ffmpeg\` (by default). No administrator rights, PATH changes or modifications to source media are required. The downloaded ZIP is deleted after successful installation.

Choose **Later** to postpone the installation; SceneSlate asks again at the next launch while the executables are missing. Tick **Do not ask again at startup** to suppress reminders. You can reopen the setup at any time through **Tools → FFmpeg setup…** (Italian: **Strumenti → Configurazione FFmpeg…**) or re-enable **Tools → Ask at startup when FFmpeg is missing**. An existing system installation on PATH is used without downloading another copy. After provisioning, SceneSlate retries any synchronization marked KO solely because FFmpeg/ffprobe were missing.

**Linux:** Install with your distribution's package manager, for example `sudo apt install ffmpeg`. SceneSlate can remind you that it is missing, but does not automatically install system packages on Linux. You may also explicitly set `SCENESLATE_FFMPEG` and `SCENESLATE_FFPROBE`.

The Python standard library is sufficient; **NumPy is optional** and speeds up correlation. The fallback FFT implementation works without NumPy. Standalone PyInstaller builds **do not bundle FFmpeg**. The optional Windows installer is the only automatic network operation, and only runs after approval.

When both the camera video and a separate sound recording have been assigned to one take, the background worker inspects the video for an audio stream. If one exists, it analyzes up to the first **90 seconds** of each recording, searching offsets of up to **±60 seconds**. An overlap of at least **8 seconds** is required. This supports ordinary double-system recording where a camera recorded scratch audio as well; it is not timecode synchronization and cannot detect time drift reliably.

Statuses are intentionally conservative:

| Status | Meaning | XML result |
|---|---|---|
| `✓ OK` | Strong, reasonably unambiguous waveform match | Export aligned original video and external audio |
| `◐ REVIEW` | Plausible but weak or ambiguous match | Export video alone; check manually and retry if necessary |
| `✕ KO` | No usable match, camera has no embedded audio, missing media/FFmpeg or failed analysis | Export video alone (if readable) |
| `… WAIT` | Waiting/working, or source files changed after a previous successful match | Export video alone |
| `— SINGLE` | Only one of video/audio was assigned | Export the existing medium |
| `—` | No takes | Nothing exported |

A **SYNC** column next to each take and a separate SYNC column in the scene tree summarize all child statuses. A parent is `OK` only when **every take in its subtree** is successfully synchronized. The **Unsynced only / Solo non sincronizzati** filter shows any shot/sub-shot containing a non-OK take, including incomplete takes. Use **↻ Sync** to retry the selected take after addressing any issue and **Sync details** to see the measured offset, correlation score and diagnostic error. Raw statuses and the offset are preserved in JSON and `full_catalog.csv`.

> Matching is heuristic: **always verify important takes by listening**, especially with music, repeated dialogue, noise, sync drift, or timecode mismatches. A high correlation is not a professional sync guarantee. No video or audio is rendered or altered.

## Starting the application

| Platform | Recommended launcher | Requirements |
|---|---|---|
| Windows | Double-click `SceneSlate.vbs` or `scene_slate.pyw` | Python 3.10+ with Tkinter and `.pyw` file association |
| Linux | Open `SceneSlate.desktop` from a file manager, or run `./launch_linux.sh` | Python 3.10+ with Tkinter (`python3-tk` on Ubuntu/Debian) |

The optional `SceneSlate.pyz` contains the Python sources as a single portable Python zip application (`python SceneSlate.pyz`, with Python 3 installed); on Windows FFmpeg/ffprobe can be installed using the new in-app wizard.

The Windows `.vbs` entry point uses `pythonw.exe` (via `.pyw` file association) so it does not leave a Command Prompt window open. For troubleshooting use `launch_windows.bat`. The Linux desktop shortcut uses `Terminal=false`; depending on your file manager, it may require marking it executable or trusted. To launch in a terminal, run `python3 scene_slate.py`.

This source package is *not* a precompiled Windows executable. To build an independent executable on the target OS, use `build_windows.bat` or `build_linux.sh` after installing PyInstaller. The GitHub Actions workflow is **release-only**: it tests/builds for Windows and Linux only when a GitHub Release is published, then attaches the binaries directly to that Release. It does **not** store Actions workflow artifacts.

## Publishing releases

Normal pushes and pull requests do not run GitHub Actions. To build distributable binaries:

1. Make sure the intended version is committed on `main`.
2. Create a new version tag (for example `v3.4.0`) pointing to that commit.
3. In **GitHub → Releases → Draft a new release**, choose the tag and **Publish release**.
4. The `Publish SceneSlate release` workflow will run tests and PyInstaller on the standard Windows and Ubuntu hosted runners.
5. If successful, the release receives `SceneSlate-<tag>-windows-x64.zip` and `SceneSlate-<tag>-linux-x64.tar.gz` directly as Release assets.

No `actions/upload-artifact` step or Actions cache is used. GitHub Releases are the intended home for downloadable builds, while GitHub Actions logs remain available according to GitHub's retention policy. This setup is designed for **public repositories using standard GitHub-hosted runners**; verify your own GitHub billing settings before changing repository visibility or runner type.

**Release prerequisites:** `gh release upload` uses the ephemeral `GITHUB_TOKEN` with `contents: write`. Building does not bundle FFmpeg/ffprobe; on Windows the in-app wizard can install them into the user profile after approval. Because this workflow triggers on publishing a Release, publish only after the tagged code is ready to distribute.

## Typical workflow

1. Browse the original video and audio folders. Each file browser supports name/date sorting, searching, subfolder scanning, highlighting unassigned files, and filtering to unassigned files only.
2. Create scenes and shots (positive integers), with optional sub-shots named `A`, `B`, `Detail`, `Wide shot`, or any other nonempty name. Takes may be attached directly to a shot even when sub-shots exist.
3. Drag a video or audio onto a shot/sub-shot to create a take. Drag the other kind onto the same take row to explicitly pair them. **Pair selection is manual**; SceneSlate then automatically attempts to synchronize their recorded audio waveforms in the background.
4. New takes are numbered sequentially by insertion order starting at 1 within each shot or sub-shot. Renumber manually as necessary; **Auto** restores automatic numbering while respecting other manually locked numbers.
5. Use arrow keys to select a take (up/down) and side (left/right); use `B`, `R`, `S` to rate the active side. Delete unlinks the selected side only. Add optional descriptions and annotations using the fields below the take table.
6. Use `Ctrl+C` and `Ctrl+V` in the scene tree to copy a scene/shot/sub-shot to multiple destinations. All copies reuse references to the *same* media files; they never copy the bytes.

## Language behavior

- The language choice is stored in the user session (`language: "en"` or `"it"`), **not** in the media catalog. Different computers can display the same catalog in different languages.
- A clean profile starts in English, including buttons, file-browser labels, sort choices, prompts and status messages. Language can be switched at runtime.
- Existing projects keep their custom scene/shot naming conventions. For a new catalog, the default scene label is `Scene` in both languages; change it under **Naming… / Convenzione…** if needed.
- **Source file names, launcher names, CSV file names, CSV column headers, and exported report text are English regardless of UI language.** Resolve's fixed metadata column names are left unchanged. Ratings `B/R/S` and the stable JSON keys never change.
- Your own scene descriptions, annotations, sub-shot names, and media paths are never translated or rewritten.

## Saving, resuming, and upgrading

Named catalogs use `*.sceneslate.json`, saved where you choose. The last catalog, directory selections, file-browser sorting/filter state, selected shot/take, and UI language are automatically restored from a per-user directory:

- Windows: `%APPDATA%\SceneSlate\session.json`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/sceneslate/session.json`
- Optional override: `SCENESLATE_CONFIG_DIR`

The current unnamed autosave is named `autosaved_draft.sceneslate.json`. SceneSlate **also discovers the old `bozza_autosalvata.sceneslate.json` file** when restoring an unsaved catalog from an earlier version. Older catalog JSON formats can be opened and migrated; first save of a migrated catalog creates a version-specific backup before overwriting it. Existing user-defined names and media references are preserved.

To update SceneSlate, replace only its application folder; do not delete the profile directory or your named catalogs. Keep an independent backup of important metadata and footage.

## Exports

Use **Export… / Esporta…** to select any combination of four export modes, choose XML timeline FPS (defaults to 25) and an output directory. CLI supports `--modes csv,take,shot,scene --fps 25`. Output files include:

| File | Contents |
|---|---|
| `full_catalog.csv` | One row per take, paths, quality ratings, notes, and **sync status/offset/score/method/error**; UTF-8 BOM, semicolon-delimited |
| `shot_summary.csv` | Summary for each shot and optional sub-shot; UTF-8 BOM, semicolon-delimited |
| `resolve_metadata.csv` | Standard DaVinci Resolve columns `File Name`, `Clip Directory`, `Scene`, `Shot`, `Take`, `Keywords`, `Comments`; UTF-8, comma-delimited |
| `export_report.txt` | Missing media, contradictory reuse warnings, sync/export notes |
| `xml_takes/*.xml` | **One FCP7 XML timeline per take**: aligned video + external audio if sync `OK` |
| `xml_shots/*.xml` | **One FCP7 XML timeline per shot**, concatenating all takes in the shot and its sub-shots |
| `xml_scenes/*.xml` | **One FCP7 XML review timeline per scene**, concatenating its shots/sub-shots |

In DaVinci Resolve, try **File → Import Metadata To → Media Pool** with the Resolve CSV on a *copy* of the project first. Resolve metadata is clip-based. If one physical media file has multiple incompatible Scene/Shot/Take values across catalog locations, SceneSlate **omits that clip from the Resolve-specific CSV** and records the ambiguity, but keeps *every use* in `full_catalog.csv`.

**Importing XML in DaVinci Resolve:** In the destination project choose **File → Import → Timeline**, then select the desired `.xml` (Final Cut Pro 7 XML / XMEML v5). Check XML frame rate, media relinking, track layout, and the audio alignment in Resolve. These XML files import as **editable timelines**, not native synced source clips in the Media Pool. You can copy or nest a synced take timeline into the main edit, or use the shot/scene review timelines. The `.xml` files contain `file://` URLs pointing to existing original media paths; **they do not include media and never duplicate the footage**. Imported sequences may need relinking after moving files to another machine. **The generated XML has been structurally and source-offset tested, but has not yet been validated in an installed copy of Resolve; try a small scene first.**

**Safety for unsynced media:** SceneSlate does not invent alignment. For a two-file take whose sync status is not `OK`, the XML exports video only and reports the omitted external audio. Audio-only takes export audio; video-only takes export video. If media cannot be inspected using ffprobe, the take is skipped from XML with a report warning. For long recordings, only the shared aligned overlap is exported, avoiding out-of-range media. Each take can appear in multiple scenes without duplicating the underlying files.

The JSON schema and the stored media ratings are language-neutral. English CSV headings and output names are intentional changes from 3.1; scripts consuming the old Italian CSV names/headers need to be updated.

Command-line export (always writes English output):

```bash
python3 scene_slate.py --export catalog.sceneslate.json --out /path/to/output --modes csv,take,shot,scene --fps 25
# Windows: py -3 scene_slate.py --export catalog.sceneslate.json --out C:\path\to\output
```

## Development and automated tests

The UI and correlation fallback use only the Python standard library at runtime (FFmpeg/ffprobe are external programs for synchronization and XML media inspection). Run tests:

```bash
python3 -m unittest discover -s tests -v
# Headless Linux GUI tests:
xvfb-run -a python3 -m unittest discover -s tests -v
```

The internationalization strings are in `scene_i18n.py`; new UI labels and messages should be added there with English equivalents. Keep data model field names and stored session mode IDs untranslated. For cross-platform builds use the included GitHub Actions workflow.

## Limitations

SceneSlate does **not** modify or render original media, and does not provide in-app video preview. Synchronization is non-destructive: it computes an offset stored in the catalog. Creation timestamps on Linux may fall back to modification timestamps when the filesystem does not expose birth time. Audio/video pairing requires a user's deliberate choice. There is currently **no license file**; public availability of source code does not itself grant broad redistribution or reuse rights.

## Upgrade notes for 3.4

Catalog version remains **5**. Older catalog files (v1–v4) migrate automatically, preserving all existing associations. On the first save of a v4 catalog, SceneSlate preserves a `.v4.bak` original. The sync record is attached to the take; copied references retain valid alignments but are invalidated when the underlying media changes. Session configuration stays outside the software folder under the same per-user directory.

### Data interoperability and limitations

- `resolve_metadata.csv` is still a **media-level metadata import**, not a means of assigning native Resolve clip synchronization.
- The XML output references the originals and pairs source in-points by frames, preserving the detected waveform offset. It does not create synced Media Pool sources, timecode, multicam clips or proxies.
- The XML sequence FPS is selected independently of camera FPS. Mixed-frame-rate projects require checking retiming and sequence settings in Resolve.
- Only the first decoded camera and external audio stream is compared; stereo/multichannel external recordings retain up to 16 individual channels in XML playback; very quiet scratch audio, multiple independent channels, very long initial delays, clips with clock drift, and ambiguous repetitive sounds may fail or require verification.
- A background worker processes jobs sequentially to limit disk load; closing the application does not block on background extraction. Sync outcomes are autosaved to the catalog.
