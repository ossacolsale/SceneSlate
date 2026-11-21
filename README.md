# SceneSlate 3.2

SceneSlate is a **cross-platform, offline footage catalog** written in Python 3 and Tkinter. Its interface is available in **English and Italian**. A new installation starts in **English**; change the language using the **Language / Lingua** selector in the top toolbar. The preference survives restarts and upgrades, and switching languages does **not** rename files, modify a catalog or reset the scene selection.

Footage is organized as **scene → shot → optional sub-shot → take**. Every take has an optional video reference and an optional audio reference, each with independent ratings (`B` good, `R` reserve, `S` reject). Takes can have descriptions and annotations; scenes, shots and sub-shots have optional descriptions. **Original media files are never renamed, moved, deleted or duplicated.** Pairing is cataloguing only: it does not synchronize audio or video waveforms.

## Starting the application

| Platform | Recommended launcher | Requirements |
|---|---|---|
| Windows | Double-click `SceneSlate.vbs` or `scene_slate.pyw` | Python 3.10+ with Tkinter and `.pyw` file association |
| Linux | Open `SceneSlate.desktop` from a file manager, or run `./launch_linux.sh` | Python 3.10+ with Tkinter (`python3-tk` on Ubuntu/Debian) |

The Windows `.vbs` entry point uses `pythonw.exe` (via `.pyw` file association) so it does not leave a Command Prompt window open. For troubleshooting use `launch_windows.bat`. The Linux desktop shortcut uses `Terminal=false`; depending on your file manager, it may require marking it executable or trusted. To launch in a terminal, run `python3 scene_slate.py`.

This source package is *not* a precompiled Windows executable. To build an independent executable on the target OS, use `build_windows.bat` or `build_linux.sh` after installing PyInstaller. The GitHub Actions workflow tests and builds for Windows and Linux, with downloadable workflow artifacts.

## Typical workflow

1. Browse the original video and audio folders. Each file browser supports name/date sorting, searching, subfolder scanning, highlighting unassigned files, and filtering to unassigned files only.
2. Create scenes and shots (positive integers), with optional sub-shots named `A`, `B`, `Detail`, `Wide shot`, or any other nonempty name. Takes may be attached directly to a shot even when sub-shots exist.
3. Drag a video or audio onto a shot/sub-shot to create a take. Drag the other kind onto the same take row to explicitly pair them. No automatic media matching is attempted.
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

Use **Export… / Esporta…** to select an output directory. The files are:

| File | Contents |
|---|---|
| `full_catalog.csv` | One row per take, video/audio paths, quality ratings, descriptions, notes, sub-shot and all references; UTF-8 BOM, semicolon-delimited |
| `shot_summary.csv` | Summary for each shot and optional sub-shot; UTF-8 BOM, semicolon-delimited |
| `resolve_metadata.csv` | Standard DaVinci Resolve columns `File Name`, `Clip Directory`, `Scene`, `Shot`, `Take`, `Keywords`, `Comments`; UTF-8, comma-delimited |
| `export_report.txt` | Missing media, contradictory reuse warnings, export notes |

In DaVinci Resolve, try **File → Import Metadata To → Media Pool** with the Resolve CSV on a *copy* of the project first. Resolve metadata is clip-based. If one physical media file has multiple incompatible Scene/Shot/Take values across catalog locations, SceneSlate **omits that clip from the Resolve-specific CSV** and records the ambiguity, but keeps *every use* in `full_catalog.csv`.

The JSON schema and the stored media ratings are language-neutral. English CSV headings and output names are intentional changes from 3.1; scripts consuming the old Italian CSV names/headers need to be updated.

Command-line export (always writes English output):

```bash
python3 scene_slate.py --export catalog.sceneslate.json --out /path/to/output
# Windows: py -3 scene_slate.py --export catalog.sceneslate.json --out C:\path\to\output
```

## Development and automated tests

The application uses only the Python standard library at runtime. Run tests:

```bash
python3 -m unittest discover -s tests -v
# Headless Linux GUI tests:
xvfb-run -a python3 -m unittest discover -s tests -v
```

The internationalization strings are in `scene_i18n.py`; new UI labels and messages should be added there with English equivalents. Keep data model field names and stored session mode IDs untranslated. For cross-platform builds use the included GitHub Actions workflow.

## Limitations

SceneSlate does **not** edit, sync or preview media. Creation timestamps on Linux may fall back to modification timestamps when the filesystem does not expose birth time. Audio/video pairing requires a user's deliberate choice. There is currently **no license file**; public availability of source code does not itself grant broad redistribution or reuse rights.
