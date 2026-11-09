# GRAIL'D 0.8.0 standalone verification

## Verdict

The rebuilt release is a standalone **Windows x64 application**: friends do not need Python, pip, VS Code, the source project, a separate FFmpeg installation, or a separate updater executable. The executable contains its Python runtime, required application libraries, UI, fonts, audio decoder, and updater helper.

It is **not independent of Windows system runtimes**. The supported distribution target is modern Windows 10/11 x64 with Microsoft Edge WebView2 Runtime and .NET Framework available. The build contains the WebView2 loader/SDK and Python.NET bridge, not the entire WebView2 browser runtime or Windows .NET Framework. WebView2 is included on Windows 11 and most Windows 10 installations, but a machine missing it must install Microsoft's Evergreen Runtime. See [Microsoft's distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution) and [pywebview Windows dependencies](https://pywebview.flowrl.com/guide/installation.html). Recommend .NET Framework 4.8 on the target computer; no .NET SDK is needed.

A separate folder on the current computer was tested. This was not a fresh Windows VM, and installed system runtimes were not removed. Fresh interactive Discord consent remains a manual browser test; automated checks validate broker connectivity, the authorization handshake, and stored-session preservation.

## Packaging fixes made before signing again

- Replaced the Tailwind CDN script with compiled `assets/tailwind.css`.
- Replaced Google Fonts requests with local Inter fonts in all four used weights. Included font and Tailwind licenses.
- Added the assets directory to `build.bat`, `JuiceGuesserMain.spec`, and the existing versioned beta builder.
- Replaced the first-launch default pointing to David's personal music directory with the current user's Music directory. Explicitly saved/imported music-folder choices keep taking precedence.
- Added opt-in packaged diagnostics and an external verification runner. Ordinary gameplay, OAuth, scoring, and leaderboard behavior were not changed.

The original signed release folders were archived, without editing their signed bytes, under:

`build/standalone-audit/signed-originals-20261031-225002/`

Both 0.8.0 and 0.8.1 were rebuilt using `prepare_beta_release.py` and signed again using the existing trusted publisher key. Rebuilding 0.8.1 ensures the test update retains the packaging fixes.

## Resource and dependency inspection

| Area | Finding |
| --- | --- |
| Python | `python313.dll`, standard library, SSL, SQLite, and required application modules bundled. |
| Libraries | pygame/SDL, pywebview, Python.NET/CLR loader, requests/CA certificates, mutagen, cryptography, and imageio-ffmpeg bundled. |
| Native libraries | Import inspection of 109 bundled Windows binaries found no unresolved non-system DLL imports. This does not replace testing Windows runtime prerequisites. |
| HTML/JS/CSS | `index.html`, inline application JavaScript/CSS, `canary_ui.js`, `update_ui.js`, and local compiled styles bundled. No remote script or stylesheet references remain. |
| Fonts | Inter 400/600/700/900 bundled. Decorative emoji use Windows system fonts. |
| Images/icons | No required project-only image or icon files. Covers come from the user's files or Canary and are converted to image data URLs; downloaded metadata/artwork is cached. |
| Audio | FFmpeg executable and pygame codecs bundled. User music stays external; a separate temporary folder containing spaces was exercised. |
| Paths | Frozen resources resolve under PyInstaller's extraction directory using `resource_path`; source file paths in debug/code metadata do not require those files at runtime. Legacy config discovery is optional. |
| Updater | Helper embedded in the main EXE; real separate-process installation/startup and rollback are tested independently. |
| Secrets | No private signing-key files, environment files, account databases, saved sessions, publisher signing modules, or broker server implementation bundled. The public verification key and public broker URL are intentional. The certifi PEM contains public CA certificates. |

## Tests against the actual release executable

The original signed 0.8.0 was first copied alone to a fresh folder under `%LOCALAPPDATA%\GRAILD-StandaloneValidation` and passed the pre-existing live packaged smoke test. Inspection then identified the CDN/font dependency and triggered the rebuild above.

The rebuilt 0.8.0 was copied alone to another freshly created folder outside the project. The test started it with that folder as the working directory, Python-related environment variables removed, and PATH restricted to Windows directories. Its offline diagnostic additionally installed a Python audit rule that rejects reads under the project directory. It used a fresh disposable user-data directory, leaving the real profile untouched.

Verified:

- Native WebView2 window and asynchronous Python/JavaScript bridge.
- Local styling and bundled Inter font rendering without CDN resources.
- Real pygame mixer initialization and decoded playback in Classic and Random modes. The offline test used the real default audio driver, not the dummy driver; the test sound is silent.
- External music folder, file recognition, and bundled FFmpeg decoding.
- Live Canary search, era checks, explicit match confirmation, metadata, artwork, era eligibility, and stale-cache fallback.
- Live public leaderboard retrieval from the packaged app, without publishing any test score.
- Broker health endpoint returned HTTP 200. A separate ephemeral OAuth-start probe returned HTTP 200, a valid Discord authorization origin, and S256 PKCE. No credentials or authorization URL were printed or stored in the report, and interactive Discord consent was not completed.
- All 65 existing regression tests passed, including updater, UI, audio, achievements, Canary, and leaderboard coverage.

Machine-readable evidence: `build/standalone-audit/v0.8.0-results.json`, `build/standalone-audit/v0.8.1-results.json`, `build/standalone-audit/archive-inspection.json`, `build/standalone-audit/discord-broker-probe.json`, and `build/beta-validation-results.json`. The archive inspection covers both the main EXEs and their embedded helpers. The update report was regenerated against the rebuilt pair: both signed 0.8.0-to-0.8.1 installation and failed-launch rollback passed, including restored saved Discord login, player settings, and Canary caches. Temporary copies of the real profile were removed; original installations and user data were untouched. Update testing uses simulated GitHub transport with real signed EXEs; live GitHub release downloads require manual publication.

## Repeat the separate-folder verification

Publisher/development commands (friends do not need these tools):

```powershell
py -3.13 verify_standalone_release.py --release dist/releases/v0.8.0 --live
py -3.13 verify_standalone_release.py --release dist/releases/v0.8.1
```

The verifier first checks the existing manifest signature and executable checksum, validates local resource references and bundled native/Python dependencies, then copies just the EXE to a unique outside-project folder. It refuses to report success if the packaged diagnostic fails or the signed artifact changes. It does not rebuild or modify release assets.

## What to upload or replace

For **v0.8.0**, upload both files from `dist/releases/v0.8.0/`:

1. `GRAILD.exe`
2. `graild-update.json`

For **v0.8.1**, use the same two names from its own folder. Replace both assets together if either version was already uploaded; do not use an archived manifest with a rebuilt executable. The assets have new checksums/signatures. The embedded helper is sufficient for friends; do not distribute private keys, test folders, project files, or Python installations. No releases were published automatically.

See [BETA_RELEASES.md](BETA_RELEASES.md) for the existing build/sign commands and release process.

## Final manual checks before broad sharing

On a friend's Windows x64 machine with no development tools, install WebView2/.NET if absent, copy just the main EXE into a user-writable folder, launch normally, choose their own music folder, and complete a fresh Discord sign-in in their browser. Check the profile and global leaderboard. After manually publishing v0.8.1, run the documented real GitHub update test. These interactive and clean-OS checks cannot be certified solely from this development machine.

Final artifacts verified after testing:

- v0.8.0 SHA-256: `19e1b141deb06da405199aa92693995991aefff60056fa3c6b6018707aeab204`
- v0.8.1 SHA-256: `b6ae2d40d415a34780bb34ca4475ceb12bd56aef29ff47770167c080b68f0429`
