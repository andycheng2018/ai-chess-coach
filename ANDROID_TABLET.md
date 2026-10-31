# Chess Buddy on an Android tablet

This APK runs Chess Buddy's interface on Android 8.0/API 26 or newer. The Mac
remains the companion backend for Stockfish, Luna, the Lichess bot, and VBOT SSH.
SenseRobot connects through its existing Lichess room flow. Keep the Mac and
tablet on the same trusted network; the Mac must also reach VBOT, and Lichess
sign-in/game streaming needs Internet access.

## Install and pair

1. Copy `ChessBuddy-Android-demo.apk` to the tablet. Open it and allow installation
   from that source when Android asks. This is a development-signed demo build,
   not a Google Play release. A later demo signed with a different debug key may
   require uninstalling first; export saved analysis PGNs before uninstalling.
2. On the Mac, update dependencies with `.venv/bin/python -m pip install -r requirements.txt`.
   Stop the ordinary backend's Terminal with Control-C if it is already running.
3. Double-click **Open Chess Buddy Tablet.command**. It opens a pairing QR on the
   Mac and keeps the backend running. The key is stored in ignored, owner-only
   `logs/tablet-pairing.local.json`; keep it private.
4. Open Chess Buddy on the tablet and choose **Scan Mac pairing QR**, or enter the
   address/key shown on the Mac. Review the destination, then tap **Connect tablet**.
5. Sign into Lichess. Android returns to the app through `chessbuddy://oauth/callback`.
6. Use SenseRobot setup to join its Lichess room. For VBOT, choose the dog's actual
   reachable address and use the existing readiness and onsite-confirmation flow.

The Mac address is not the dog's address. **Mac connection** at the bottom of the
tablet app lets you re-pair after changing networks. Stop robot reactions before
switching servers or forgetting a connection. Pairing does not itself arm a robot.
Player coaching history is available in the app; the developer Audit Studio is
opened on the Mac, so its browser session does not need the tablet pairing key.

HTTP pairing is intended for a trusted private LAN and does not encrypt traffic.
The client also supports HTTPS backends with system-trusted certificates. The
pairing key is scoped to the selected backend origin and is never added to Lichess
requests. The backend accepts tablet requests only from private addresses, the
native app origin, and the matching key; all existing robot admission checks remain.
To revoke tablets, stop the backend, rename the local pairing-key file, and reopen
the launcher. Pair the tablet again using the new key.

If automatic Mac address discovery chooses the wrong interface, set
`CHESS_TABLET_HOST_IP` to the Mac's Wi-Fi IPv4 address before running the launcher.
Do not expose this demo backend through a public port-forward.

## Build

The **Android tablet APK** GitHub Actions workflow builds the web assets, syncs
the Android plugins, assembles the debug APK, verifies its signature, and uploads
the APK plus SHA-256 checksum as `ChessBuddy-Android-tablet`.

For a local build, install JDK 21 and Android SDK 36 with its required build tools,
then run `npm ci`, `npm run build`, `npx cap sync android`, and
`cd android && ./gradlew assembleDebug`. The APK is written to
`android/app/build/outputs/apk/debug/app-debug.apk`. SDK paths and signing material
are local-only. The APK bundles no backend `.env`, Lichess bot credentials, SSH
keys, robot verification files, or coaching logs.

Verify native sign-in, QR permissions, layout/rotation, background/resume,
reconnection, and both robot flows on the actual tablet before relying on it for
a live demonstration. An APK build alone does not establish physical integration.
