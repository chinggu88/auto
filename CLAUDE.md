# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A screen-automation macro for a Windows MMO client (IntelliJ module name: `lin_auto`). It drives the game purely through synthetic mouse/keyboard input and screen-pixel template matching — there is no game API, no network code, and no parsing of game memory.

## Running

There is no build, test suite, lint config, or dependency manifest. Each top-level `.py` is an independent entry point run directly:

```
python main.py     # full-featured: HP/mark watchers + buff timers + attack loop
python oman.py     # "오만" variant: adds transform() + die() revive handling
python tell.py     # near-copy of oman.py; attacks with an f5 press every 3 sweeps, 3-hour auto-stop
python turn.py     # transform/mark-detection only; attack loop commented out
python main2.py    # simplest: manual-assist middle-click when cursor is over a target
```

Dependencies (install manually): `pyautogui`, `pywin32`, `keyboard`, `schedule`. Python 3.9 per `.idea/misc.xml`.

**Windows-only.** `win32gui` and the hardcoded `'\\'` path separators in every `file_path` construction mean these scripts cannot run on the macOS dev machine — they can only be edited here. Do not attempt to execute them to verify changes.

To stop a running script: `pyautogui.FAILSAFE` is disabled in `oman.py`/`tell.py`/`turn.py`, so the corner-of-screen escape hatch does **not** work there. The attack loops are `while True` with no keyboard interrupt handler.

## Architecture

The five scripts are copy-paste forks of each other rather than a shared library. A change to one is usually not propagated; when fixing a bug, check whether the same code exists in the other four and ask which variants should be updated.

**Target detection via cursor shape.** The core trick: the game changes the mouse cursor when it hovers a valid attack target. `setattckinfo()` runs once at startup — it moves to a known-good spot, holds ctrl, and captures `win32gui.GetCursorInfo()[1]` as `attackinfo`. The attack loop then compares the live cursor handle against that baseline to decide whether to click. This makes `attackinfo` a session-specific handle value that must be re-captured on every run; it cannot be hardcoded (the commented `attackinfo=1018953961` in `main.py:335` is a stale artifact).

**Attack sweep (`attack1`).** Walks the cursor in a square perimeter of `len × 50px` steps around `centerpoint`. Before each probe it first moves to `(x, y+400)` — a "park" position off the play area — to force the game to re-evaluate and redraw the cursor; without that move the shape would be stale. `len` must be odd (the code prints a warning and does nothing otherwise). `attack()` in `main.py` is the unconditional variant that clicks every cell without checking cursor shape.

**Template matching.** All state sensing goes through `pyautogui.locateCenterOnScreen(image/<name>.PNG, confidence=…)` against `image/`:
- `checkhp.PNG` / `checkmp*.PNG` — low-resource warning UI, triggers recall
- `mark1-4.PNG` — hostile clan mark on screen, triggers flee (F8)
- `lv80.PNG`, `night.PNG` — transform-menu entries, clicked directly at the match location
- `out.PNG` — death/revive dialog

Confidence thresholds are tuned per image and vary between files (0.2 to 0.8) — they are resolution- and UI-scale-dependent, not arbitrary.

**Scheduling via self-rescheduling timers.** There is no event loop. Each watcher ends with `threading.Timer(N, itself).start()`, so it re-arms after every run: HP/mark checks at 1-4s, buffs at 600/1200/1700s, transform at 600/1800s. `main()` starts the watchers, then blocks in the attack loop on the main thread. `schedule` is imported everywhere but only `main.py` calls `sc.run_pending()`, and nothing is registered with it.

**Coordination is module-level globals only.** `isattack` (or `ishunting`/`isture` in `main.py`) is read by the attack loop and written by the watcher threads to pause attacking during buffs, transforms, or a flee. There is no lock; races are tolerated by design.

**Hardcoded to one screen layout.** `centerpoint = [625, 480]` in every script, plus the `+400` park offset and `50`/`90` step sizes, assume a specific window size and position. F5–F12 map to in-game skill/item slots, and the *same* key means different things across scripts (e.g. F8 is flee in `main.py`/`oman.py`, but `tell.py`'s `checkrHp` presses F5 instead).

## Known defects in the current code

Present in the committed source; be deliberate about whether a task wants them fixed:
- [oman.py:125](oman.py#L125) — `die()` re-schedules `transform` instead of itself, so death detection runs once.
- [oman.py:150](oman.py#L150) and [tell.py:137](tell.py#L137) — `os.path.realpath('__file__')` passes the string literal, resolving `file_path` relative to the cwd rather than the script directory (the other functions in the same files use `__file__` correctly).
- [turn.py:143](turn.py#L143) — `mark4[0] <= 600 & mark4[0] >= 650` is both bitwise-`&` and unsatisfiable, so that branch never fires.
- [main.py:246](main.py#L246) — `checkrMp` assigns `ishunting` without a `global` declaration, so the state change is discarded.

## Conventions

Comments, `print()` output, and intent notes are in Korean; keep new ones in Korean to match. Dead code is kept commented out in place rather than deleted — it records alternate hunting strategies for different dungeons, so prefer commenting out over removing when disabling a behavior.
