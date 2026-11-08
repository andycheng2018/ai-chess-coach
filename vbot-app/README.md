# VBOT Studio (working name)

The dog's own app: connect, browse faces and actions, write shows, and run them from a
stage view. It has no chess, Stockfish or Lichess dependency.

## Status

| Piece | State |
| --- | --- |
| App with simulated dog (all five screens, saved shows, fault rehearsal) | Works in a browser |
| Live face control: app → local controller → `robot_face.py` | Ran on the dog on 2026-11-03, from a Mac: Mood Swing played and the operator saw the faces. **Stop future cues** also worked: the next cue never started and the dog confirmed the screen release. Only those six faces have been played. Lost connections and recovery are only tested against stubs. |
| Head and body presets, and bounded step/turn moves (`robot_studio.py`) | **Deployed to the dog. Presets are tested against fakes only. Turns were watched on one dog on Nov 5 2026; steps did not move it and are being retried (see [Basic moves](#basic-moves-run-on-one-dog)).** Off unless the operator ticks all three onsite confirmations when connecting. No preset is marked rehearsed or confirmed because of it. See [Motion](#motion-optional-untested-on-the-dog). |
| Navigation | Deliberately absent from the live path |
| Speech | Placeholder. No verified backend. |
| Cloud | Controls the dog through the hosted server after pairing with its key, by paste or by scanning `show_pairing_qr.sh` on Android. No hold-to-drive, and the session ends if Studio stops checking in. |
| Android app | Project in `vbot-app/android` (`com.andy.vbotstudio`). The controller and pairing are tested against fakes. CI release builds verify the pinned permanent signature and run the embedded controller on an emulator; physical-device verification is separate. |
| Player tracking | Types and a staged screen. No real perception feed, and no 3D. |

## Run it

From the repository root:

```sh
npm run vbot:dev         # Dev server on http://localhost:5180 (simulated dog works on its own)
npm run vbot:controller  # Local controller on http://127.0.0.1:8791, needed only for the real dog
npm run vbot:build       # Typecheck and build into vbot-app/dist
```

After a build, `npm run vbot:controller` also serves the app at `http://127.0.0.1:8791`.

Tests never contact a robot. `npm test` includes them, or run them directly:

```sh
node --test tests/vbot_app_*.test.mjs
.venv/bin/python -m unittest tests/test_vbot_app_control.py
```

## How control works

```text
Screens
  → DeviceTransport (src/transport/types.ts): one interface
      ├ FakeTransport        simulated dog, no network
      ├ LocalFaceTransport   server/vbot_app_server.py → vbot_app_control.py
      │                        → SSH with pinned host key → vbot-demo/robot_face.py → display service
      │   On Android, the same adapter and controller run inside the APK: StudioPlugin
      │   → studio_backend.py → vbot_app_control.py → StudioHost's pinned SSH → robot_face.py
      └ CloudTransport       the same protocol, through the hosted server
```

On Android there's no local network listener, so other apps on the device have nothing to connect to.

- **Preview isn't on the transport.** It renders the pure `buildTimeline`, so a preview can't reach a device.
- **A face-only connection is limited to the display.** `robot_face.py` contains only display routes and read-only
  health subscriptions. It has no action client, publisher, or motion route, and a test enforces that.
- **One owner at a time.** `robot_face.py` and `robot_studio.py` take the same `controller.lock` as `robot_action.py` and honors
  `unresolved-action.json`. While a face session is open, a chess reaction or show is refused, and the reverse
  is also true. An idle session closes after 150 seconds to free the lock.
- **Commands are single-use.** IDs are recorded before acting, on the controller (`.local/vbot-app/commands.jsonl`)
  and on the dog (`requests/face-<id>.json`). A duplicate returns the recorded result.
- **Unknown stays unknown.** A lost answer stops the show and is never retried. A restart or reconnect
  checks status and replays nothing.
- **Faces don't cover warnings.** If the dog reports a system or battery warning, or that state stops arriving,
  a new face is refused. Charging and diagnostic assets can't be played.

Manufacturer-app and RCP control don't use this lock. Before a face session, make sure nothing else
is driving the display: direct display writes sit outside RCP's layer bookkeeping.

## First live face test

This writes one file to the dog, so it needs explicit authorization and the dog in front of you. It doesn't
change services, networking or packages, and it doesn't move the dog.

```sh
export VBOT_TARGET=vbot@<current dog address>
scp vbot-demo/robot_face.py "$VBOT_TARGET:/userdata/vbot/chess-demo/"
npm run vbot:build && npm run vbot:controller
```

Open `http://127.0.0.1:8791`, choose **Real dog, through this computer**, enter the address and connect.
Then run **Mood Swing** from Stage. Connection refuses a dog whose SSH key isn't already trusted on this
computer. Host-key checks are never bypassed.

## Motion (optional, untested on the dog)

Faces alone are the default. Motion exists so a show can mix faces with the head and body presets
`robot_action.py` already supports. It is **not** a rehearsal record of anything.

- **Arming.** On a real-dog connection, tick all three boxes (someone is with the dog, it is standing, the
  area is clear) and press **Connect with motion**. The controller then runs `robot_studio.py --serve --motion
  --confirm-motion`; anything short of three exact `true`s is refused before the dog is contacted. The
  confirmations are never stored. Motion lasts for that one connection and lapses with the dog's 15-minute
  session. Reconnect to re-arm.
- **One session, one lock.** `robot_studio.py` serves faces and presets from a single process, so there is no
  hand-off between helpers. It reuses `robot_action.py`'s guarded path as is: fresh readiness before every cue,
  the static probe, durable request records, the unresolved-action lock, terminal-result and postflight checks.
  It adds no scheduler and none of the gates are loosened.
- **Faces never overlap a preset.** Presets drive the display themselves (their own expression, lights and
  sound), and the vendor guide says not to mix control owners. Before a preset starts, any face this session
  put up is released, and a failed release refuses the preset. You can't choose the face during a preset.
- **Only approved presets.** The same 17 as `robot_action.py`; a test keeps the lists equal. Head presets are
  `atom/look_*`; everything else is a body preset.
- **A clean finish is the only way to continue.** A preset the dog refuses for readiness (for example, it isn't
  standing) stops the show and ends the motion session, as `robot_action.py`'s own session does: inspect the dog
  and reconnect with the confirmations. A preset that doesn't finish cleanly, or whose outcome is unknown, also
  stops the show and shows **Outcome unknown**. Neither is retried. Plain protocol refusals (a stale or expired
  command, an unapproved preset) stop the show but keep the connection.
- **Stop.** **Stop future cues** works between presets. It does not stop a preset already running; use the
  handset Stop.
- **Not yet possible.** Choosing a face *during* a head preset would need a custom graph, and the head
  parameters of `atom/look_*` aren't documented, so inventing them would be an unrehearsed motion request.
  That needs the preset files read from the dog first. (Turns below do carry a face, because they use
  a custom graph with explicit values rather than a preset.)

### Basic moves (run on one dog)

A move is one short, finite step or turn, sent as a single `BaseActionCommand` (`ROTATE`) inside a small custom graph, so a face can be on screen for its duration. (Steps are different, see below.) This is the vendor docs' own
composition pattern: the face is a background (`DAEMON`) node, the move is one finite node with a timeout, and
a `BARRIER` releases the face. Moves need the same three confirmations as presets.

| Move | Amount | Notes |
| --- | --- | --- |
| Step forward / back | 0.25 m | Vendor `atom/move_param.json` template. **Unconfirmed: the plain-command version did not move the dog.** |
| Step left / right | 0.20 m | In the dog's frame. |
| Turn left / right 10° (nudge), 30° or 90° | ±0.5236 / ±1.5708 rad | Left is counterclockwise. The docs leave the sign to the provider, so this was checked onsite (Nov 5 2026): the left 30° turn went counterclockwise. Right uses the opposite sign and was not separately watched. |

- **The amounts are ours.** The vendor docs publish no safe range for steps or turns, so these are small bounds
  chosen here and enforced on the dog. The app and controller only send a move's *name*, never a number, so
  neither can ask for a bigger one. A test checks the table stays small.
- **Move pad.** Under **Actions**, a 3×3 pad of bounded moves. Hold **↺** or **↻** to keep turning in 10° turns, one
  command at a time (about 2 s each), each sent only while the button is still held; letting go can overshoot by the
  one turn already underway. Other buttons send one move per tap. This is the proven path: the turns were watched on
  the dog. A test covers every way the chain stops (release, pointer-cancel, blur, hidden page, a non-clean result, a
  12-turn cap).
- **Drive pad (hold to move), new and not yet seen working.** Hold a button and the app streams velocity frames
  (every 100 ms) to the dog; let go and it stops. This is real continuous velocity, published to
  `/locomotion/velocity_command` as a `Twist` by `robot_studio.py` on the dog. The vendor docs say a direct
  publisher doesn't inherit the ROS bridge's timeout and that no zero-on-dead-man is configured, so the dead-man is
  built into the dog-side helper rather than trusted to the app or the network:
  - The helper publishes the command **only while fresh frames keep arriving** (a command older than 0.5 s is stale),
    from its own thread, so a half-delivered frame or a stalled read can't hold the stop up. A test proves the zeros go
    out while the reader is still stuck.
  - **Every way a drive ends publishes a burst of five zeros**: release, stale frames, the per-press cap (8 s on the
    dog, 7 s in the app), a cap violation, a closed stream, SIGTERM, and a publisher error. If the zeros can't be
    confirmed, `unresolved-action.json` stays in place, so nothing else runs until someone inspects the dog.
  - **Caps refuse, they don't clamp**: |vx| ≤ 0.15, |vy| ≤ 0.10, |wz| ≤ 0.40. These are ours: the docs give no units
    or limits for `Twist`, so **m/s and rad/s are assumed**. The app sends 40% (Slow) or 80% (Normal) of them.
  - A drive is refused unless the dog is ready (standing, fresh telemetry) **and the velocity topic has a consumer**.
    The helper never changes the run mode.
  - Frames carry a sequence number; late or repeated ones are dropped on the controller and on the dog. A show
    can't start during a drive and a drive can't start during a show.
  - **What this can't cover:** a `kill -9` of the helper skips the zeros, and nothing documented says whether the dog
    stops by itself when publishing just stops. The tests exercise every path the helper handles, not that one.
  - **Not yet known:** whether the dog responds to `Twist` in its current mode (`RL_TROT`), which sign and scale it
    expects, and how far one hold goes. First supervised test, in order: (1) hold with nothing moving to check the
    publisher matched; (2) Slow, turn only, about a second, release; (3) close the tab mid-turn and separately drop
    the Mac's Wi-Fi, and confirm the dog stops within about half a second; (4) only then, Slow forward.
- **Bottom sheet.** Pressing an action, the pad or **Try** no longer switches tabs. A sheet at the bottom shows
  what is running, with Stop, and then what the dog reported ("The dog reported it finished" is a report, not proof
  that anything moved: see steps above). Whole shows still open the Stage.
- **Arming motion.** The three confirmations stay available while connected: tick them and press
  **Reconnect with motion** (disabled while a show runs). It reconnects with a new lease; nothing is replayed.
- **Same gates as presets.** A move goes through `robot_action.py`'s readiness scan, durable request record and
  unresolved-action lock, then the same terminal-result and postflight checks. The graph is built *before* any
  record is written, so a construction error can't leave an unresolved-action lock behind. A dirty result ends
  the session, like a preset.
- **The face is always handed back.** The screen is treated as possibly held until the dog confirms a release
  after the move. If that release fails the move is reported as failed and the session ends.
- **What is verified.** The goal builds and survives flatbuffers serialization for every move, with and without
  a face, using the vendor's own generated classes (`vbot-lab/.venv/bin/python -I tests/test_vbot_studio.py`).
  Everything else is tested against fakes.
  **Nov 5 2026, one dog, results so far:**
  - **Turns work.** Left 30°, right 30°, left 90° and right 90° were sent and watched. Left is counterclockwise.
    This proves a typed `BaseActionCommand.ROTATE` is accepted in the dog's current mode.
  - **Steps did not.** A typed `MOVE_FORWARD`/`MOVE_LEFT` was sent four times and the dog reported `SUCCEEDED`
    with a clean postflight each time, but did not move. The guarded path can't tell "moved" from "did nothing",
    which is why the app showed success. A "clean finish" for a step therefore means nothing on its own.
  - **Steps now use the vendor's own template**, `atom/move_param.json` with `base_action_task`, `distance_m` and
    `tts`, exactly as the vendor docs list it. That preset controls the screen, so a step can't carry a face.
    Not yet confirmed to move the dog. The vendor preset files can't be read from the dog (not visible to its
    `vbot` user), so this is the documented argument list only.
  - **Moves with a face (turns only) have not been run.**
  - Step back and step right have not been run at all.
- **Deploy.** The same three helper files (`robot_face.py`, `robot_action.py`, `robot_studio.py`) from one
  commit. The helper now announces protocol 4, its move list and its driving limits; an older `robot_studio.py` is refused at connect.

Deploy once, with the dog in front of you (this writes one file and moves nothing):

```sh
scp vbot-demo/robot_studio.py vbot-demo/robot_action.py vbot-demo/robot_face.py "$VBOT_TARGET:/userdata/vbot/chess-demo/"
```

`robot_studio.py` imports functions from the other two, so deploy all three from the same commit. Check what is
on the dog first: copying `robot_action.py` over a deployed one replaces it.

## Recovery

| What you see | What to do |
| --- | --- |
| “Outcome unknown” | Check the dog in person. Reconnect to read status. The cue won't be replayed. |
| “Screen release not confirmed” | Look at the dog's screen. The helper also releases it when its session ends. |
| Connect says another controller owns the dog | Stop the chess reactions or show first, or wait for the idle close. |
| Connect says an unresolved action needs inspection | Inspect the dog and the saved request before doing anything else. |
| Connect says the helper may be missing | Check power, Wi-Fi and SSH trust, then that `robot_face.py` (and, for motion, `robot_studio.py`) is deployed. |
| Controller not running | Run `npm run vbot:controller`. Saved shows are in the browser and aren't affected. |

Until the Android app has run on a device, live control needs a computer running the controller. Saved shows
live in that browser or app's storage, so export any you want to keep.

## Android app

It installs next to Chess Buddy and can't replace it or touch its data. The APK carries the controller and face
protocol, and doesn't carry the chess code or any dog-side helper.

**Installing.** Download `VBOT-Studio-Android.apk` from the repository's
`vbot-studio-v…` GitHub Release. These tags are separate from Chess Buddy's
`android-v…` releases. Install it as `com.andy.vbotstudio` beside Chess Buddy.

**Building.** Pushing to `codex/vbot-app-scaffold` runs
`.github/workflows/vbot-studio-apk.yml`. The workflow restores the existing
`ANDROID_SIGNING_BUNDLE`, builds a release APK, checks its certificate against
`android/signing-certificate.sha256`, and runs the embedded controller on an
Android emulator. A separate publish job creates a release only after all checks
pass. No robot connection or movement is part of the workflow.

Local debug builds remain available with `npm run vbot:android:sync`, then
`cd vbot-app/android && ./gradlew assembleDebug`. Signed release builds require
the existing signing environment documented in `ANDROID_UPDATES.md`.

**Updating.** Open **App updates → Open Studio releases** for the permanent
Studio-only download page. No update token is required. Finish a show and
disconnect before opening the installer. New permanently signed Studio versions can update one another in
place. Earlier CI debug builds used different signatures and may require a
one-time migration: export saved shows and record pairing information first.
Do not uninstall without preserving your data. The Studio package is distinct
from Chess Buddy and does not replace or erase Chess Buddy.

The standalone Android controller handles local robot actions and performances.
The Qwen voice/session panel currently needs the computer-side Studio server;
including its UI in the APK does not provide that server on the tablet.

**Pairing, once per dog:**

1. Put the device and the dog on the same Wi-Fi.
2. On a computer that already trusts the dog, run `ssh-keygen -lF <dog address>`. It lists one fingerprint per key type.
3. In the app, choose **Real dog, from this device**, then enter the address, a fingerprint and the dog's SSH password.
4. If the app says the dog presented a different key type, compare that fingerprint to the list and use it if it matches.
   If it isn't on the list, stop and inspect the dog.

The password is used once and never saved. Pairing adds this app's public key to the dog's `authorized_keys`.
`robot_face.py` must already be on the dog, because the app doesn't deploy it.

**Limits.** Keep the app open during a show. There's no background service, so Android may pause a backgrounded
app. If that drops the connection, the show stops and the dog's helper hands back the screen. If the connection
stays up, the helper does that after 3 idle minutes.

## Adding later

- **Rehearsal records for Studio:** motion is enabled per connection, not by measured rehearsal. Reading
  `device-verification.local.json` so rehearsed presets show their measured durations is still open.
- **Cloud:** implement `DeviceTransport` against the real contract. The dog connects outbound. Never put
  device or admin secrets in the frontend or APK.
