# Saved analysis library verification

Verified locally on 2026-10-09.

## Implemented

- One browser library for games and editable analysis pages, with legacy draft
  recovery. Each page retains its tree, selected move, orientation, board layout,
  panel dimensions, and search settings. Autosave and manual Save use the same
  persistence path. Save a copy creates an independent page.
- Library navigation with Cards / List / Compact, search, New analysis, archive,
  and Restore. Individual hash URLs support reload and browser Back / Forward.
- Save game snapshots all played moves, known players/result, and Lichess link.
  Refreshing the snapshot preserves branches and promotes actual moves to the
  exported main line. A saved copy is detached from future snapshot refreshes.
- PGN file download, preserving variation branches. PGN import reads main line.
- Exact depth 1–128, or uninterrupted unlimited search with Stop / Resume.
  Presets and long searches share Stockfish formatting and position validation.
  Long searches use one separate stoppable engine so they do not hold the shared
  coaching-engine lock indefinitely. Session ownership, replacement, shutdown,
  and a renewable 12-second lease bound abandoned work.
- Board left / Board right / Stacked. Arrow dividers support pointer drag,
  keyboard arrows, and Home / End. Stacked divider controls board size; phone
  layouts stack sections automatically.

## Automated verification

`npm test`: **33 Node tests + 55 Python tests passed**.

Coverage includes independent saves, stale-tab conflict detection, quota errors
preserving previous bytes, legacy branches, archive/restore, completed-game PGN,
played main-line promotion, client abort sending Stop, exact depth without a
clock cap, unlimited stop, worker lease expiry, ownership, replacement, terminal
positions without engine startup, and invalid depth rejection.

`npm run build`: TypeScript checks and Vite production build passed. Vite reports
its bundle-size advisory for the main chunk.

## Browser / runtime verification

Used the running local Vite app and real backend / Stockfish 19:

- Created “Opening ideas,” played e4, saved, created an independent copy, played
  e5 in the copy. Library showed original: 1 move; copy: 2 moves.
- Reloaded the copy's individual URL: tree, selection, settings, and layout
  returned. Browser Back reached library; Forward reopened the copy.
- Cards, List, Compact rendered; archive then Restore recovered the copy.
- Real exact-depth search completed at **depth 8**. Real unlimited search reached
  **depth 35**, Stop paused it and retained the evaluation. Process inspection
  showed only the bot and shared finite-analysis engines remaining afterwards.
- Pointer drag changed board share 45% → 53%; keyboard resizing changed engine
  height 380 → 400px; stacked board size 440 → 460px.
- Tested 390 × 844: modal client width and scroll width both 388px; board 356px,
  no horizontal overflow. Reset viewport afterwards.
- Download PGN produced “Opening ideas copy.pgn”; contents were a valid standard
  PGN main line `1. e4 1... e5 *`.

Screenshot: `chess-analysis-library.png` in the Codex visualization output folder.

## Boundaries

Saves are browser-local, not cloud/account sync. Library limit: 100 pages, with
an explicit error rather than silent deletion. Existing per-page limit remains
512 moves. Live game saving is covered through snapshot logic and PGN tests;
this verification did not start a new Lichess game or use physical SenseRobot
hardware. Analysis is Stockfish-only and does not call the language model.
