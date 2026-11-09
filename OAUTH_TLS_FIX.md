# GRAIL'D 0.9.1 OAuth certificate fix

## Root cause and request trace

The desktop Discord flow first calls `POST /oauth/start` on
`https://graild-discord-broker.onrender.com`, then opens Discord in the system
browser. After the loopback callback it calls `POST /oauth/complete` on the
same broker. Both desktop HTTPS requests use `JuiceSpotApp.oauth_json_request`
in `web_app.py`, which previously called `urllib.request.urlopen` without an
explicit SSL context. The broker's own Discord requests use HTTPX separately.

Inspection of the previous Intel and Apple Silicon app ZIPs confirmed that
`GRAILD.app/Contents/Resources/certifi/cacert.pem` was already present. The
failure was trust-store selection: urllib used OpenSSL's default external CA
locations instead of selecting that bundled file. End-user Macs need not have
those external files. The first affected desktop connection is `/oauth/start`;
`/oauth/complete` has the same problem. The user's original Mac stack trace
was not available to determine which of those calls raised their error.

The live broker chain verified with trusted CA roots and hostname checking:
TLS 1.3, issuer Google Trust Services WE1, leaf subject `onrender.com`, expiry
20 December 2026. Verified requests returned HTTP 200 from `/healthz` and
HTTP 400 from both OAuth endpoints with intentionally invalid diagnostic
forms. The HTTP errors confirm successful TLS, without signing in or changing
accounts. Details are in `build/broker-certificate-verification.json` and
`build/oauth-tls-development.json`.

## Changes

- `tls_support.py`: resolve the CA file from frozen `_MEIPASS`, the macOS
  Resources layout, or development certifi. Add those roots to Python's
  default verified SSL context, preserving system/administrator roots.
- `web_app.py`: pass that context to the existing urllib OAuth helper.
- `requirements.txt`, `GRAILD-mac.spec`, `JuiceGuesserMain.spec`, `build.bat`,
  `prepare_beta_release.py`, `prepare_mac_release.py`: explicitly depend on
  certifi, collect its data, and include the new module in source handoffs.
- `test_tls_support.py`: eight regression tests cover development/frozen
  resolution, macOS Resources, missing/invalid bundles, strict verification,
  preservation of system roots, and unchanged OAuth request data.
- `mac_launcher.py`, `standalone_smoke.py`, `.github/workflows/build-macos.yml`:
  packaged diagnostics and native Intel/Apple Silicon TLS validation. The Mac
  workflow deliberately removes external CA paths and checks that an empty
  trust store rejects the broker. The diagnostic is opt-in, before GUI launch.
- `release-notes/v0.9.1.md`: describe the fix.

No OAuth state/PKCE/callback logic, account persistence, broker security,
updater implementation, or global SSL settings were changed. Certificate and
hostname verification stay enabled. Missing or invalid bundles fail closed.

## Validation and remaining release work

The Windows development suite passed 120 tests, with five native Mac-only
tests skipped. The rebuilt, signed Windows executable also passed isolated
packaged checks for bundled CAs, strict TLS verification, UI, audio and updater
resources; see `build/standalone-audit/v0.9.1-results.json`. The live broker
diagnostics passed, including rejection with
an empty trust store. Native Mac workflow execution is pending approval to
push the prepared sources and start GitHub Actions. Until that completes,
previous Mac binaries must not be represented as containing this fix.

The prepared checkout is `build/mac-release-source`; it has not been pushed
for this fix. GitHub upload/build was blocked by automatic approval review
because it would publish source and mutate the default branch. A corrected
source ZIP and architecture-specific build kits can be built locally without
publishing. Native interactive Discord consent remains a tester acceptance
check after compilation.
