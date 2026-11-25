# update_all_check_first

A copy of the MiSTer [Update All](https://github.com/theypsilon/Update_All_MiSTer) launcher with a review step
added in front of it. You choose which **new cores and scripts** get installed. Anything you don't pick is added
to the `downloader.ini` filter so it never shows up again.

## What it does

Before Update All runs, `ucf.py` downloads every database listed in `/media/fat/downloader.ini` (plus the drop-in
`downloader_*.ini` / `downloader/*.ini` files). It applies the same filter rules Downloader uses and compares the
result with Downloader's record of what is installed (`Scripts/.config/downloader/downloader.json`).

| Change | What happens |
|---|---|
| Updates to installed files | install automatically |
| New dated versions of installed cores (`Foo_20261114.rbf`) | install automatically |
| New extras: wallpapers, MGLs, manuals, BIOS, docs… | install automatically |
| New cores (Console / Computer / Arcade / Other / Utility) | **need approval**: install or block |
| New scripts (`Scripts/…`) | **need approval**: install or block |
| New content whose tags are all shared with installed files | warning; installs unless you pick **Block + delete** |

Arcade items are grouped by the core they run on. Every new item ends up either **installed** or **blocked**.
Blocked items are written to the `[MiSTer]` `filter =` line as `!term` and won't be offered again.

### Why some content can't simply be blocked

Downloader **deletes installed files** that a filter excludes. So a block term is only offered when *no installed
file* carries that tag. When new content shares every tag with installed files (for example new revisions of an
installed arcade game), you get a warning. You can still choose **Block + delete**. The script then lists every
installed file that would be removed, asks you to confirm (default **No**), deletes them and adds the filter term.

## Menus

All menus use `dialog` and work with arrows, Enter and Esc, so a controller can drive them. Enter switches an item.

- **Categories:** install all / block all, or switch items one at a time (`[X]` = install, `[ ]` = block)
- **W – Shared-tag content:** install (default) or block + delete
- **F – Add to filter:** review everything that will be blocked; switch any back to install
- **A – Show automatic changes:** updates, new versions, extras, warnings
- **U – Unblock:** removes a term this script added
- **G – Continue:** confirm screen, then the filter is written, deletions are made, the run is logged and Update All starts
- **X – Exit:** nothing is installed, blocked or deleted, and Update All does not run

If the check fails (no network, broken database list, missing helper), Update All is **not** run, so nothing
installs without being checked.

## Install

Copy the `Scripts` folder to the root of your MiSTer SD card (`/media/fat`):

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
- `Scripts/.config/update_all_check_first/history.log`: installs, blocks and deleted files per run

## Notes and limits

- Update All rewrites the filter lines of the Coin-Op Collection and Ranny-Snice wallpaper databases on every run.
  A block written to those lines would not last, so new items there are only blockable through the global filter.
- Databases that Update All enables during the same run (from its settings screen) are not covered by the check.
- `update_all_check_first.sh` is a copy of `update_all.sh`. When Update All changes its launcher upstream, re-copy
  it and re-add the marked `# CHECK FIRST (added)` block just before `echo "Launching Update All"`.

## Tests

`tests/` holds two scripted UI tests that fake every `dialog` call and write only to copies under `/tmp/ucf_test`.
Run them on a MiSTer: `python3 tests/test_ui_block.py` and `python3 tests/test_ui_block_delete.py`.

## Credits and license

The launcher is derived from `update_all.sh` from
[theypsilon/Update_All_MiSTer](https://github.com/theypsilon/Update_All_MiSTer)
(© José Manuel Barroso Galindo), licensed GPL-3.0-or-later. The filter rules in `ucf.py` follow the behavior of
[MiSTer-devel/Downloader_MiSTer](https://github.com/MiSTer-devel/Downloader_MiSTer).
This project is licensed under the **GNU GPL v3.0 or later**; see `LICENSE`.
