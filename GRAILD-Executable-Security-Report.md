# GRAIL'D Executable Security Investigation

**Scope:** read-only inspection of the project source, Windows and macOS build configuration, and current `build/` and `dist/` artifacts. No executable was launched. No files were removed or altered other than creating this report. SHA-256 was computed by reading executable bytes. This is a static workspace review, not a malware verdict or an independent validation of publisher signatures.

## Executive summary

- `payload.exe` **is present**: nine physical copies are under `build/update-acceptance-TEST-ONLY/runtime/.../jobs/`. No file named `payload.exe` was found in `dist/`. The large `GRAIL'dv0.8.0beta.zip` archive also contains copies of this test tree, including one `payload.exe` entry.
- The payload files are consistent with generated updater acceptance fixtures: two hashes map to the 0.8.1 and 0.8.2 test fixtures, while one is modified by appending the literal bytes `tampered` to exercise rejection. The same three versions and test-only updater are created by `updater_windows_acceptance.py`. No evidence found that these are app startup payloads or a separate malware implant.
- **Confirmed credential exposure in workspace:** `GRAILD-Discord-Bot/.env` contains a populated, non-placeholder `DISCORD_BOT_TOKEN`. Its value is not reproduced here. The file is excluded by the bot `.gitignore`, but its presence in this workspace is enough to treat the credential as exposed if the folder or an archive containing it was shared. Check any shared copies and rotate/revoke the token if appropriate.
- Current Windows release binaries match their manifest SHA-256 values; current macOS archive hashes match `SHA256SUMS.txt` and the corresponding metadata. These checks establish byte-for-byte consistency only. I did not cryptographically verify Ed25519 signatures because the project's Python runtime is unavailable in this environment.
- No unapproved persistence/autostart mechanism was found in the inspected source. Update restart and rollback launches are explicit updater behavior.

## `payload.exe` search and hashes

The repository-wide filename/reference search found source references in `auto_update.py`, `graild_updater.py`, updater tests, generated release-source copies, and the update acceptance harness. These references are expected: on Windows, `auto_update.py` atomically renames a size-limited download to the staging name `payload.exe`; it verifies it before marking the update ready. `graild_updater.py` re-verifies the payload before copying, after copying to the incoming executable, and after replacement. The updater test suite creates payloads to test successful updates and tampering.

A filename search over `build/` and `dist/` found **9 physical `payload.exe` files, all in `build/update-acceptance-TEST-ONLY/runtime/.../jobs/`; 0 in `dist/`**. The nine copies have three distinct hashes:

| Size | SHA-256 | Assessment |
|---:|---|---|
| 7,569,662 bytes | `00BDCE6756EAD208D8E2D375AE8516AC43D3B0A4757B480542F14CB45ACA68BD` | Base `Fixture-0.8.0.exe`, observed as the old/test executable in acceptance-test runtime. |
| 7,570,632 bytes | `41703F8309DDABD7B0F9921C2ED332B3DCD27229E309E65561E84C7280701A95` | `Fixture-0.8.1.exe`; repeated accepted update fixture. |
| 7,568,113 bytes | `610589688337E190BAC71EFEA3247CEE7E3695697E4FE250E579995246DC0216` | `Fixture-0.8.2.exe`, generated for the simulated failed-startup/rollback test. |
| 7,570,640 bytes | `28DB705FF72CA14683D76927966748F3A9B3A873EE2CE8CE6A1F93F2CB336682` | 7,570,632-byte fixture plus the 8-byte `tampered` test suffix. Deliberate tamper-rejection case. |

For context, the test harness uses a 7,569,662-byte `Fixture-0.8.0.exe` as the old installation target; its SHA-256 is `00BDCE6756EAD208D8E2D375AE8516AC43D3B0A4757B480542F14CB45ACA68BD`. That base fixture hash is not one of the physical `payload.exe` hashes. The payload hashes came from file bytes; no payload was executed. The archived `GRAIL'dv0.8.0beta.zip` contains the same generated acceptance-test tree and at least one payload entry; this is archive duplication, not another source of payload logic.

## Executables in intended distributions

### Windows

The release assembly's named app executables are:

| Release path | File | Purpose | SHA-256 |
|---|---|---|---|
| `dist/releases/v0.9.2/` | `GRAILD.exe` | PyInstaller desktop app, webview UI, gameplay, account features, and updater client. | `154A981F894BAF62774BAE370668A9A9CB71BE95AEA613866900CE4A9247C502` |
| `dist/releases/v0.9.2/` | `GRAILDUpdater.exe` | Separate recovery/standalone updater helper. The primary app also embeds a copy for normal update installation. | `678B1E2DEFA327C9570CAC8351098054DEEEB72D254CFBA054DE7A76BA7E7451` |

For comparison, each of `v0.8.0`, `v0.8.1`, `v0.9.1`, and `v0.9.2` contains one `GRAILD.exe` and one `GRAILDUpdater.exe`. All four main EXEs' actual SHA-256 values match `graild-update.json`; v0.9.2's helper also matches `build-info.json`. The helper is expected by `build.bat` and the release preparation script; it is copied into the main app's one-file bundle as a data resource and launched by the updater code.

The main PyInstaller build also collects `imageio_ffmpeg`, which supplies the FFmpeg decoder executable used by `audio_files.py` for supported playback/conversion. This is an expected dependency, not a second app launcher. PyInstaller embeds it inside the application bundle rather than presenting it as a top-level release download. The outer release folder separately contains the named updater helper as described above.

The workspace has **16 physical `.exe` files under `dist/`**, including old root-level `JuiceGuesserMain*.exe` staging builds and historical/release copies. The old root-level outputs are not listed in `dist/releases/v0.9.2/UPLOAD_FILES.txt` and are not the declared v0.9.2 Windows asset. `dist/` also contains non-release directories such as `achievements/` and `leaderboard-fixed/` with legacy builds.

### macOS

The current v0.9.2 macOS distribution is two ZIPs, one per architecture. Each contains a `GRAILD.app` bundle with:

- `GRAILD.app/Contents/MacOS/GRAILD`: app launcher and PyInstaller executable.
- `GRAILD.app/Contents/Frameworks/Python.framework/Versions/3.13/Python`: bundled Python runtime library/executable component used by the frozen app.
- `GRAILD.app/Contents/Frameworks/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v9.0` (arm64) or `ffmpeg-macos-x86_64-v9.0.2` (x86_64): bundled decoder used by audio playback.

No Windows `.exe` is in these macOS ZIPs. `GRAILD-mac.spec` explicitly filters `.dll`, `.exe`, and `.pyd` files from collected package assets to avoid including Windows binaries in a Mac app. The FFmpeg file has no `.exe` suffix on macOS and is an expected runtime dependency.

The actual v0.9.2 Mac ZIP hashes match the published checksum text and metadata:

- arm64 ZIP: `f7b8f863bafd4c4f703514d93f539483eebf6ccf6c6f7ced794a49f361e64461`
- x86_64 ZIP: `7b8bb1790f1d46069b94f79fa52214d59a010f759f782df50c506c07bb02d943`

The corresponding embedded `GRAILD` launcher hashes are `76A2BB54C7158C7E368A517337DCE554D6D0375630B2A4275060ED5587C77903` (arm64) and `D030A3A57594E08880E6514C4652AA63020D3B897B5A8F9DD5B402E1939DCD9C` (x86_64). These were read from ZIP entries without launching them.

## PyInstaller and build configuration

- `JuiceGuesserMain.spec` analyzes `JuiceGuesserMain.py`, the UI assets, certifi data, and `collect_all()` for pygame, pywebview, and imageio_ffmpeg. It explicitly includes `dist/GRAILDUpdater.exe`. No `payload.exe` is declared as a bundled input.
- `build.bat` first builds `GRAILDUpdater.exe`, then builds the desktop one-file executable with the entry script, UI assets, FFmpeg dependency, and updater helper. It copies named build outputs to `dist/` using `publish_build.py`.
- `prepare_beta_release.py` copies an explicit source list and assets to an isolated build staging directory, builds the updater and app with PyInstaller, and copies only `GRAILD.exe` and `GRAILDUpdater.exe` into the versioned release output before manifest generation.
- `GRAILD-mac.spec` starts at `mac_launcher.py`, collects expected Mac packages/assets, filters Windows PE extensions, and applies the configured macOS signing identity if supplied.
- `build_macos.py` checks architecture, builds the app, runs `codesign --verify`, creates the ZIP, and compares bundle digests. These are build-time checks; they do not imply notarization.
- `build/tailwindcss-windows-x64.exe` is a standalone Tailwind CSS CLI referenced by `assets/README.md` for regenerating CSS. Its SHA-256 is `67F1C5E3F5A03406A7BF5BADF5ADA09B79F3AE78EC43450C15F7E983068DA346`. It is a developer build tool, not part of the runtime app distribution.

No executable was launched or extracted to disk during this review. Windows and macOS ZIP central directories and selected executable streams were read for inventory/hashing.

## Download, generation, rename, and execution paths

- `auto_update.py` requests release metadata from `api.github.com`, validates release asset URLs against the configured GitHub repository/tag/name, downloads the exact signed asset size to a staging `.part`, then verifies the manifest-bound SHA-256 before renaming it to `payload.exe` (Windows) or `payload.zip` (Mac).
- `graild_updater.py` copies the verified payload to a `.graild-new-<job>.exe` path, verifies it again, backs up the existing app, atomically replaces it, and launches the new app for health confirmation. Failure triggers verified rollback and relaunch of the old app. It does not fetch an arbitrary helper executable; the helper is supplied by the app bundle/release build.
- `mac_updater.py` unpacks the signed app ZIP using the system `ditto`, validates bundle digest/signature, swaps the `.app`, and rolls back if startup confirmation fails.
- `imageio_ffmpeg` supplies the decoder. `audio_files.py` launches this known bundled decoder with fixed argument construction; the command runs media decoding, not an arbitrary downloaded program.
- Build scripts call PyInstaller and platform build tools (`codesign`, `ditto`, `lipo`). `publish_build.py` copies/renames build output, preserving locked prior outputs with timestamped names. `updater_windows_acceptance.py` deliberately creates test-only fixture executables and tampers with one test payload. No source path was found that downloads and executes an unrelated `payload.exe`.


## Hardcoded secrets and personal identifiers

The source/config scan found no private signing-key block, private signing-key file, or non-test literal API/session credential. `update_trust.py` contains the Ed25519 **public** verification key, which is expected to ship with the verifier. `oauth_config.py` contains a public Google OAuth client ID, not a client secret. The broker source and templates contain default owner Discord account IDs; these identify accounts but are not authentication credentials. Test OAuth credentials are clearly test fixtures. The non-placeholder bot token in `GRAILD-Discord-Bot/.env` is the credential finding described above. Its file is ignored by the bot `.gitignore` and is not in the v0.9.2 upload list.

The bot `.venv` contains 13 ordinary Python/pip utility executables and a Certifi CA trust bundle. It is a local dependency environment, not an application distribution. No `payload.exe` exists in that environment, and no private key file was found in the filename scan; Certifi's CA bundle is public trust data, not a signing private key.
## Network destinations and persistence

Observed production network destinations in source include GitHub Releases/API for signed update metadata/assets, Discord OAuth/API, Google OAuth/OpenID, the configured Discord OAuth broker (`graild-discord-broker.onrender.com`), and Canary API (`canary.best`). `evil.example` and similar attacker domains appear in negative tests. Update URL validation constrains release assets to HTTPS GitHub release URLs for the configured repository, expected tag, and exact asset name; redirects are restricted by the HTTP client/validator. No unexplained third-party executable download destination was identified in the inspected code.

Persistence found is expected application/update state: user profile/account data in platform user-data directories, update jobs/health state in the platform update directory, and macOS secure session storage via Keychain. The updater uses temporary backup/incoming executables and removes/retains them according to recovery flow. Search found no Run/RunOnce autorun registration, startup-folder installation, scheduled task, launch agent, service installation, or cron persistence code. Bot runtime configuration and logs are normal service behavior.

## Update signature verification

Windows validation uses an Ed25519 signature over canonical release-manifest JSON, with the trusted public key compiled in `update_trust.py`. The signed manifest binds the repository, channel, version/tag, platform, asset name, size, and SHA-256. `auto_update.py` checks the manifest before download, enforces size limits, verifies the downloaded bytes, and only then exposes the update as ready. `graild_updater.py` validates the manifest and payload again before installation, verifies staged/incoming/installed bytes, and verifies the recovery backup before rollback. On this code path, a payload with a missing/invalid manifest signature or a byte mismatch is rejected before it can be installed.

**Important distinction:** the Windows updater verifies the publisher's Ed25519 manifest signature and the executable's signed hash; it does not appear to require a separate Authenticode certificate signature on the PE file. Thus “fails signature verification” is prevented for the configured manifest-signature scheme, while Authenticode validity is not an independent install gate. A trusted manifest signer can authorize any bytes. That is a trust-model boundary, not evidence of a bypass.

The Mac path likewise binds the archive digest in the signed manifest and verifies the app bundle digest and code signature before swap. Current Mac build metadata says the bundles are ad-hoc signed and not notarized; physical-Mac acceptance is noted as pending. This is a distribution assurance limitation, not an unexpected executable.

## Intended versus actual release contents

- `dist/releases/v0.9.2/UPLOAD_FILES.txt` names `GRAILD.exe`, Windows manifest, two Mac ZIP assets, and Mac manifests. All listed payloads exist. The actual Windows `GRAILD.exe` SHA-256 matches the Windows manifest; Mac ZIP hashes match Mac manifests and `SHA256SUMS.txt`.
- `GRAILDUpdater.exe` exists in the v0.9.2 release folder and has a digest recorded in `build-info.json`, but it is **not listed** in `UPLOAD_FILES.txt`. Since the main Windows app embeds its own helper, omission from the upload list appears intentional for the public update asset set; the standalone helper remains a local/recovery artifact. Confirm that packaging policy before distributing it separately.
- The v0.9.2 release folder also contains source build-kit ZIPs, build scripts, checksums, status notes, signing script, and checklist. These are build/release support materials, not runtime executables. Some are present in the version folder but absent from the upload list, as expected for local packaging support.
- Earlier `v0.9.0` and `v0.9.1` folders contain their historical Windows executables and macOS packages/build kits. The complete `dist/` tree has 16 `.exe` files, counting current, older, and legacy/staging outputs; only the per-version `GRAILD.exe` is declared as the Windows update asset.
- `build/` has 52 `.exe` files, mostly isolated release-build snapshots, historical release copies, test fixtures, and generated build tools. They are development artifacts, not part of the intended release upload set.
- The root archive `GRAIL'dv0.8.0beta.zip` is 1,400,439,727 bytes and contains large `build/` and `dist/` trees, including acceptance fixtures and payload files. It is not a clean distributable release package. Treat sharing this archive as a potential exposure of internal build artifacts and test fixtures; inspect its full file list before distributing. No evidence in this review shows that it includes the live bot `.env`.

## Findings by confidence

### Confirmed security issue

1. **Plaintext Discord bot credential in workspace:** `GRAILD-Discord-Bot/.env` has a populated, non-placeholder `DISCORD_BOT_TOKEN`. The value is intentionally withheld. It is ignored by `GRAILD-Discord-Bot/.gitignore`, and no release upload listing includes it, but the credential is present in the project directory. If this workspace or an archive containing that path was shared, revoke/rotate it and verify the bot's authorized state. This review did not test the credential or inspect its value.

### Suspicious findings requiring investigation

1. **Oversized legacy ZIP contains generated test/release artifacts:** `GRAIL'dv0.8.0beta.zip` contains `build/` and `dist/` content, including test updater fixtures and `payload.exe` copies. This is not consistent with a clean user-facing release archive; determine who created/shared it and whether intended.
2. **Standalone helper present but absent from v0.9.2 upload list:** decide whether `GRAILDUpdater.exe` is strictly local recovery support or should be an explicitly controlled release asset. Its presence alone is not suspicious because the app also embeds the updater.
3. **No separate Authenticode gate:** current update acceptance is based on Ed25519-signed manifest plus signed SHA-256 binding. Confirm this is the intended Windows trust policy; do not mistake it for an Authenticode check.
4. **Ad-hoc Mac signing and pending physical-Mac acceptance:** build metadata states not notarized and real-Mac acceptance pending. Confirm distribution policy and user expectations.


5. **Legacy archive contains browser-profile databases and logs:** `GRAIL'dv0.8.0beta.zip` includes 37 `.db`/SQLite entries (~3.07 MB) and 100 `.log` entries (~107 KB), mostly under generated Edge `browser-profile` directories, plus `build/canary-reference/live-cache.sqlite3`. The archive also contains two `.env.example` templates but not `GRAILD-Discord-Bot/.env`. The database/log contents were not parsed for personal records in this pass; inspect or exclude the archive before sharing it because its generated profiles/caches may carry browsing or test-session data.
### Legitimate application components

- `GRAILD.exe` / macOS `GRAILD.app` launcher: main desktop application.
- `GRAILDUpdater.exe`: trusted update/recovery helper, also embedded into the main Windows app.
- Bundled FFmpeg executable: expected `imageio_ffmpeg` media decoder.
- Bundled Python framework in the Mac app: frozen Python runtime component.
- `payload.exe` under `build/update-acceptance-TEST-ONLY`: test fixtures used to test signature/hash acceptance, tampering rejection, installation, and rollback; hashes above match fixture/test construction.
- `build/tailwindcss-windows-x64.exe`: documented developer CSS build utility.
- Other old `JuiceGuesserMain*.exe`, historical `GRAILD.exe` and updater copies in `build/` or non-release `dist/` folders: stale/staging/history artifacts, not current declared release assets.

## Review limits

The working environment's `py.exe`/`python.exe` could not be launched, so no Python-based manifest-signature verifier, PyInstaller archive inspector, or release verifier was run. No apps or binaries were executed. Windows EXE hashes and manifest hash fields were compared directly; macOS app ZIP entries were inventoried and their ZIP checksums compared with the recorded checksums. Ed25519 signatures, Authenticode status, code-signing identities, and live network behavior remain unverified in this session. Hashes establish identity for this snapshot, not that a file is benign.