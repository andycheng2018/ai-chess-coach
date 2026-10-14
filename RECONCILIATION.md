# main → add-llm-log reconciliation

Verified October 13, 2026. The merge direction is **main into add-llm-log**.
No default-branch merge or push is part of this reconciliation.

## Inputs

- Feature parent: `e47b67461b9492bec18029770b580f23e7459f02`.
- Default parent: `555e0f3725e7144858d57c217eaab28afdc56186`.
- Shared ancestor: `d7f9815654b9fcda2f920048406479c97eb9cf6f`.
- Approved newer UI stash: `840d31274288ee0a5cee74c0ef143bca9465a550`.

The first reconciliation commit, `f96d7af`, is a merge with both branch parents.
The newer UI is applied on top. GitHub Desktop stash backups remain available;
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
