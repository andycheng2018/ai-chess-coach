# Standalone Chess Buddy for Android

The standalone APK runs the coaching backend, Stockfish, journal, Lichess bot
runtime, and VBOT SSH client **inside the tablet**. No Mac backend or Mac pairing
key is needed. The earlier paired implementation remains on `codex/android-tablet`;
this version is developed on `codex/android-standalone`.

## Connections

- **Local:** board, variations, saved analysis, Stockfish, coaching history, and
  robot decision/admission logic. The embedded API binds only tablet loopback.
- **Internet:** student Lichess sign-in, game streaming, bot-account operation,
  OpenAI/Luna, and optional ElevenLabs speech.
- **Robot Wi-Fi:** the tablet must reach VBOT's SSH address while also reaching
  the Internet. SenseRobot keeps its existing Lichess room flow.

## Install and configure

1. Install `ChessBuddy-Standalone-Android.apk` on an Android 8.0/API 26 or newer
   64-bit ARM tablet. x86-64 is included for compatible emulators. This demo is
   development-signed, not a Play Store release. A differently signed later build
   can require uninstalling; export analysis PGNs before uninstalling.
2. Open the app and **Tablet settings**. The embedded engine starts locally;
   Stockfish analysis does not require API keys.
3. Enter an OpenAI key for Luna and your Lichess **BOT account** username/token
   for running the training opponent and accepting SenseRobot rooms. The student
   signs into Lichess separately through OAuth.
4. Save settings and continue. Secrets are encrypted using Android Keystore and
   are not bundled into the APK. Empty secret fields retain saved values.
5. Join SenseRobot through its setup/room flow or start ordinary training play.

Keep the app foregrounded during a live demo. The ongoing notification can stop
the backend. Android may limit background service lifetime/network activity;
stopping the backend does not stop the Lichess clock.

## Direct VBOT setup

The tablet generates its own SSH key; do not copy a Mac private key into it.

1. Enter the dog's actual address and independently verified, full SHA256 SSH
   host fingerprint. Unknown/changed keys are rejected without automatic acceptance.
2. Import the dog's existing `device-verification.local.json` rehearsal record.
   This is host identity/rehearsal metadata, not a private key. Its fingerprint
   must match. The bounded helper must already be provisioned on the dog at
   `/userdata/vbot/chess-demo`; this port does not install or restart robot services.
3. Save settings. **Show tablet public key** creates a tablet-owned identity whose
   private half stays Keystore-encrypted in private app storage.
4. Add that public key to the dog's `vbot` authorized keys using an already
   authorized setup method. Alternatively, **Install tablet public key on dog**
   uses an operator-entered one-time SSH password and explicit confirmation.
   The password is not saved and existing authorized keys are retained.
5. Use the normal VBOT panel's readiness and onsite-confirmation flow. Pairing a
   key does not arm movement. Canonical coach checks, rehearsals, clock limits,
   cooldowns, one-shot dispatch, and unknown-outcome disarming still apply.

The helper runs on the dog, not a Mac. Provisioning a new identity is a one-time
setup operation. No perception-triggered gestures are added by this port.

## Build and source

`Standalone Android tablet APK` builds on `codex/android-standalone`. It compiles
official Stockfish `sf_19` with the Android NDK for arm64 and x86-64, embeds Python
with Chaquopy, and builds a non-debuggable release variant using the development
signing configuration. The artifact includes the APK, matching Stockfish source,
NNUE files, license/build helper, and SHA-256 checksums.

Python backend sources are copied from this checkout at build time rather than
forked into a separate implementation. The Android Responses HTTP adapter keeps
the existing prompts, validation, audits, and `store=False` while avoiding desktop
SDK native dependencies. Direct SSH uses JSch with the explicitly pinned host and
tablet identity. Runtime data stays outside packaged source assets in private storage.

No `.env`, bot token, SSH private key, local rehearsal profile, or existing journal
is copied into the build. Native compilation and signature checks are distinct
from actual tablet/robot acceptance: verify startup, local engine search, OAuth,
QR permissions, background/resume, and direct robot access on the target tablet.
Physical rehearsals require onsite supervision and the existing stop procedure.
Turning reactions off prevents future commands; use the dog's stop control for
movement already underway.
