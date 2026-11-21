# SceneSlate 3.1

SceneSlate is an **offline desktop media-logging application** built with Python and Tkinter. It organizes film footage into **scenes → shots → optional sub-shots → takes**. Each take can reference one video file, one audio file, or both, with independent quality ratings (**B** = good, **R** = reserve, **S** = reject). Original media files are **never moved, deleted, copied, or modified**.

The interface is currently in Italian; this README and project documentation are in English.

## Getting started

| Platform | Recommended launcher | Requirements |
|---|---|---|
| Windows | Double-click `SceneSlate.vbs` (or `scene_slate.pyw`) | Official Python 3.10+ installation with Tkinter and `.pyw` association |
| Linux | Launch `SceneSlate.desktop` from your file manager (you may have to mark it trusted/executable), or run `./avvia_linux.sh` | Python 3.10+ with Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu) |

These launchers are designed to avoid showing a terminal window. On Windows, `avvia_windows.bat` is provided as a diagnostic fallback. On Linux, you can also run `python3 scene_slate.py` from a terminal.

The source distribution does **not** include a compiled Windows `.exe`. To build a stand-alone executable on its target platform, run `build_windows.bat` or `build_linux.sh` (requires PyInstaller). The included GitHub Actions workflow can build platform-specific artifacts.

## Basic workflow

1. Point the video and audio browsers at your existing media folders; files remain in place, including on RAID or network storage. The browsers support searching subfolders, sorting by name/date, and filtering for unused files.
2. Add scenes with **+ Scena**, shots with **+ Shot**, and optional sub-shots with **+ Sotto-shot**. Shot identifiers are positive integers; sub-shot identifiers can be arbitrary names such as `A`, `B`, `Close-up`, or `Camera 2`. Takes can also belong directly to a shot without a sub-shot.
3. Drag a video or audio file onto a shot/sub-shot to create a take. Drop the other kind of file onto the take row to complete the pair. Pairing is **explicit**, not guessed from filenames or dates.
4. New takes get the next sequential take number in their parent shot/sub-shot. The number can be edited with **N° ciak…**; **↻ Auto** recalculates automatically assigned numbers while keeping manually set numbers fixed. Filesystem creation dates are used only for optional browser sorting (Linux may fall back to modification time).
5. Navigate takes with **Up/Down**, select video or audio with **Left/Right**, and rate the selected side using **B/R/S**. **Delete** unlinks only the selected media reference, not the underlying file.
6. Optionally enter descriptions for scenes, shots and sub-shots, plus a description and annotations for each take (audio/video pair). All values are saved and included in full exports.

## Fast copy/paste between scenes and shots

Select a node on the left, then press **Ctrl+C** or use **Copia contenuto**. Select a destination and press **Ctrl+V** or **Incolla nella selezione**. Clipboard contents remain available for repeated pastes into different destinations.

- Pasting into a **scene** creates new shots, assigning unused shot numbers when needed.
- Pasting into a **shot** appends takes and/or sub-shots depending on the copied node.
- Pasting into a **sub-shot** appends the copied takes.

Descriptions and annotations travel with copied objects. Sub-shot IDs are regenerated, duplicate names receive suffixes, and pasted takes are numbered progressively. **Only filesystem references are copied**, so you can reuse footage across many scenes without duplicating media on disk.

## Saving, compatibility and upgrades

Use **Salva con nome…** to save a named `*.sceneslate.json` catalog; later edits are automatically saved. Unnamed drafts are also recoverable locally. Catalogs from earlier versions are migrated without inventing audio/video pairings. Before a migrated catalog is overwritten, a versioned `*.v1.bak`, `*.v2.bak`, or `*.v3.bak` backup is kept. Legacy notes on scenes/shots become descriptions; take notes become annotations. Legacy JSON fields are preserved where possible.

Application preferences live **outside the program directory**, so replacing the extracted software folder will not delete them:

- Windows: `%APPDATA%\SceneSlate\session.json`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/sceneslate/session.json`
- Override directory: `SCENESLATE_CONFIG_DIR` environment variable.

Your named catalogs and original media stay wherever you saved them. Keep independent backups of important projects.

## Exporting data to DaVinci Resolve and other software

**Esporta…** generates:

| File | Purpose |
|---|---|
| `catalogo_completo.csv` | One row per take with video/audio paths, independent ratings, optional sub-shot, descriptions and annotations; UTF-8 with BOM, `;` delimiter |
| `riepilogo_shot.csv` | Summary by shot and sub-shot |
| `resolve_metadata.csv` | Resolve Media Pool metadata, including `File Name`, `Clip Directory`, `Scene`, `Shot`, `Take`, `Keywords`, and `Comments` |
| `report_esportazione.txt` | Missing media, conflicting reuse, and export warnings |

Import Resolve metadata using **File → Import Metadata To → Media Pool**. Descriptions and annotations are included in `Comments`. Sub-shot information is included in Keywords/Comments because a universally supported Resolve sub-shot metadata field is not available.

**Important:** Resolve metadata is clip-based. If the same physical file appears in multiple scenes with incompatible metadata, SceneSlate preserves all uses in its complete catalog but omits the ambiguous clip from the Resolve-specific metadata CSV and explains the conflict in the report.

**SceneSlate does not synchronize audio and video.** It logs their association. Use Resolve's timecode sync, waveform sync or a manual clap reference for actual alignment. Test CSV imports on a copy of the target project first.

Command-line export:

```bash
python3 scene_slate.py --export catalog.sceneslate.json --out /path/to/export
# Windows equivalent: py -3 scene_slate.py --export catalog.sceneslate.json --out C:\path\to\export
```

## Development and tests

Runtime uses only the Python standard library (including Tkinter). Run tests with:

```bash
python3 -m unittest discover -s tests -v
# For GUI tests on headless Linux:
xvfb-run -a python3 -m unittest discover -s tests -v
```

There is currently **no license file**. Public source availability does not itself grant broad redistribution or reuse rights.
