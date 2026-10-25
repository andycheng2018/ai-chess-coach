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
Ordinary good moves make a fresh random draw from eligible, locally rehearsed gestures:
wave; look left/right/forward/up/down; handshake/left handshake; right/left high-five;
and approving yes. No shuffle bag or ordered rotation is used. Only an immediate repeat
is excluded when an alternative is available. Moves arriving during an action or rest
are skipped permanently, never queued or caught up later.

Each exact target/preset needs an operator-confirmed successful rehearsal and a measured
terminal duration greater than zero and at most 10 seconds before entering live normal
reactions. A documented name alone establishes neither duration nor installed availability.
Unrehearsed or longer presets stay out of the live pool; the companion's **Good-move gestures**
list shows readiness. Fast/low/unknown clocks select only the head presets. The helper
never stands the robot automatically or bypasses the preset's own transitions/checks.

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
minutes apart; gestures rest five seconds after completion, dances twenty. Busy/cooldown
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
at least 10% battery, unplugged, no BMS alarm, active FUNCTION with severity zero and
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

### Blunder reaction

A canonical coach **blunder** selects the documented `actions/GRIEVANCE.json`
performance. Mistakes and inaccuracies do not trigger it. This is a body performance,
not a brief head gesture: fast/unknown clocks and time trouble suppress it; it shares
the three-minute performance interval and 20-second rest with milestone dances.
Busy/cooldown moves are skipped, never queued. A blunder also resets the improvement
baseline, so it cannot accidentally become a celebration.

Live sad reactions require an exact successful, physically confirmed rehearsal in
`device-verification.local.json` for the selected SSH target, with a matching saved
host key. Merely adding it to the helper allowlist does not verify installation or
behavior. Until rehearsed, the native companion shows that it is pending and live
blunders are explicitly skipped. Rehearsal mode can preview a synthetic blunder
without contacting a robot. All existing arming, preflight, result and postflight
checks still apply.

### Join a SenseRobot room from the live board

Select **Join room link** beside the live-board match ID. Create a room on SenseRobot,
paste its invitation, and check the preview: the invitation's `color` belongs to the
coach bot; your player takes the opposite color. Select **Join as black/white**.
The app recovers an already joined exact room before attempting acceptance, verifies
the account/opponent/color, and refuses a different returned game ID. Switching to
this room leaves other games open. Reopening the currently selected room preserves
its live stream; no repeated acceptance or automatic retry is sent.

Joining on Lichess does not establish physical synchronization: confirm SenseRobot
has entered the same game before moving pieces. This action can open a supplied room
while another game is selected; the longer setup wizard retains its original checks.

### Show the current game QR

**Show game QR** shares a public game-viewing URL with an explicit board orientation.
It does not claim a seat or create a SenseRobot invitation. The dialog makes this
separation explicit and links to **Join a SenseRobot room link**. It does not promise
that scanning a started game's viewing QR will enroll SenseRobot in that game.
Use the robot's Create Room flow for a new room-based physical-board session. A QR or error screen alone does not establish that an existing physical game is inactive. The room parser rejects
viewing links instead of silently presenting them as invitations.

QR generation is local, with copy/save, finished-game labels, matching game-ID casing,
and Escape/focus handling. Player tokens and private seat URLs are never encoded.

### Invitation screen versus actual physical play

A SenseRobot invitation screen can remain visible while physical moves and replies
reach Lichess. Treat the screen as a display state, not a definitive disconnection
signal. Compare the exact game ID and move sequence before creating another room.
Multiple open games can otherwise make the QR room and actual playing game differ.

In SenseRobot mode, the board displays Lichess connection separately from a person's
physical-play confirmation. The confirmation is informational, does not gate chess
or arm VBOT, and requires a human move followed by a bot reply in the displayed line.
It remains local to the current view and exact game/account/move branch; a changed
account, game, rewind, divergence, or reload requires confirmation again. App move
history by itself never proves physical movement.

### Connection freshness and live-session lifetime

After confirming the workspace and onsite Stop, **Check & enable live reactions** performs
one fresh read-only readiness check and then binds the selected game. A separate manual
precheck is optional. A failed check or a match change during that check leaves reactions off;
no automatic retry or rearming occurs. The 30-second probe lifetime applies to starting a
session, not to an already-enabled match. Per-action preflight and postflight checks remain.
Selecting the same game only opens its board; it does not set the game to recovering or
implicitly arm the robot. Switching games and terminal results turn reactions off.
Disarm events record whether this was an operator action, game change, or game completion.

### Joining a room after sign-in expires or an account check fails

The **Join room link** dialog needs a verified player account and a valid original
invitation. Use its **Sign in with Lichess** action if signed out, or **Retry account check**
if a temporary lookup failed. Account lookup has a bounded timeout; network errors and
rate limits preserve the existing login. Only an authentication rejection clears it.
A valid invitation is saved locally for up to 30 minutes across OAuth and reopened afterward.
Signing in never accepts the room automatically: verify the displayed bot/player colors,
then choose **Join as black/white**. The example placeholder is not a supplied invitation.

## Capture Practice tutorial

Open **🎯 Capture Practice** near the top of Chess Buddy. Four authored one-move
positions teach pawn/rook/knight captures of a queen and a bishop capture of a rook.
Use **Show me the capture** for a hint arrow, then click or drag the capturing piece.
Incorrect moves keep the exercise available; a correct capture shows the piece and points.
The exercises use the on-screen practice board and do not alter your Lichess game.

For robot rewards, turn off any other VBOT session, confirm the workspace/Stop controls,
then choose **Check & enable dance rewards** inside the tutorial. A server-validated
correct capture requests the complete `actions/ROCKYOU.json` preset. Practice rewards
have their own explicit session: they do not fabricate Stockfish records or need a live
Lichess game. The normal game's three-minute major-signal downgrade does not apply to
these authored rewards; existing busy checks and 20-second post-dance rest still apply.
Repeated submissions of the same lesson attempt return its saved result without another
robot request. Old solved attempts never replay after enabling rewards. Closing the
practice dialog turns off its future rewards; use the handset Stop for current movement.

### Explicit demo approval for untested gesture presets

The owner can explicitly approve known catalog presets for immediate demonstration
without writing false physical-verification records. Such approval is scoped to the
saved robot target and an expiry time; the current demo approval lasts two hours.
The UI distinguishes these entries as **Demo enabled · not individually rehearsed**.
SSH identity, provider/schema, battery, posture, system, head and terminal-result checks
still apply. A missing or aborted preset is not retried automatically.
Jump presets (`HAPPY_LITTLE_JUMP`, `HAPPY_JUMP`, `JUMP_IN_PLACE`) receive four times the
random-selection weight of other eligible gestures. There is no ordered rotation or queue.
Fast/low/unknown-clock games continue to use only head gestures. Names do not establish
installed availability, duration or amplitude.

### Intentional-blunder opponent

On the live Training Arena board, choose **Opponent mode → Demo: intentional blunders**. The server enables this only for the exact active game with Lichess-confirmed `rated: false`; other games and the normal strength setting stay unchanged. The choice resets when the game ends or the coach server restarts. It applies from the next bot decision, not a move already being calculated.

The bot offers legal queen/rook captures when possible and otherwise brings its queen into play; this behavior has no calibrated Elo. A canonical good/book/excellent/best verdict at depth 12+ and at least two net material points after the expected reply qualifies a big capture for Rock You, even if the player is still losing. Demo captures bypass the usual three-minute major interval; busy actions, the 20-second post-dance rest, fast/low/unknown clocks, explicit live arming and robot readiness remain enforced. Skipped captures are never queued. Switching back to Normal practice restores the selected strength.

### Win celebration

Enable live VBOT reactions before the game ends. A fresh final result in the existing Lichess bot stream that names the human player as winner requests **actions/ROCKYOU.json** once, then turns reactions off. Checkmate, resignation and timeout wins qualify; losses, draws, aborted games, stale/unconfirmed results and practice sessions do not. Client notifications carry only game/session identity, never an authoritative winner. Preview mode shows the victory event without contacting VBOT.

If a reaction is already running or resting, the companion shows a cancellable victory wait (up to two minutes). Turning reactions off or switching games cancels it. The normal three-minute major interval and running chess clock limits do not suppress a victory after the game has ended; action completion/rest, verified SSH identity, fresh robot preflight, terminal result and postflight checks still apply. A readiness refusal or unknown outcome disarms without retry. The browser result and bot stream can arrive in either order; the controller allows 15 seconds for the canonical result before turning off without a dance. Reconnects and duplicate terminal events cannot replay a handled win.

### Remembered networks and robot addresses

The native **Robot connection · remembered networks** panel shows the Mac's current LAN and saved robot addresses for that network. Choose an address or enter one, optionally label the network (for example Home or Rich's hotspot), then **Remember for this network**. A successful **Check robot** also learns the address automatically, even if the robot is currently lying down or otherwise not ready for motion. A manually saved candidate is marked **needs check** until a strict SSH/helper check confirms the robot.

On macOS, recognition reads the default physical LAN interface, local IPv4/subnet, gateway, cached gateway MAC and Wi-Fi name when available. It does not scan devices, reconnect Wi-Fi, flush caches or change network settings. The key uses the router MAC and subnet/gateway; SSID is a fallback when the router identity is unavailable. The Mac's DHCP address is excluded, and identical subnets on different routers stay separate. If neither SSID nor router identity is available, the app offers manual entry without guessing a network match.

Only a saved candidate for the detected network is filled automatically. Unknown networks do not inherit the last hotspot's address. A network transition clears readiness and turns reactions off, including any waiting win dance; explicit checking and onsite confirmation are required again. Before dispatch, the controller rechecks the network. No saved address automatically arms or triggers movement, and no background robot SSH probes are performed. If DHCP changes the robot's address, enter/check the new address once; old addresses remain in the network's selectable history.

The controller pins SSH to the already-trusted robot host identity using `HostKeyAlias`, with `StrictHostKeyChecking=yes` and existing public-key authentication. It does not accept a new robot key, change `known_hosts`, copy private keys or embed passwords. A successful check can carry that same robot's rehearsed preset records to another remembered IP; candidate addresses and a matching subnet alone cannot. Application-version and device preflight gates remain independent. Temporary approvals for unrehearsed presets keep their original target/expiry limits.

Network memory is kept locally in ignored `vbot-demo/networks.local.json`, with atomic saves and owner-only permissions. It contains network labels/router fingerprints and address history, not Wi-Fi passwords. Malformed data is preserved and disables automatic selection rather than being overwritten. This is app connection memory, not a modification to the Mac's saved Wi-Fi networks.
