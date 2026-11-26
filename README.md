# MiSTer Tools

Small tools for [MiSTer FPGA](https://github.com/MiSTer-devel/Wiki_MiSTer/wiki), installed and kept up to date by
Downloader / Update All.

## Tools

| Tool | What it does | Docs |
|---|---|---|
| **update_all_check_first** | Runs Update All, but first shows what's new: new cores and scripts are installed, blocked for good, or deferred to the next run, by category, with a controller-friendly menu. | [README](tools/update_all_check_first/README.md) · [changes](tools/update_all_check_first/CHANGELOG.md) |

More tools will be added here as they are built.

## Install

### With Downloader / Update All (recommended)

Add this to `/media/fat/downloader.ini`, then run Update All (or `downloader`):

```ini
[windycityjess/mister_tools]
db_url = https://raw.githubusercontent.com/WindyCityJess/MiSTer_Tools/db/db.json.zip
```

Every tool is installed and updated from then on. To leave one out, add `!<tool name>` to the `filter =` line of
the `[mister]` section, for example `filter = ... !update_all_check_first`.

If you use update_all_check_first, tools added to this database later show up there as new scripts that need
your approval, like any other database.

### By hand

Download the tool's zip from [Releases](https://github.com/WindyCityJess/MiSTer_Tools/releases) and copy its
`Scripts` folder to the root of the SD card (`/media/fat`).

## Repository layout

```
Scripts/                  what gets installed, in SD-card layout (/media/fat/Scripts/...)
tools/<tool>/             per tool: README, CHANGELOG, files.txt (its installed files), tests
build/build_db.py         builds the Downloader database from tools/*/files.txt
.github/workflows/db.yml  rebuilds the database on every push to main and publishes it to the db branch
```

### Adding a tool

1. Put its files under `Scripts/` exactly as they go on the SD card.
2. Create `tools/<tool>/` with `README.md`, `CHANGELOG.md`, `files.txt` (one installed path per line) and tests.
3. Add a row to the table above and an issue label `tool: <tool>`.
4. `python build/build_db.py --check` must pass; after the push the database updates itself.
5. Tag a release `<tool>-v1.0.0` with a zip of its files.

## Issues

Use the issue forms and pick the tool. Each tool has its own label.

## License

GNU GPL v3.0 or later; see `LICENSE`. update_all_check_first is derived from
[theypsilon/Update_All_MiSTer](https://github.com/theypsilon/Update_All_MiSTer) (GPL-3.0-or-later).

This project was developed with the assistance of AI.
