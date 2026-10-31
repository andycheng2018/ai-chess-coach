# Visitor welcome

A short welcome opens on the first visit in a tab/app web session. It explains:
open easy capture practice, tap a piece and its destination, then keep exploring.
**Start demo** starts one standalone two-dance Flow performance, independently
of Lichess login, account recovery, room join, or game state. **Try an easy capture**
opens the existing practice board without a Lichess login.
**Explore Chess Buddy** opens Home Hub. Closing the welcome returns to the page
that was already open. Dismissal is remembered in session storage across reloads.

For each next visitor, finish the previous live match, turn robot reactions off,
and choose **Next guest** in the shortcut row. This reopens the welcome and lets
the next person start a fresh practice view. It does not delete saved games,
analysis, chat history, account credentials or robot configuration. A browser
cannot identify a new physical visitor; the host uses this reset between people.
The button is blocked while robot reactions are armed/busy or a game is starting.

The host opens **For the demo host** in the welcome and confirms clear space
and supervision with the handset Stop ready. These confirmations are kept only
in memory, scoped to the configured dog address, for 15 minutes. **Next guest**
keeps that preparation within its window. Reload, address change, expiry, or an
unchecked confirmation requires host preparation again. Every visitor Start
previews the verified score and checks the robot's current readiness before
starting. No game identifier or account is required or manufactured.

A successful Start opens Dog stage to monitor/stop further cues. A failed check
keeps the welcome open with the actual error. Duplicate clicks cannot queue
parallel shows; lost/unconfirmed start responses are not retried automatically.
**Dog performance** remains available to configure or inspect the existing show
controls. Opening or dismissing the welcome alone never starts movement.

Validation: production build; first-session popup; dismissal persisting across
reload; Next guest reopening; practice navigation; performance navigation;
armed-controller reset blocking; account/game-free Start; expired/mismatched host
checks; duplicate Start clicks; readiness refusal without a movement request. Reset/navigation were tested in an isolated
frontend pointed at an unused backend port, so no physical show was started.
