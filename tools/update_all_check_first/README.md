# update_all_check_first

Part of [MiSTer Tools](../../README.md).

A copy of the MiSTer [Update All](https://github.com/theypsilon/Update_All_MiSTer) launcher with a review step
added in front of it. You choose what happens to each **new core and script**: install it, block it (added to
the `downloader.ini` filter so it never shows up again), or defer it (not installed now, asked again next run).

## What it does

Before Update All runs, `ucf.py` downloads every database listed in `/media/fat/downloader.ini` (plus the drop-in
`downloader_*.ini` / `downloader/*.ini` files). It applies the same filter rules Downloader uses and compares the
result with Downloader's record of what is installed (`Scripts/.config/downloader/downloader.json`).

| Change | What happens |
|---|---|
| Updates to installed files | install automatically |
| New dated versions of installed cores (`Foo_20261114.rbf`) | install automatically |
| New extras: wallpapers, MGLs, manuals, BIOS, docs… | install automatically |
| New cores (Console / Computer / Arcade / Other / Utility) | **need approval**: install, block or defer |
| New scripts (`Scripts/…`) | **need approval**: install, block or defer |
| New content whose tags are all shared with installed files | warning; installs unless you pick **Block + delete** |

Arcade items are grouped by the core they run on. Every new item is **installed**, **blocked** or **deferred**.
Blocked items are written to the `[MiSTer]` `filter =` line as `!term` and won't be offered again.

### How Defer works

Downloader installs everything the filter doesn't exclude, so an item can't just be left out of both lists.
A deferred item's `!term` is added to the filter **for this run only**. When Update All finishes, the launcher
runs `ucf.py --release-deferred`, which takes the term back out. Nothing was installed for it, so nothing is
deleted, and the item shows up as new again next time. If the release never runs (reboot, power loss), the
next run of the script releases it before checking. Running plain Update All or Downloader in between keeps the
deferred items out until then.

Shared-tag content (below) can't be deferred: filtering it even for one run would delete the installed files.

### Why some content can't simply be blocked

Downloader **deletes installed files** that a filter excludes. So a block term is only offered when *no installed
file* carries that tag. When new content shares every tag with installed files (for example new revisions of an
installed arcade game), you get a warning. You can still choose **Block + delete**. The script then lists every
installed file that would be removed, asks you to confirm (default **No**), deletes them and adds the filter term.

## Menus

All menus use `dialog` and work with arrows, Enter and Esc, so a controller can drive them. Enter switches an item.

- **Categories:** install all / block all / defer all, or switch items one at a time (Enter cycles
  `[Install]` → `[Block]` → `[Defer]`)
- **Main menu `*`, `/`, `~`:** install, block or defer every new core and script at once
- **W – Shared-tag content:** install (default) or block + delete
- **F – Add to filter:** review everything that will be blocked; switch any to install or defer
- **A – Show automatic changes:** updates, new versions, extras, warnings
- **U – Unblock:** removes a term this script added
- **G – Continue:** confirm screen, then the filter is written, deletions are made, the run is logged and Update All
  starts; deferred terms are removed again when it finishes
- **X – Exit:** nothing is installed, blocked or deleted, and Update All does not run

If the check fails (no network, broken database list, missing helper), Update All is **not** run, so nothing
installs without being checked.

## Install

Install through the MiSTer Tools database (see the [main README](../../README.md#install)), or copy these
files to your MiSTer SD card (`/media/fat`):

```
/media/fat/Scripts/update_all_check_first.sh
/media/fat/Scripts/.config/update_all_check_first/ucf.py
```

Then run **update_all_check_first** from the MiSTer Scripts menu. Over SSH you can preview the analysis without
changing anything:

```
python3 /media/fat/Scripts/.config/update_all_check_first/ucf.py --report
```

Requires `python3` and `dialog` (both included in MiSTer Linux).

## Files it writes

- `/media/fat/downloader.ini`: `!term` added to `[MiSTer] filter` (or to a database's own `filter =` line when
  that database has one without `[mister]`). A backup `downloader.ini.bak_ucf_<timestamp>` is made before every
  write, and the 10 newest are kept.
- `Scripts/.config/update_all_check_first/blocked.json`: what this script blocked (used by the Unblock menu)
- `Scripts/.config/update_all_check_first/deferred.json`: deferred terms waiting to be released (only exists
  while Update All runs, or if a release was missed)
- `Scripts/.config/update_all_check_first/history.log`: installs, blocks, deferrals and deleted files per run

## Notes and limits

- Update All rewrites the filter lines of the Coin-Op Collection and Ranny-Snice wallpaper databases on every run.
  A block written to those lines would not last, so new items there are only blockable through the global filter.
- Databases that Update All enables during the same run (from its settings screen) are not covered by the check.
- `update_all_check_first.sh` is a copy of `update_all.sh`. When Update All changes its launcher upstream, re-copy
  it and re-add the marked `# CHECK FIRST (added)` block just before `echo "Launching Update All"`.

## Tests

`tests/` holds three scripted UI tests that fake every `dialog` call and write only to copies under
`/tmp/ucf_test`. Copy `tests/` to the MiSTer and run `python3 test_ui_block.py`, `python3 test_ui_block_delete.py` and
`python3 test_ui_defer.py`.

## Credits and license

The launcher is derived from `update_all.sh` from
[theypsilon/Update_All_MiSTer](https://github.com/theypsilon/Update_All_MiSTer)
(© José Manuel Barroso Galindo), licensed GPL-3.0-or-later. The filter rules in `ucf.py` follow the behavior of
[MiSTer-devel/Downloader_MiSTer](https://github.com/MiSTer-devel/Downloader_MiSTer).
This project is licensed under the **GNU GPL v3.0 or later**; see `LICENSE`.

This tool was developed with the assistance of AI.
