# VBOT Studio (working name)

The dog's own app: connect, browse faces and actions, write shows, and run them from a
stage view. It has no chess, Stockfish or Lichess dependency.

## Status

| Piece | State |
| --- | --- |
| App with simulated dog (all five screens, saved shows, fault rehearsal) | Works in a browser |
| Live face control: app → local controller → `robot_face.py` | Ran on the dog on 2026-11-03, from a Mac: Mood Swing played and the operator saw the faces. **Stop future cues** also worked: the next cue never started and the dog confirmed the screen release. Only those six faces have been played. Lost connections and recovery are only tested against stubs. |
| Head and body presets (`robot_studio.py`) | **Built and tested against fakes only. Not deployed to or run on a dog.** Off unless the operator ticks all three onsite confirmations when connecting. No preset is marked rehearsed or confirmed because of it. See [Motion](#motion-optional-untested-on-the-dog). |
| Navigation | Deliberately absent from the live path |
| Speech | Placeholder. No verified backend. |
| Cloud | Placeholder. Needs the backend API, auth and pairing contract. |
| Android app | Project in `vbot-app/android` (`com.andy.vbotstudio`). The controller and pairing are tested against fakes. **Not yet compiled or run on a device.** Test builds use a debug signature. |
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
      └ CloudTransport       explains what's missing
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
  That needs the preset files read from the dog first.

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

**Building.** GitHub Actions builds it with `.github/workflows/vbot-studio-apk.yml`, which uses no secrets and
publishes nothing. Pushing to `codex/vbot-app-scaffold` starts a build, which then runs on an emulator. Download
`VBOT-Studio-debug` from the run. To build locally you need JDK 21, the Android SDK and Python 3.13:

```sh
npm run vbot:android:sync
cd vbot-app/android && ./gradlew assembleDebug
```

**Updating.** Each CI build has a different debug signature, so installing a newer one means uninstalling the old
one, which erases saved shows and the pairing. Export shows first. A permanent signing key would fix this.

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
