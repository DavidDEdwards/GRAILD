# GRAIL'D beta auto-updates

## Current state

The application version is `0.8.0` in `app_version.py`. The configured repository is `DavidDEdwards/GRAILD-Releases`, the default channel is beta, and the publisher public key `graild-beta-2026` is embedded. Automatic checks are enabled by default. No GitHub release has been published automatically.

See [BETA_RELEASES.md](BETA_RELEASES.md) for the prepared 0.8.0/0.8.1 builds, actual key location, exact build/sign commands, upload list, key backup instructions, and manual live test. The publisher setup examples below describe the general mechanism; this project's initial setup is already complete.

## Architecture

- `update_security.py`: strict SemVer 2.0 precedence (including numeric prerelease identifiers and ignored build metadata), duplicate-field rejection, Ed25519 verification, repository/channel/tag binding, manifest expiry, signed sizes and SHA-256 checks.
- `auto_update.py`: background GitHub release lookup, beta/stable filtering, HTTPS GitHub/CDN URL allow-listing, bounded metadata reads, streamed downloads, progress and cancellation. Source mode can exercise checks/downloads but cannot replace its Python interpreter.
- `graild_updater.py`: a separately frozen, network-free installer bundled inside the application and also built as `dist/GRAILDUpdater.exe`. The app copies its own trusted helper into a unique job directory, verifies that copy, and starts it before closing.
- The helper rechecks the signature and executable digest, verifies that its parent PID is the exact target executable, opens a process handle, acknowledges readiness, then waits for process exit. PID reuse cannot substitute another parent. Windows file locking and bounded replacement retries protect other running copies.
- The helper writes a recovery journal, copies a verified backup alongside the target, and atomically replaces the executable. It never unpacks an untrusted ZIP or accepts an installation path from a release manifest.
- The new EXE is hash-checked under a read lock immediately before process creation. The helper starts it with an independent PyInstaller environment. The new app verifies the handoff and acknowledges only after native UI initialization. A failed exit or missing startup health signal triggers rollback; only the helper-launched failed process tree is stopped.
- `update_health.py` also finalizes a successfully started new build if the helper was interrupted after committing it.
- `update_ui.js`: signed version/release notes, Update Now/Later, progress, cancellation, and Settings > Check for Updates. Release notes render as plain text, not HTML. Update Now authorizes download, verification, restart and installation; Later does not install anything.

GitHub release listing behavior is documented at https://docs.github.com/en/rest/releases/releases#list-releases. Ed25519 uses https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/. Independent frozen subprocess handling follows https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-independent-subprocesses-from-a-frozen-application.

## User data and installation

Existing data stays at `%APPDATA%\JuiceSpot`: Discord DPAPI session, account/profile SQLite database, preferences and Canary metadata. The updater never copies, replaces or deletes that directory, and never touches music files.

Update settings, downloads, requests, result logs and journals are stored under `%LOCALAPPDATA%\GRAILD\updates`. Each job has a random identifier. Downloads use `.part` files, which are never executed; cancellation/interruption discards partial downloads and a retry starts fresh.

The EXE can be updated in a writable portable folder. For beta distribution, `%LOCALAPPDATA%\GRAILD\app` is a suitable installation folder. Protected locations such as Program Files require moving to a user-writable location; this updater does not elevate or request administrator access. Friends need only the main EXE for normal updates because its updater helper is embedded. Keep the standalone helper available for recovery.

Rollback restores the executable, not old user data. Future database migrations must remain backward compatible with the immediately previous release; this avoids replacing newer player data during rollback. The initial implementation adds no updater migrations to the profile database.

## Publisher setup before distributing 0.8.0

1. Create or choose a **public** GitHub repository. Set `DEFAULT_REPOSITORY = "owner/repository"` and `DEFAULT_CHANNEL = "beta"` in `update_trust.py`, or let users configure the repository and channel in Settings. Never embed a personal access token in the app.
2. Generate an Ed25519 key **outside the repository**, preferably in encrypted/offline storage:

   ```powershell
   py -3.13 release_tools.py keygen --private-key C:\SecureReleaseKeys\graild-beta.pem --key-id beta-2026
   ```

   The command prompts for a password and writes an encrypted PKCS8 PEM. It prints only the public key. Paste the public key into `TRUSTED_PUBLIC_KEYS` in `update_trust.py`.
3. Run `build.bat`. It builds the standalone helper first and bundles it plus both UI scripts into the main one-file EXE. Both executables get the same compiled trust keys and version. Close the running app before publisher builds when possible. If the old EXE is locked, the build prints a timestamped new filename: sign and publish that exact new file, not the old `dist/JuiceGuesserMain.exe`. Test this update-enabled initial build before sharing it.

Do not send friends the unconfigured scaffold build and expect it to trust a key added later only on GitHub. Trust cannot safely be bootstrapped from the update server.

## Publish the next beta

1. Change `APP_VERSION` to, for example, `0.8.1-beta.1`. Stable examples use `0.8.1`. Rebuild both executables with `build.bat`.
2. If using Windows Authenticode, sign the final EXE **before** creating its update manifest, because signing changes its bytes. Authenticode is optional here; the Ed25519 manifest signature is mandatory.
3. Write UTF-8 release notes, then create the signed manifest:

   ```powershell
   py -3.13 release_tools.py manifest --private-key C:\SecureReleaseKeys\graild-beta.pem --key-id beta-2026 --repository owner/repository --channel beta --asset dist\JuiceGuesserMain.exe --notes release-notes.txt --output graild-update.json
   ```

   This prompts for the password; no private key is bundled or uploaded. The signer refuses keys not present in `update_trust.py`.
4. Create a GitHub Release with tag `v0.8.1-beta.1`, mark it **prerelease**, and upload the final EXE and `graild-update.json` as release assets. Their names must exactly match the signed manifest. A stable release uses channel stable, a stable SemVer, and is not marked prerelease.
5. Keep old public keys embedded during key rotation until clients have updated to builds that include the replacement key. Manifests expire after 90 days; publish a fresh signed release when needed. Do not distribute private keys or test-only acceptance binaries.

Beta clients consider both stable and beta releases, choosing the highest valid newer SemVer. Stable clients reject prereleases and beta-channel manifests. Existing installations are never downgraded just because a channel changes. A checksum downloaded beside an EXE is not treated as a trust anchor.

## Failure and recovery

- If update storage is inaccessible, the updater reports an error while gameplay remains available.
- HTTP errors, rate limiting, offline connections and timeouts leave the existing app running. Cancellation and interrupted downloads cannot create an executable candidate.
- Any signature, version, repository, tag, expiry, size or digest mismatch blocks installation.
- A write-permission failure detected during preflight leaves the app open. If installation fails after shutdown but before commit, the original EXE is still intact and can be reopened.
- If new-build startup fails, the helper restores and reopens the previous verified local EXE. It retains result logs for Settings.
- Successful updates retain a `.graild-backup-<job-id>.exe` alongside the application. Keep it until satisfied with the beta. Old job files/backups are not recursively deleted by the updater.
- If the helper or machine is forcibly stopped after commit and the new build cannot start, close every copy of the app and run the **matching cached helper** for that job:

   ```powershell
   & "$env:LOCALAPPDATA\GRAILD\updates\jobs\<job-id>\updater.exe" --job "$env:LOCALAPPDATA\GRAILD\updates\jobs\<job-id>" --recover
   ```

   It validates the signed manifest and recorded backup digest, refuses to overwrite an independently changed target, and restores only the EXE. `request.json`, `journal.json`, and `result.json` identify the job and outcome. The original manifest must still be within its validity period; an expired manifest requires publisher-assisted manual recovery from the retained backup.

This protects against tampered GitHub assets/CDNs and unsigned release metadata. It is not a sandbox against a malicious publisher holding the signing key or malware already controlling the same Windows user account. No privileged service or elevation is installed.

## Verification

Development tests:

```powershell
py -3.13 -m unittest test_updater test_update_ui test_canary_auto_eras test_canary_client test_canary_matching test_audio_files test_game_modes test_achievements test_global_leaderboard test_canary_ui -v
```

`py -3.13 updater_windows_acceptance.py` builds a separate TEST-ONLY updater with an ephemeral test public key and small fixture EXEs. It tests real Windows process waiting, signed installation, tampered payload rejection, startup rollback and interrupted-commit recovery. Production trust configuration is not modified. Results are in `build/update-acceptance-TEST-ONLY/results.json`.

The actual packaged main app is checked with the existing isolated `--canary-smoke-test <report.json>` diagnostic, including app version, fail-closed update defaults, native update UI, profiles, metadata and local gameplay. GitHub publication remains a manual publisher step. The configured signed builds have additional isolated native update coverage in `validate_beta_releases.py`; see BETA_RELEASES.md.
