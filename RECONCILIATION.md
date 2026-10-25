# main → add-llm-log reconciliation

Verified October 13, 2026. The merge direction is **main into add-llm-log**.
No default-branch merge or push is part of this reconciliation.

## Inputs

- Feature parent: `e47b67461b9492bec18029770b580f23e7459f02`.
- Default parent: `555e0f3725e7144858d57c217eaab28afdc56186`.
- Shared ancestor: `d7f9815654b9fcda2f920048406479c97eb9cf6f`.
- Approved newer UI stash: `840d31274288ee0a5cee74c0ef143bca9465a550`.

The local verification merge, `f96d7af`, combines both branch parents.
The newer UI is applied on top. Publication through the connected GitHub account
retains both original branch parents and the exact verified final source tree. GitHub Desktop stash backups remain available;
its separate main stash containing local coaching journal data is not applied.

## Integration decisions

- Coaching requests carry **both game ID and UCI move history**. Game ID keeps
  model attempts and learning records linked; history drives opening recognition.
- The server's opening recognizer, database, prompt additions, opening route,
  and takeback API are retained.
- The analysis library, depth/unlimited searches, journal, audit dashboard,
  SenseRobot setup, and Finder launcher are retained.
- The home hub, sidebar/navbar, profile, menu, dedicated coach window, and
  demo fixes from the approved stash are included.
- Opening labels/status appear under the live board and inside the new coach
  window. The new timeline shows synced/offline/unavailable journal status.
- The old coach/learning-panel markup is replaced by the approved coach-window
  layout; existing learning records remain in the same canonical journal.

## Preservation checks

- No tracked paths from either branch parent were lost.
- Before applying the UI, all 11 files changed only on main matched main exactly;
  38 files changed only on the feature branch matched it exactly. The history
  test file additionally gains an integration regression test.
- Four independent UI components match the stash bytes and file modes exactly.
  Profile differs only by trailing whitespace cleanup; CoachWindow gains opening
  and journal-status display. App.tsx combines both feature sets.
- Every CSS selector from the reconciled branches and approved UI stash survives.
- No unresolved index entries or source conflict markers; staged diff check passes.

## Verification

- `npm test`: **37 Node + 60 Python tests passed**.
- `npm run build`: TypeScript and production build passed. Existing Vite main
  chunk size advisory remains.
- Five new regression tests cover game ID plus opening history, backward
  compatibility for journal callers, opening metadata in linked model audit,
  the new window's opening/timeline display, and offline save status.
- Browser smoke check: new home hub loads, profile opens/closes, Analysis
  navigation opens `#analysis` library without creating an unintended board.
- Live `/api/coach/opening` recognizes the standard Ruy Lopez move sequence.

Physical SenseRobot hardware was not exercised during this branch reconciliation.


## Follow-up: demo work and retained stashes — October 25, 2026

The current branch remains `add-llm-log`. This follow-up creates local commits;
it does not merge into `main`, push, restart the application, or contact/control
physical robots.

### Current work committed in focused batches

| Commit | Scope | Independent staged-snapshot verification |
| --- | --- | --- |
| `128920a` | Account recovery, preserved sign-in, room-link recovery and selected-game stability | 120 Node + 159 Python tests; production build |
| `4814329` | Capture lessons, unrated intentional-blunder opponent, one-time win celebration, stochastic gesture expansion and 10% battery cutoff | 126 Node + 193 Python tests; production build |
| `c9ccda0` | Passive Mac network recognition, remembered robot IPs and SSH identity continuity | 130 Node + 213 Python tests; production build |

Each snapshot was materialized from the Git index and tested separately, so
later working-tree changes could not hide a dependency in an earlier commit.
The final feature tree passes **343 tests** and the production build. The existing
Vite large-chunk advisory remains. Staged credential-pattern checks and
`git diff --cached --check` passed. The backend entrypoint retains its executable
file mode.

### Stash reconciliation

- UI stash `840d31274288ee0a5cee74c0ef143bca9465a550` was already deliberately
  restored in `eb22eeb` (the academy UI integration documented above). The current
  navbar/sidebar retain those components, HomeHub/MenuModal add live-game
  recovery, ProfileModal has whitespace cleanup, CoachWindow adds Luna chat and
  journal/opening state, and App/CSS retain newer integrations. Reapplying the
  older snapshot would regress current behavior; no older UI source was reapplied.
- Journal stash `f762b21de58bd04868c669caec4b1336efb4c33d` contains 130 valid
  records absent from the current local journal. Its exact bytes were recovered
  to ignored, owner-only
  `logs/stash-recovery/f762b21de58bd04868c669caec4b1336efb4c33d.jsonl`.
  The active `logs/coach_logs.jsonl` was not rewritten or replayed, so historical
  snapshots cannot override newer accepted learning records.
- Both original GitHub Desktop stashes remain intact as recovery references.
- Local coaching logs, Wi-Fi/LAN address memory, robot verification/rehearsal
  records, verification backups and credentials are excluded from these commits.
  Verification backup/temp patterns are now ignored explicitly as well.
