# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A screen-automation macro for a Windows MMO client (IntelliJ module name: `lin_auto`). It drives the game purely through synthetic mouse/keyboard input and screen-pixel template matching — there is no game API, no network code, and no parsing of game memory.

## Project rules (new work)

These apply to everything written from now on, starting with the `iksun/` program. The older
top-level scripts predate them and are kept as they are.

1. **No image detection.** Do not add `locateCenterOnScreen` / template matching / `image/*.PNG`
   checks. State comes from memory only; when a value cannot be read, the action stops (it does
   not fall back to the screen).
2. **No mouse or keyboard input to control the game.** Game actions (buffs, potions, recall,
   casting, movement, attacking) are done through memory access, not `pyautogui` / `keyboard`
   presses or clicks. Hotkeys that control *this* program (e.g. the `Tab` emergency stop) are
   not game control and are allowed.
   - Every address written must be listed in `mem.json`, and temporarily changed values are
     restored after the action (as `memcast.py` does for `spell_target`).
3. **All item and skill use goes through direct in-process function calls ("방법 2").**
   Decided by the user on 2026-11-14 over the alternatives below, accepting that it carries the
   highest detection/ban risk (an account was banned on 2026-10-27; see `skillcast.py`). Do not
   switch to another mechanism without asking.
   - Why no pure memory write works: `Lin.exe` runs hotkeys only from its window procedure
     (`FUN_00434ae0`: WM_KEYDOWN F5–F12 → `FUN_00434920` → `FUN_00460e70`, plus F10 and wheel
     click). No per-frame "pending action" flag exists. The send backlog at `0x5FABE4` is only
     flushed on the Winsock FD_WRITE message, and every packet is XOR-chained with the rolling
     8-byte key at `0x5FABD0`, so injecting packets from outside desyncs the stream.
   - Rejected alternatives (keep for reference): PostMessage WM_KEYDOWN to the game window
     ("방법 1", hotkey items only), and "임시 단축키 칸" — write name/bless/flag into a hotkey slot
     (`0x4A2850 + k*0x30`, `0x4A27F0 + k*4`, `0x4A27D8 + k`) then PostMessage that key.
   - Entry points found by static analysis (unverified in the live client):
     - `FUN_00460e70(slot, 0)` — runs hotkey slot 0–7 (F5–F12). `__stdcall`, `ret 8`, uses
       only its arguments, so it does **not** need the self pointer (`0x5AB548`, which reads 0
       and is what blocked `skillcast.py`). Branches on `0x4A27D8[slot]`: spell →
       `FUN_0045e8c0`, item → `FUN_0042c110`.
     - `FUN_0042c110(slot)` (ECX = inventory window `[0x4A2DBC]`) — finds the inventory entry
       whose name matches the slot name and whose bless (+0x6C) matches `0x4A27F0[slot]`, then
       acts by use type (+0x68). Plain-use types send `FUN_0045a380("cds", 0x1C, item_id, "")`.
       Types 0x05/0x07/0x08/0x0E/0x11/0x1A/0x1B only enter a target-selection mode.
     - `FUN_0045a380(fmt, ...)` — builds, encrypts and sends one packet (`mySend` =
       `FUN_0045a050`). Using an inventory item that is not on the hotkey bar means calling this
       with the use-item packet directly.
     - `FUN_0045e270(skill_code, 0)` — skill entry used by `skillcast.py` (needs the self
       pointer in ECX, currently 0).
   - These functions touch UI and global state, so they must run **on the game's main thread**.
     `CreateRemoteThread` crashed the client (2026-11-13). Whether the APC route in
     `skillcast.py` is ever delivered (the main thread must enter an alertable wait) is
     unverified — establish a reliable main-thread execution path first.
   - Current code still violating rule 2 until this lands: `memcast.py` (`gu.press`) and
     `iksun/main.py` `Ctx.press` (`pyautogui`).
4. **Exception — top-level `main.py` attacks by mouse left-click.** Decided by the user on
   2026-11-15 after the function-call attack was dropped for `main.py`. Sensing is memory-only
   (entity table), but the attack is a real click at the mob's computed screen position, and
   buffs / transform / recall / refresh are still key presses. This exception covers `main.py`
   only; `iksun/` stays under rules 1–3.

## Running

There is no build, test suite, lint config, or dependency manifest. Each top-level `.py` is an independent entry point run directly:

```
python main.py     # full-featured: HP/mark watchers + buff timers + attack loop
python pit.py      # memory-based: reads HP/clan/mob list from client memory instead of the screen
python oman.py     # "오만" variant: adds transform() + die() revive handling
python tell.py     # near-copy of oman.py; attacks with an f5 press every 3 sweeps, 3-hour auto-stop
python turn.py     # transform/mark-detection only; attack loop commented out
python main2.py    # simplest: manual-assist middle-click when cursor is over a target
```

Dependencies (install manually): `pyautogui`, `pywin32`, `keyboard`, `schedule`. Python 3.9 per `.idea/misc.xml`.
`pit.py` and its tools add no dependencies — they call `ReadProcessMemory` through `ctypes` directly.

**Windows-only.** `win32gui` and the hardcoded `'\\'` path separators in every `file_path` construction mean these scripts cannot run on the macOS dev machine — they can only be edited here. Do not attempt to execute them to verify changes.

To stop a running script: `pyautogui.FAILSAFE` is disabled in `oman.py`/`tell.py`/`turn.py`, so the corner-of-screen escape hatch does **not** work there. The attack loops are `while True` with no keyboard interrupt handler.

## `main.py` hunting and recall (memory-sensed, since 2026-11-15)

`main.py` no longer sweeps the cursor or matches clan-mark images. Both features read
`memread.Mem.entity_table()` (the same source `postracker.py` uses):

- **Hunting (`huntloop`)** — `scanents()` lists live non-player entities within `dist` tiles
  (Chebyshev), nearest first. The loop keeps one target id, clicks it, and moves to the next
  nearest when the target is `dead` or gone from the table. Screen position comes from the
  affine calibration file beside the script (`scarecrow_calib.json` from `postracker.py`'s F9
  scarecrow calibration, else `calib.json` from `turnundead_mem.py`); without one it refuses to
  start. **No cursor-shape check** (removed by the user on 2026-11-15): the computed position is
  clicked directly. The probe's miss cooldown made the loop see "no mobs" and teleport while mobs
  were present. Off-screen mobs and nameless entities are not candidates.
- **Auto calibration (`autocalib.py`, `opts['autocal']`, since 2026-11-22).** Replaces the manual
  scarecrow F9 step. With 시작할 때 자동 보정 on (default), `runmacro` calls `autocalib.run(MEM, log,
  alive)` before loading calibration: it reads the game client rect (`GetClientRect` /
  `ClientToScreen`), spirals the cursor out from its centre every `GRID` px reading `chains.hover_id`
  (`Lin.exe+0x1AB548`, entity pointer under the cursor, 0 on empty ground; a hit counts only if two
  reads `SETTLE` apart agree), pairs each hit with that entity's game offset from me at that moment,
  traces the sprite's bottom / left / right edges in `STEP` px and uses the foot centre `CLICK_UP`
  px up as the point (sprite centres vary with mob height; feet sit on the tile), drops entities
  that moved while being traced, fits RANSAC within `INLIER_PX`, then probes
  the predicted spot of entities not yet hit, and saves only if leave-one-out error ≤ `LOO_MAX`.
  Any entity works (mobs, NPCs, players, me). Result goes to `auto_calib.json` (same `points`
  format), which heads `CALIB_FILES`; on failure the older files are used. Moves the cursor only —
  no clicks, no writes. `python autocalib.py` runs it standalone.
- **Hold while attacking (since 2026-11-22, codes assumed, not yet confirmed in-game).** `huntloop`
  reads my entity's `act` (+0x0C); if it is in `ATTACK_ACTS` (Lineage action table: attack =
  1 / 5 / 12 / 21 / 25 / 41 for bare / 1H sword / axe / bow / spear / 2H sword) it does not re-click,
  does not switch to a nearer mob, and counts as progress for the stuck check. When the target ends
  while still attacking, the next search waits up to `ATK_WAIT_MAX`. Attack keys still fire.
  `python memprobe.py --act` prints my act / base live to confirm the codes.
- **Recall (`_checkrHp`)** — any entity of kind `player` other than self → `request('return')`.
  "Could not read" is never treated as "nobody around": `MEM_FAIL_LIMIT` consecutive failures stop
  the macro. The HP check is still the `checkhp.PNG` image.
- **Entity kinds** come from `mem.json` `ent.rules` via `Mem.kind()`. `player` is "id in
  1,000,000–1,999,999" (measured 2026-11-15 on seven characters; `+0x4C == 255` was dropped
  because ground effects such as `마법진3` share it), preceded by a name-based `effect` rule.
  With no `monster` rule, every named entity judged `other` is a candidate — NPCs included,
  nothing filters them now. `python memprobe.py --entkind --mob … --npc … --pc …`
  finds a discriminating offset.
- **No mobs → teleport at once.** When no clickable mob is in range the loop presses the refresh
  key immediately (`TELE_GAP` 1.5 s between presses); the old "N empty sweeps" counter is unused.
  Click interval is `RECLICK_SEC` 1 s, and each click re-picks the nearest mob.
- **Chat buff (`dochatbuff`) writes the text into the chat input buffer** via `memchat.py`
  (verified in-game 2026-11-15). `mem.json` `chains.chat_str` = `[[Lin.exe+0xA3288]+0x28]+0` is a
  string struct: `+0` buffer pointer, `+4` char count. Each char is one 2-byte cell — ASCII as is,
  Hangul as `(CP949 lead << 8) | trail`, **not** UTF-16. An empty input has a null buffer and its
  capacity is unknown, so the flow is Enter → type `1` × len (IME-independent) → overwrite those
  cells in place → Enter; `memchat.put` refuses to write more cells than are already there.
  `0x9BF98` is the "focused edit" pointer and is 0 when the input is empty — do not use it.
  `python memchat.py ".버프" --auto` runs the same sequence standalone.
- **Walking distance (terrain grid, since 2026-11-17).** `scanents()` measures mob distance as
  BFS walking steps over the terrain grid (`memread.terrain()` / `terrain_blocked()`, merged from
  `feat/spell-table`; the `memprobe --terrain` map was confirmed against the screen on
  2026-11-17). The search radius is `HUNT_DIST + PATH_MARGIN`, the grid is re-read every
  `TERRAIN_SEC` or when it no longer covers that radius around me, and the BFS is cached per
  position. Mobs with no path are dropped. With no open space, the step count equals Chebyshev
  distance. The straight-line distance is kept in `o['line']` and attack-key range (`dist`) uses
  it. Players stay straight-line. An unreadable grid falls back to straight-line distance (logged
  on change) rather than stopping, because terrain only orders targets.
- **Crowd refresh (`opts['crowd']`, since 2026-11-17).** The 메인 tab row 몹 몰림 새로고침 (under
  탐지 거리) sets `CROWD_N`: when `scanents()['mobs']` (live mobs within `HUNT_DIST` walking steps,
  off-screen included) reaches that count, the loop presses the refresh key at once (respecting
  `TELE_GAP`) and drops the target. 0 = off; needs the refresh key; detect-only logs only.
- **Player encounter (`opts['pc_act']` / `opts['pc_dist']`, since 2026-11-21).** The 메인 tab row
  사람 만남 picks the reaction — 베르 후 정지 (`'ber'`, the old behaviour) or 새로고침(텔) (`'refresh'`:
  press the refresh key, drop the target, keep hunting; `TELE_GAP` between presses and no attacking
  meanwhile) — and a trigger radius `PC_DIST` in straight-line tiles (0 = any visible player).
  `nearpcs()` applies the radius for both `huntloop` and `_checkrHp`. `'refresh'` with no refresh key
  falls back to ber + stop. In `'refresh'`, the row below (강제 베르, `opts['pc_ber']` / `PC_BER`, since
  2026-11-22) forces ber + stop once the player-triggered teleports this run (`pcmeet` in `huntloop`)
  reach that count; 0 = off, and the entry is disabled while 베르 후 정지 is selected.
- **Unreachable mobs (fallback).** For obstacles not in the grid (other mobs, doors), a target
  farther than `STUCK_REACH` tiles with no progress (own position unchanged, distance not
  shrinking) for `STUCK_SEC` is skipped for `SKIP_SEC`; if nothing else remains the loop
  teleports.
- **Idle watchdog removed (2026-11-17).** The forced teleport after `IDLE_TELE_SEC` with no
  target change was deleted at the user's request; the loop no longer stalls on one target.
- **Heal / Ber / Immune** — three more F-key roles (`heal`, `ber`, `immune`). Each hunt-loop tick
  reads HP (`readhp()`: secure holder first, then `chains.hp`) and the live-mob count from
  `scanents()`: HP% ≤ `heal_pct` / `ber_pct` presses that key, mobs ≥ `immune_n` presses immune.
  Heal and immune need a target, so they go through `memcast.Caster.castkey(self_id, self_ptr, key)`
  (same mechanism as `postracker.py`'s turn-undead: write the target id, press the key, restore);
  ber is a plain key press.
  The key's 주기 column is the re-press gap (0 → `GAP_DEFAULT`: 2 s / 2 s / 30 s). They run with
  attack off too, never in detect-only, and `MEM_FAIL_LIMIT` unreadable HP reads stop the macro.
- **Hotkey pages F1 / F2 and the tabs (since 2026-11-15)** — the game's F5–F12 bar has two
  pages: F1 = attack page, F2 = buff page. The GUI is a three-tab notebook (메인 / 버프 / 공격)
  with the save/start buttons and log below it.
  - 버프 tab (F2 page): key + 주기 for F5–F12 plus a 변신 키 dropdown (its interval is that
    key's 주기 cell; `dotransform` still clicks the lv80 / night menu). `BUFFS` is every key
    except the transform key. `runpending()` batches all pending buff / transform requests
    into one `setpage(PAGE_BUFF)` → presses → `setpage(PAGE_ATTACK)`; chat buff runs inside the
    batch without caring about the page. At start the queued initial buffs go through the same
    path, and `runmacro` presses F1 once before `huntloop` so hunting always begins on the
    attack page.
  - 공격 tab (F1 page): the attack-key table (up to `ATTACK_MAX` 4 rows, default one:
    F6 / 4 s / 3 tiles, `opts['attacks']` = `[{key, delay, dist}]`) and the role keys
    새로고침 / 힐 / 이뮨 / 베르 (`PAGE_ROLES`) with their conditions; a role's 재사용 간격 entry
    is written into that key's `seconds` slot on read. Each hunt-loop tick presses at most one
    attack key whose target distance ≤ `dist` and whose `delay` has elapsed, in row order, after
    `runpending()`; `delay` 0 disables the row. Attack keys and page roles must not share a
    key; the same F key may be used on both pages. An old `roles.skill` config is migrated to
    attack key 1 on load.
  - The 귀환 role is removed: `KEY_RETURN` is always `None`, and the ber key stands in for it
    (`returnkey()`, since 2026-11-16). With a ber key set, `_checkrHp` runs during hunting and
    another player (or `checkhp.PNG`) → `doreturn` presses ber on the F1 page and stops. With no
    ber key it runs only in detect-only mode (log only). `huntloop` also checks
    `scanents()['players']` every tick (replacing the clan-mark check): any other player →
    press ber (if set) and `dostop()`, without waiting for the 2 s timer. `KEY_SKILL` / `SKILL_COOL` remain as
    a compatibility mirror of attack key 1 for `pit.py`.
- **Character panel** — `App.pollinfo()` shows name / LV / HP / MP / exp / AC / position / nearby
  counts every `INFO_POLL` ms through its own read-only `Mem` (`self.imem`), separate from the
  macro's `MEM`, so it works before Start.
- **`감지만` (detect-only)** logs the chosen target and nearby players without clicking or recalling.
- The old code is kept, unused by `main.py`: `huntloop_sweep`, `_checkmarks`. The sound
  ("소리로 칼질 감지") option, `soundwatch` / `FightGate` and `sound_record.py` were deleted on
  2026-11-17 at the user's request.
  `pit.py`, `memcalib.py`, `collect.py` and `sweep.py` import main's helpers
  and globals by name — do not rename them.

The "Architecture" section below describes the older forks (`oman.py`, `tell.py`, `turn.py`) and
`main.py` before this change (`attack1`, `isattack`, `checkrMp` no longer exist in `main.py`).

## The memory-based variant (`pit.py`)

`pit.py` is the one file that is **not** a copy-paste fork. It does `import main` and reuses
everything that did not change (log queue, `_arm`/PENDING timers, mouse movement,
`setattckinfo`, buff/transform/return actions, mark-template
image fallback, config load/save, the `App` GUI via subclassing). It redefines only
`_checkrHp`, `huntloop`, `runmacro`, and `App`. **`main.py` is unmodified** — a change there
propagates to `pit.py` automatically, and `pit.py` reads/writes main's module globals
(`main.ALIVE`, `main.PENDING`, …), so renaming one of those breaks `pit.py` loudly with
`AttributeError`.

Supporting files:

- `memread.py` — read-only ctypes wrapper. Opens the handle with `PROCESS_VM_READ |
  PROCESS_QUERY_INFORMATION` only; there is deliberately **no write function in the file**.
  Resolves CheatEngine-style pointer chains, validates every pointer step, and rejects
  values outside a sanity range (`hp > hp_max`, `hp_max = 0`, …) so a shifted offset reads
  as "could not read" rather than acting on garbage. N consecutive failures set `stale`,
  which permanently drops that session to the image path and logs once.
- `mem.json` — **all offsets live here, never in code**, because a client patch moves them.
  `base` is an RVA from the anchor module (ASLR makes absolute addresses useless across
  restarts). Unfilled values are `null`, which disables just that feature.
- `memprobe.py` — the go/no-go gate. `--list` to find the PID, `--pid N` to test whether
  `OpenProcess` and `ReadProcessMemory` actually work, `--watch hp,mp` to confirm values
  track the game, `--objs` to dump the object list and read off real clan names.
- `memcalib.py` — measures the world→screen transform instead of hardcoding a tile size.
  The hovered mob's identity is unknown, so it treats every mob as a candidate and solves
  the correspondence with RANSAC, then **verifies against the game itself** by moving the
  cursor to each predicted mob position and checking `GetCursorInfo` (statistical thresholds
  alone let ~2% of garbage fits through; the in-game check does not). Writes only the
  `screen` key of `mem.json`.
- `build_pit.bat` — builds `pit_auto.exe` plus console `memprobe.exe`/`memcalib.exe`.
  `mem.json` is copied **beside** the exe, never bundled, and an existing one is not
  overwritten. `build_exe.bat` (main.py) is untouched.

Two invariants worth preserving when editing `pit.py`:

1. **The cursor check is never removed.** Even with memory-supplied coordinates, `huntloop`
   still runs `main._probe()` before `main._settleclick()`. A wrong coordinate then produces
   no click at all, which keeps the failure mode identical to the image version.
2. **Memory is an accelerator, image is the fallback.** Every sensing helper is tri-state
   (`True`/`False`/`None` = could not judge), and `None` routes to `main.py`'s original image
   code. An empty object list counts as "reading nothing useful", not "nobody around" —
   otherwise the flee-on-hostile-clan safety would fail silently.

Settings live in `pit.json`, **not** `config.json`: `main.saveconfig` writes a fixed dict and
would silently drop any extra keys. `pit.py` reuses `main.loadconfig`/`saveconfig` for the
shared buff/role settings and keeps `mem`/`hp_pct`/`mp_pct`/`clans`/`target` in its own file.

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

## Conventions

Comments, `print()` output, and intent notes are in Korean; keep new ones in Korean to match. Dead code is kept commented out in place rather than deleted — it records alternate hunting strategies for different dungeons, so prefer commenting out over removing when disabling a behavior.
