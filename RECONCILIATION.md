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


## November 8, 2026: consolidate recent Claude and Codex work

- Destination: `add-llm-log`, initially `b5c0aab` with a clean working tree.
- Refreshed origin refs before comparing branch ancestry. The Android/server,
  selectable bot accounts, VBOT Studio, MCP/Qwen dashboard, and speech changes
  were already ancestors of the destination; they were not reapplied.
- Merged `claude/dog-dance-variety-551640` (`dfcd5f6`) with merge commit
  `09ebc2a`, retaining the feature branch's original authorship. Git resolved
  the merge without conflicts. Both source worktrees were clean.
- Updated two fixed-Rock-You expectations for varied demo celebrations. Added
  offline coverage for no immediate repeats, rehearsal-only live pools, single
  candidates, session reset, and separated milestone dispatch. Existing capture
  reward and victory tests continue to cover their Rock You behavior.
- Validation: 260 Node tests passed; 600 Python tests ran successfully with six
  skips. Chess Buddy and VBOT Studio production builds both passed.
- Every local and fetched remote branch tip is an ancestor of the consolidated
  destination. All three stashes remain intact. The most recent stash contains
  generated Android assets and was not replayed over current builds.
- This is a local source integration only: no robot commands, deployment,
  tablet installation, backend restart, or remote push was performed.


## November 8, 2026: final Android release consolidation

Refreshed origin and verified all 27 recorded local and remote tips below are ancestors
of the release. Reconciled the remaining Android merge commit without source conflicts.

| Ref | Audited tip |
| --- | --- |
| `refs/heads/add-llm-log` | `5a74748b04054382de87bc50bc3b8a885f64af6d` |
| `refs/heads/claude/dog-dance-variety-551640` | `febc27d2e0636185643c80f3a41f8d6c61244956` |
| `refs/heads/claude/vbot-agent-mcp-integration-3e1ae9` | `73c33975d6a2e12e0229ff1000c188a760fbb67f` |
| `refs/heads/codex/android-standalone` | `febc27d2e0636185643c80f3a41f8d6c61244956` |
| `refs/heads/codex/android-tablet` | `1e7bd50e5cd2f81e9db61e07e20f418ce822ca10` |
| `refs/heads/codex/merge-coaching-workspace` | `6941a00170fe69e5072962a6b2a53e8c03ca8202` |
| `refs/heads/codex/merge-luna-chat` | `d303a54a971d7dcbc1bfe6fd50722111f856592a` |
| `refs/heads/codex/merge-practice-and-celebrations` | `4814329f2cab97c8e53d15019deaf29661a31cf5` |
| `refs/heads/codex/merge-robot-live-integration` | `128920ac00cb67c84743a2e353d9f968ed260b7e` |
| `refs/heads/codex/merge-robot-network-memory` | `d464d445809ef64b0aa96c17cdee798c93909658` |
| `refs/heads/codex/merge-room-discovery` | `f2841930d9336182a17eca22e1f688b31fb92494` |
| `refs/heads/codex/vbot-app-scaffold` | `75fad97c89c8d7d1c6a9ac4aa908f517b4f14cdb` |
| `refs/heads/main` | `555e0f3725e7144858d57c217eaab28afdc56186` |
| `refs/remotes/origin/add-llm-log` | `50ed0157fcfc6b33aa566a46cab66ac46493f83a` |
| `refs/remotes/origin/claude/dog-dance-variety-551640` | `7982c9a2586690cfb018095c3e02f80819ed9392` |
| `refs/remotes/origin/claude/vbot-agent-mcp-integration-3e1ae9` | `b5c0aab68e74d2a979b46b81c6fb7c8c2eeb1a9f` |
| `refs/remotes/origin/codex/android-standalone` | `b112822ff4e291e6eeb8d543785519440975d0fe` |
| `refs/remotes/origin/codex/merge-coaching-workspace` | `6941a00170fe69e5072962a6b2a53e8c03ca8202` |
| `refs/remotes/origin/codex/merge-luna-chat` | `d303a54a971d7dcbc1bfe6fd50722111f856592a` |
| `refs/remotes/origin/codex/merge-practice-and-celebrations` | `4814329f2cab97c8e53d15019deaf29661a31cf5` |
| `refs/remotes/origin/codex/merge-robot-live-integration` | `128920ac00cb67c84743a2e353d9f968ed260b7e` |
| `refs/remotes/origin/codex/merge-robot-network-memory` | `d464d445809ef64b0aa96c17cdee798c93909658` |
| `refs/remotes/origin/codex/merge-room-discovery` | `f2841930d9336182a17eca22e1f688b31fb92494` |
| `refs/remotes/origin/codex/vbot-app-scaffold` | `75fad97c89c8d7d1c6a9ac4aa908f517b4f14cdb` |
| `refs/remotes/origin/feature/vbot-qwen` | `3c7809d07d80a5df0f69c36b13519e4a1f56f490` |
| `refs/remotes/origin/main` | `555e0f3725e7144858d57c217eaab28afdc56186` |
| `refs/remotes/origin/opening-recognition` | `06d564af2f2fa635a54d1e2cb48d7b138ec608fd` |

Imported ten uncommitted files from the Claude MCP worktree: Studio pairing QR,
Android camera/scanner wiring, tests and terminal QR helper. Timestamped backups
are in ignored .local/full-integration-backup-20261108-154903. The source worktree
changes and all three stashes remain preserved; the other Claude worktree was clean.
Old UI stash work was previously reconciled. Private journals and generated assets
were not reapplied. Studio now declares the native Browser plugin as well as scanner.

Includes visible live-game Simple Demo reaction controls, cloud routing, hosted
robot address trust, Studio cloud controls, Qwen sessions, bot account selection,
Test Dashboard, and rehearsed dance variety. Validation: 267 Node tests passed;
649 Python tests ran with six skips and no failures; both web builds passed.
Android compilation, pinned signature verification and emulator checks run in CI.
This audit does not claim tablet installation, robot motion or venue acceptance.
