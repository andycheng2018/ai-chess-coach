# VBOT Studio (working name)

The dog's own app: connect, browse faces and actions, write shows, and run them from a
stage view. It has no chess, Stockfish or Lichess dependency.

## Status

| Piece | State |
| --- | --- |
| App with simulated dog (all five screens, saved shows, fault rehearsal) | Works in a browser |
| Live face control: app → local controller → `robot_face.py` | Tested against stubs and the real SDK schema. **Not yet run on the dog.** The helper isn't deployed. |
| Head, body and navigation control | Deliberately absent from the live path |
| Speech | Placeholder. No verified backend. |
| Cloud | Placeholder. Needs the backend API, auth and pairing contract. |
| Android app | App ID reserved (`com.andy.vbotstudio`). **Native project not generated.** |
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
      └ CloudTransport       explains what's missing
```

- **Preview isn't on the transport.** It renders the pure `buildTimeline`, so a preview can't reach a device.
- **Each face cue is limited to the display.** `robot_face.py` contains only display routes and read-only
  health subscriptions. It has no action client, publisher, or motion route, and a test enforces that.
- **One owner at a time.** `robot_face.py` takes the same `controller.lock` as `robot_action.py` and honors
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

## Recovery

| What you see | What to do |
| --- | --- |
| “Outcome unknown” | Check the dog in person. Reconnect to read status. The cue won't be replayed. |
| “Screen release not confirmed” | Look at the dog's screen. The helper also releases it when its session ends. |
| Connect says another controller owns the dog | Stop the chess reactions or show first, or wait for the idle close. |
| Connect says an unresolved action needs inspection | Inspect the dog and the saved request before doing anything else. |
| Connect says the helper may be missing | Check power, Wi-Fi and SSH trust, then that `robot_face.py` is deployed. |
| Controller not running | Run `npm run vbot:controller`. Saved shows are in the browser and aren't affected. |

Live control currently needs a computer running the controller. **There's no recovery path without one**
until the Android app exists. Saved shows live in that browser's storage, so export any you want to keep.

## Adding later

- **Android:** run `npx cap add android` from `vbot-app/`, then bring over the native SSH and pinned-key
  approach from `android/app/src/main/java/com/andy/chessbuddy/StandaloneHost.java` behind `DeviceTransport`.
- **Motion:** this needs its own authorization, per-dog rehearsal data and a verified stopping procedure. It
  should reuse `robot_action.py` through the same admission rules rather than add a second scheduler.
- **Cloud:** implement `DeviceTransport` against the real contract. The dog connects outbound. Never put
  device or admin secrets in the frontend or APK.
