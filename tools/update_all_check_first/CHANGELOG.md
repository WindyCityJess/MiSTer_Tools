# update_all_check_first changes

## 1.1.0 (2026-11-25)
- New choice **Defer**: a new core or script is not installed and not blocked; it is offered again next run.
  It is filtered for this run only and released after Update All finishes (or at the start of the next run).
- Enter cycles Install -> Block -> Defer; "defer all" in each category and the main menu.
- The Add-to-filter menu can switch an item to install or defer.

## 1.0.0 (2026-11-25)
- First release: review new cores and scripts before Update All runs, by category; install or block
  (downloader.ini filter); shared-tag warning with optional block + delete; unblock menu; backups and history log.
