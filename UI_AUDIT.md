# UI audit — October 9, 2026

## Scope and evidence

Source inspection and browser checks of the analysis board, the signed-out
landing page, and the SenseRobot setup entry/help screen. Browser checks used
the local web app and its running Stockfish backend; no model calls, Lichess
games, camera requests, or physical-board confirmations were needed.

## Findings fixed

| Finding | Cause | Change / verification |
| --- | --- | --- |
| Dark stripe through the evaluation bar | An opaque score label was pinned at the midpoint, covering the actual white/black fill. | Removed the overlay; the number remains in the Stockfish panel. Browser checked both orientations with a negative score. |
| Bar snaps back to equal while changing depth | Every search cleared the completed result and rendered a default 50% fill. | Keep the completed evaluation for the same position during another search. Browser showed the score and fill remaining visible during “Updating analysis…”. |
| Pausing erases the evaluation | Disabling the engine also cleared its result. | Preserve the last result for that position. Moving to a different position while paused shows an unknown pattern, without an old score or arrow. |
| Clicking the selected position launches another search | The search depended on the workspace object rather than the actual position/history. | Key requests by root FEN and move sequence. Repetition history remains part of the identity. |
| Very short windows shrink the board too far | Desktop column width used viewport height without a lower bound. | Bound the preferred column width. At 900×450, board width improved from 156px to 250px. The dialog remains scrollable. |
| Duplicate arrow marker IDs across boards | Main, review, and analysis boards reused global SVG IDs. | Give each board its own IDs. A render test verifies two simultaneous boards have eight distinct definitions and reference their own arrowheads. |
| Invalid PGN displays parser internals | The UI forwarded the chess library's raw grammar error. | Give readable guidance; browser verified the previous position survives an invalid import. |

Engine continuations now include move numbers so a Black-to-move line is
distinguishable from a White-to-move line.

## Checks

- White/Black orientation: negative White-perspective score stayed unchanged;
  White fill moved between the bottom and top of the bar correctly.
- Checkmate: imported Fool's Mate showed “Black wins” with zero White fill.
- Insufficient material: bare kings showed “Draw” and equal fill.
- Paused engine / new position: unknown fill, no score or continuation from the
  previous position.
- Reselecting the current position: evaluation remained available.
- Mobile at 390×844: square 326px board; dialog content did not overflow
  horizontally. SenseRobot help also fit its dialog width.
- Keyboard: Tab from the last import control wrapped to the close button;
  Escape closed analysis and restored focus to its launch button and body scroll.
- Automated checks: 26 Node tests and 49 Python tests; TypeScript check and
  production build. The existing Vite bundle-size warning remains.

## Limits

This is a focused UI audit, not complete coverage of every authenticated game,
report, device, or browser. Physical SenseRobot play, camera scanning, and a
live game running behind the analysis dialog still need device/session testing.
PGN import still imports its main line; export includes created variations.
