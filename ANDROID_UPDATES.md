# Android updates

The release pipeline builds the entire standalone app: web UI, Python backend,
Stockfish, and native integrations. This avoids mixing incompatible web and
native versions. `main` is not changed by this workflow.

## One-time signing setup

The signing identity was generated locally with:

```sh
python3 scripts/android_signing.py init
```

The private folder `.local/android-signing/` is Git ignored and owner-only.
`chessbuddy-release.p12` is the password-protected permanent keystore;
`github-secret.json` contains that keystore and its password for CI provisioning.
Treat the entire folder as secret. Back it up in a trusted password manager or
encrypted backup outside this Mac. A local copy alone is not a backup. Do not
regenerate this key for future updates. Re-running `init` retains the existing key.

The public signing certificate digest is checked into
`android/signing-certificate.sha256`. CI refuses to publish an APK with a different
certificate, even if the repository secret is accidentally replaced.

A repository administrator must create one GitHub **Actions** repository secret:

- Repository: `andycheng2018/ai-chess-coach`
- Settings → Secrets and variables → Actions → New repository secret
- Name: `ANDROID_SIGNING_BUNDLE`
- Value: the complete contents of `.local/android-signing/github-secret.json`

On this Mac, this command copies the value without printing it:

```sh
pbcopy < .local/android-signing/github-secret.json
```

Paste only into that GitHub secret field. Clear the clipboard afterward. The key
is transmitted to GitHub and made available to workflows with access to repository
secrets; only trusted maintainers should have permission to edit those workflows.
No API keys, robot SSH identities, or student credentials belong in this secret.
No signing secret is embedded in the app or uploaded with release assets.

## Everyday release flow

1. Commit and push finished work to `codex/android-standalone`.
2. GitHub assigns `versionCode = 1000 + workflow run number`, builds the app, runs
   the Node/Python suite and Android instrumented tests, and verifies the APK's
   signature against the pinned certificate. Never reset the workflow counter or
   reuse a lower code when migrating this pipeline.
3. A separate publishing job, dependent on all checks succeeding, creates a public
   `android-v<versionCode>` GitHub Release. It attaches the APK, signature report,
   checksums, and matching Stockfish source. Only this publishing job has repository
   contents-write permission. Failed tests leave no published update.
4. On the tablet, the app checks for updates at startup. **Tablet settings → App
   updates** also offers a manual check. It selects the highest complete, stable
   Android release among the repository's 100 most recent releases. Other release
   types, drafts, prereleases, older versions, and foreign download URLs are ignored.
5. Finish the game, turn robot reactions off, tap **Download update**, and open the
   downloaded APK. Android handles the final installation confirmation and verifies
   the app's signing identity. There is no silent installation permission.

The native update check is independent of the embedded backend, and remains
available on the backend-startup error screen. An Internet failure does not block
the chess app or its local engine.

## First demo migration and data

The initial `c896c79` demo used an ephemeral development signing key which was not
retained. Android will not accept a permanently signed APK as an in-place update
to that demo. Export saved PGNs, uninstall the demo, then install the first
permanently signed release. Re-enter credentials and pair the new tablet identity
if needed. The updater UI arrives with that first permanently signed build.

After this one-time migration, keep the package ID `com.andy.chessbuddy` and the
same signing identity. Normal updates preserve private app storage, Keystore-backed
settings, saved analysis, and local journals. Data schema changes still require
backward-compatible migrations; signing alone does not make a destructive data
migration safe. Keep an export before major changes.

## Local signed build

Set `ANDROID_KEYSTORE_PATH` to the absolute `.p12` path and
`ANDROID_KEYSTORE_PASSWORD` to its password; optionally set `ANDROID_VERSION_CODE`
to a new, unused code greater than the installed version. A release build without
the signing inputs fails rather than silently using a new debug identity.
Never commit shell environment files or print the password in a build log.

The private signing bundle and a native release using it still need provisioning
and verification if the GitHub secret has not yet been configured. Source checks
alone are not evidence that a published update is installed on a tablet.
