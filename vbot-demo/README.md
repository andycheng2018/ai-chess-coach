# Chess Buddy × VBOT demo

[English](README.md) | [中文](README.zh-CN.md)

This local extension connects the existing Lichess/coach integration to a documented
VBOT EDU robot preset. It does not create another Lichess account, stream, or chess evaluator.
The path is **human move → existing Lichess stream → existing engine verdict → gesture or milestone dance → RCP preset**.

## Native controls in Chess Buddy

Open **Training Arena → VBOT companion**. The panel follows the selected training
match, so there is no game-ID entry or separate dashboard to coordinate. **Check robot**
is an explicit read-only SSH/provider/telemetry check; merely opening the app or polling
status never connects to the robot. Use **Preview without motion** first, then check
readiness and confirm the workspace/Stop controls before **Enable live reactions**.
The Mac's existing SSH key and exact rehearsed-preset verification remain required.

The panel shows requested, completed, resting, skipped, and paused states, including
the exact block reason. A successful gesture followed by failed readiness remains a
successful gesture with future reactions paused. Turning reactions off, finishing a
match, or selecting another match requires deliberate rearming for subsequent motion.
Old moves are never replayed. Turning reactions off is not an emergency stop; use the
VBOT app's Stop for a running action. The legacy `/vbot` desk remains available for
advanced diagnostics, but is no longer needed for ordinary play.

After a successful action, the helper may observe transient head busy/pending status
for at most 12 seconds, with no new goal submission. Every attempt rechecks all fresh
telemetry. Head faults, battery/system/posture failures, missing/stale telemetry, and
unknown action outcomes still stop immediately. Persistent head activity pauses the
session. Deploy the updated helper for this settling behavior to apply on the device.

## Rehearse on the Mac

1. Double-click **Open VBOT Chess Demo.command** in the repository root. It uses the
   existing Python/npm dependencies, opens Chess Buddy and `http://127.0.0.1:8765/vbot`,
   and binds a newly started backend to loopback. Keep the launcher Terminal open.
   If an older backend is running, stop that server with Control-C and reopen the launcher.
   `PORT` / `CHESS_SERVER_PORT` still select the backend port; the launcher uses that port.
2. On the demo desk, choose **Rehearsal**, enter an eight-character game ID
   (`AbCd1234` works for synthetic samples), and select **Arm rehearsal**.
3. Select **Sample good move**. Expect `rehearsed`, explicitly labeled synthetic.
   Select **Sample mistake**. Expect `skipped`. Neither contacts the robot.
4. In Chess Buddy, sign in and play against your existing training bot, including
   through your existing SenseRobot/Lichess connection. Put that actual game's ID
   in the demo desk and arm rehearsal **before making the next move**.
5. Play a move the existing coach classifies as `good`. Expect an event showing the
   game, move and verdict. Other classifications are skipped. Watch the reason if
   a move is skipped because it is stale, not yet in the bot stream, busy or cooling down.

The current coach emits `good`, `inaccuracy`, `mistake` and `blunder`. Book moves are
normally `good`; no new engine labels are fabricated. The policy can also accept
server-originated `book`, `excellent`, or `best` if the canonical coach adds them later.
Ordinary good moves randomly choose only locally rehearsed WAVE/look-left/look-right
presets, avoiding immediate repeats where possible. Handshake and stand-up are not
randomized until individually rehearsed; the helper never changes posture automatically.

ROCKYOU is reserved for a good move with one of these conservative signals:

- Net material gain of at least 200 centipawns (pawn 100, minor piece 300, rook 500,
  queen 900), measured through Stockfish's expected immediate reply, with evaluation
  at least -50. This filters simple exchanges, not every longer forced sequence.
- At least 200 centipawns better than the median of the previous five human turns,
  with current evaluation at least +100 and change at least four robust noise estimates.
- Last three human-turn scores sustain at least 150 centipawns improvement versus
  the previous five: all three exceed baseline by 100+, the end exceeds the start by
  50+, no step drops more than 25, and the robust noise gate also passes.

Scores already use the human mover's perspective for either color. The coach's
`evaluationBefore`/`evaluationAfter` compare best versus played choices from the same
position; their difference is not a game improvement. Compare `evaluationAfter`
across confirmed consecutive human turns instead. Require depth 12+; missing/low-depth
or mate-sentinel scores disable full dances. Profile changes, missing plies, takebacks,
game/player changes and rearming reset the baseline. Out-of-order results cannot add
samples. A detected major moment rebases the history even if skipped, so it cannot replay.
These are tunable deterministic heuristics, not p-values or a calibrated statistical test.

Full dances are disabled for fast clocks (initial + 40 increments <10 minutes),
under two minutes remaining, or unknown time control. These modes use rehearsed head
gestures only. Untimed games allow milestone dances. Full dances are at least three
minutes apart; gestures rest ten seconds after completion, dances twenty. Busy/cooldown
moves skip without a backlog, and a clock-suppressed major moment becomes a small gesture.
The engine verdict remains independent of spoken/LLM praise. Synthetic ordinary/major
examples are rehearsal-only and clearly labeled; a sample is not a real engine signal.

Both the frontend and backend must run locally on this Mac for this demo. A production
build normally points at Render through `.env.production`; that remote backend cannot
control this Mac's robot. Use the demo launcher/dev frontend and the local coach API.
Custom frontend ports need to be added deliberately to the local VBOT origin allowlist.

### SenseRobot fallback options

In **Connect SenseRobot**, open **Other ways to connect or continue**:
use a manual eight-character room code with the invited bot color, attach the same active
training-bot game after confirming it is shown on the physical board, or continue that game
on-screen. Existing-game attachment checks the signed-in account's active games and refuses
unrelated opponents or a changed game/position. Switching input does not create another game.
Reconfirm physical-piece agreement whenever the position or input mode changes.

The optional **Device IP and MAC** card stores router reference details only in this browser.
It does not test connectivity, configure Wi-Fi, verify physical-board synchronization, or
infer a direct LAN API. The public [SenseRobot FAQ](https://www.senserobotchess.com/pages/chess-faq)
documents Lichess account linking; a direct LAN game-control interface remains unverified.

## Prepare the robot package locally

The available release pairing is SDK `2026.9.23`, Aorta messages `2026.9.23`, EDU
messages `2026.9.24` and FlatBuffers `25.12.19`. Stage existing downloaded artifacts:

```bash
python3 vbot-demo/prepare_device.py --sdk-dir /path/to/vbot-lab/artifacts/edu-sdk-2026.9.24
python3 vbot-demo/robot_action.py
```

The first command verifies all four wheel hashes against `SHA256SUMS`, then copies the
Linux ARM64 wheelhouse into this ignored local directory. It never downloads or deploys.
The second prints a preview without loading the SDK or opening a device session.
The wheelhouse is ready locally after successful preparation; macOS wheels are not deployed.

The VBOT source references are `docs/compatibility.md`, `packages/aorta/python/README.md`,
`docs/robots/quadruped-common/connection.md`, `docs/interfaces/rcp.md`,
`docs/guides/rcp-presets.md` and `schemas/aorta/schemas/service/rcp/function_input.fbs`
in the matching VitaDynamics `vbot-lab` checkout. `actions/ROCKYOU.json` is the documented
dance; `actions/CHEER_R.json` and `actions/WAVE.json` are optional alternatives.
Availability and suitable starting posture must be checked on the actual robot.

## When the robot is online: verify and deploy

These are deliberate deployment steps for the intended `foot_quadruped` robot,
a verified address, public-key SSH, and explicit onsite control. The published
application target is **V1.6.0**. An unknown installed application version stays unknown. An application version is not the system image or SDK version.
Do not assume the wired default is the Wi-Fi address or change Mac network settings for this guide.

1. Set the verified target and verify existing key-based login. Check account,
   ARM64 architecture and Python 3.10+ before any installation:

   ```bash
   export VBOT_TARGET='vbot@YOUR_VERIFIED_ADDRESS'
   ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 "$VBOT_TARGET" 'whoami; uname -m; python3 --version'
   ```

   Stop on a timeout, host-key warning, wrong account or authentication failure.
   Follow the manufacturer's connection guide for trusted interactive fingerprint/key setup;
   do not disable host-key checking or embed the factory password.

2. Verify the existing native Aorta action provider without submitting a task:

   ```bash
   ssh "$VBOT_TARGET" 'ZENOH_SESSION_CONFIG_URI=/opt/vita/aorta/edu/edu_session.json5 timeout 15s /opt/vita/aorta/bin/aorta action info /rcp/execute_task'
   ```

   Require the documented action, cancellation support and exact SDK action schema.
   Schema equality confirms the interface, not installed preset availability or application version.
   Missing routes, packages or session files are blockers; do not change permissions or services.

3. Create a fresh dedicated application directory and transfer only the prepared files:

   ```bash
   ssh "$VBOT_TARGET" 'test ! -e /userdata/vbot/chess-demo && mkdir -m 700 /userdata/vbot/chess-demo'
   scp vbot-demo/robot_action.py "$VBOT_TARGET:/userdata/vbot/chess-demo/"
   scp -r vbot-demo/wheelhouse "$VBOT_TARGET:/userdata/vbot/chess-demo/"
   ssh "$VBOT_TARGET" 'python3 -m venv /userdata/vbot/chess-demo/.venv && /userdata/vbot/chess-demo/.venv/bin/python -m pip install --no-index --find-links /userdata/vbot/chess-demo/wheelhouse aorta-sdk==2026.9.23 aorta-msgs==2026.9.23 vbot-edu-msgs==2026.9.24 flatbuffers==25.12.19 && /userdata/vbot/chess-demo/.venv/bin/python -m pip check'
   ```

   If the directory already exists, **stop before the following transfer commands**.
   Inspect/reuse the existing deployment deliberately; preserve its request records and
   any unresolved-action marker. No system packages, startup files or services are changed.

4. Confirm clear space, a suitable posture, no conflicting task, and an onsite operator
   with the handset stopping procedure. Then deliberately test **one** selected preset:

   ```bash
   ssh "$VBOT_TARGET" '/userdata/vbot/chess-demo/.venv/bin/python -I /userdata/vbot/chess-demo/robot_action.py --execute --confirm-motion --preset actions/ROCKYOU.json'
   ```

   Require both the observed physical behavior and a matching JSON `terminal` event with
   `status: SUCCEEDED` and `errorCategory: 0`. Submission/admission is not completion.
   Confirm duration fits the demo and choose a different documented preset if appropriate.

5. On the Mac demo desk choose **Live**, enter this same SSH target, confirm application
   version if independently verified and the onsite checks, select the game ID, and arm. Make a **new** good move.
   Expect `requested` followed by `completed`; there is no automatic replay of old results.

### A narrowly tested preset with an unknown application version

The phone OTA label, `/etc/version`, and `aorta --version` do not establish the robot
application version. Never enter V1.6.0 merely to pass arming. For a supervised,
individually tested preset, a local ignored `device-verification.local.json` may instead
record the verified SSH target/fingerprint, exact action schema, matching successful
terminal result and operator-observed movement. Only that target/preset is eligible;
this does not certify the application release or other presets. Preserve the source
request record and only create this evidence after actual observation. The backend
checks the saved host key at arming and dispatch, while SSH still verifies the live host.

Each action now checks fresh BMS, system, body and head samples. The demo requires
at least 50% battery, unplugged, no BMS alarm, active FUNCTION with severity zero and
no power saving, advancing heartbeats, standing idle RL_TROT, and an idle head with
no pending action/fault. These are conservative demo gates, not manufacturer-wide
operating limits. A read-only check is available after deployment:

```bash
ssh "$VBOT_TARGET" '/userdata/vbot/chess-demo/.venv/bin/python -I /userdata/vbot/chess-demo/robot_action.py --check-ready'
```

Readiness failure sends no goal and disarms. Inspect onsite; stand the robot through
the app if appropriate and rearm deliberately. The helper never stands it automatically
or changes idle/power policies. Postflight readiness failure preserves the known
completed result but disables future dances. Audio verification is independent of motion.

## Mac-first physical-board rehearsal

Keep VBOT off while preparing the chess board. Start **Open VBOT Chess Demo.command**
and keep both the Chess Buddy game page and the demo desk open on the Mac. The current
celebration path receives accepted live engine results through the game page; it does
not independently analyze a game after that page is closed. Engine results arrive before
the separate generated wording, so a celebration does not wait for spoken commentary.

1. Finish any existing training game before opening a new SenseRobot room. In Chess Buddy,
   open **Connect SenseRobot** and follow Wi-Fi, matching Lichess account, room, and play.
   Wi-Fi/account confirmations are operator statements; the actual game connection is
   verified through Lichess. Scan the room QR or paste its link. Camera failures allow retry
   or the pasted-link fallback.
2. Choose an untimed training game for the first rehearsal. Make a physical move, confirm
   Chess Buddy shows the same position, and confirm SenseRobot executes the bot's reply.
   Verify the human color and opponent before progressing.
3. With VBOT still off, arm **Rehearsal** for this game and inspect real move events.
   Synthetic sample buttons exercise the rules without contacting the robot; they are
   labeled synthetic and cannot establish that a real move earned a celebration.
4. Only after board synchronization works, power VBOT on, inspect its volume in the phone
   app, confirm a clear level workspace and Stop procedure, and arm **Live** for this game.
   Observe an ordinary gesture and a genuine major-moment response. Fast games use brief
   head gestures; full dances require the documented evaluation/material conditions.
5. Finish the game, disarm, and start another game deliberately. Select and rearm for the
   new game; the previous game must not cause later celebrations.

Before the demo, exercise refresh/reconnect, a pending move followed by a takeback,
promotion choices, game finish, and a new game. Check that the board agrees with Lichess
and old moves do not replay robot actions. If analysis narrowly precedes the bot stream,
the backend waits at most 1.5 seconds for confirmation. A timeout, mismatched position,
changed arming session, or busy/cooling robot does not create a deferred action queue.
Native obstacle rejection requires inspecting and clearing the physical workspace; retain
the preset's checks. A successful terminal result and the operator's observation are
both needed to establish physical behavior and audible sound.

## Stops, uncertainty and replay

- **Disarm future dances** prevents new requests. It is not a physical emergency stop
  and does not claim to cancel a dance already running; use the onsite handset stop.
- Each action is bounded to 90 seconds. The device helper requests cancellation on
  timeout/interruption and waits up to five seconds for a terminal result. SSH loss can
  still leave an unknown outcome. The Mac disarms, records `unknown`, and never retries.
- The device helper writes the request identity before submission, rejects a repeated
  request ID and keeps `unresolved-action.json` while a task might be running. New
  requests are refused until the previous terminal result is observed. After an unresolved
  connection loss, an onsite operator must stop/inspect the task and deliberately resolve
  that marker before rearming; never delete it simply to bypass uncertainty.
- There is no backlog: moves during a dance/cooldown are marked handled and skipped.
  A given game/color/ply is handled at most once within the controller's bounded history;
  takebacks do not earn a second dance at that ply. Backend restart always disarms and
  discards eligibility records. Arm only after reconnecting and before new moves.
- Stale results (>30 seconds or computed before arming), another game, bot moves,
  mismatched positions, stale bot-stream state and imported history cannot trigger motion.
- Only local browser origins/loopback clients can call demo controls. No credentials,
  arbitrary shell command, Wi-Fi configuration, or SSH key is accepted by the dashboard.

## Offline checks

```bash
npm test
npm run build
python3 vbot-demo/robot_action.py
```

SDK codec checks can use the matching macOS SDK in a separate local venv; do not open
an `aorta.Node` for these checks. Source tests, codec serialization and rehearsals do not
establish robot compatibility, posture, observed motion, or live Lichess demo acceptance.
Run the generated-code/lifecycle witness with that venv's Python:

```bash
/path/to/matching-sdk-venv/bin/python vbot-demo/check_sdk.py
```

This witness mocks `Node`; it checks real FlatBuffers unions and result decoding,
duplicate/admission handling and cancellation cleanup without contacting a robot.
