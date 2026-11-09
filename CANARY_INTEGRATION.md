# Canary API v1 integration

This extends the existing Python/pywebview app. Official contract: https://canary.best/api-docs and https://canary.best/api/v1/openapi.json.

## Using it

1. Choose your local music folder as before.
2. Open Catalog > Local library > Match on Canary for a song. Filename normalization removes punctuation, track-number/artist prefixes, and searches related session/alternate titles. Candidate ranking preserves version markers and uses `tracker.alt_names` aliases when present.
3. Review the exact recording, era, category, duration, producer and dates. Choose **Confirm this recording**. Even an exact title suggestion requires confirmation. Each file keeps its own mapping; no recordings, audio, stats, or accounts are merged.
4. Song Information displays saved Canary metadata and primary artwork. Remove the metadata match to change your choice. Replacing a file invalidates its old match.
5. Catalog > Canary catalogue supports title/alias search, category, recording-era codes, and pagination. Era suggestions include observed metadata; the input accepts other Canary era codes too.
6. In either game choose a Recording era to limit rounds to automatically era-checked or confirmed, locally available songs in that era. All eras includes the whole local library. Empty eligible pools never fall back to songs outside the selected era.

All gameplay audio and answer previews continue through local files and the existing bundled decoder. No Canary audio, download, private storage, era pack, or album download routes are used.

## Structure and caching

- `canary_client.py`: reusable requests client for song search/details, catalog metadata, primary artwork, cover galleries and cover search. Uses documented `q`, `era`, `category`, `artist`, zero-based `page` and `limit` parameters.
- `canary_integration.py`: explicit file matching, persistent local mappings and bounded daemon workers.
- `canary_ui.js`: catalogue browser, Song Information and confirmation flow. Polls jobs asynchronously; stale search/dialog responses cannot overwrite newer requests.
- `web_app.py`: narrow bridge methods, cached artwork preference and local-only era eligibility. Internal service and native window references stay private to avoid recursive webview exposure.
- Metadata is stored separately from account/scoring data under the existing JuiceSpot app-data folder, in `canary_api.sqlite3` and `canary_matches.sqlite3`.
- Search cache: one hour. Catalog/details: one day. Artwork: seven days. Expired metadata can be used on connection errors, timeouts, 429, or service failure, with a visible saved-data notice. Confirmed file metadata also remains available offline. HTTP 400 and 404 return clear errors rather than silently using an unrelated cached response.
- Requests have connect/read timeouts, a shared 0.8-second minimum interval (at most about 75 starts/minute), and a 429 cooldown respecting numeric Retry-After values. No automatic retry storm. At most four background jobs are active, with bounded retained results.

## Validation

Run `py -3.13 -m unittest test_canary_client test_canary_matching test_audio_files test_game_modes test_achievements test_global_leaderboard -v`.

The opt-in diagnostic uses a temporary account, test audio and cache; it does not touch your player profile. It performs live public metadata requests, manual confirmation, artwork, era filtering, both local audio modes, offline-cache fallback, and loads the actual app HTML and bridge in a hidden native WebView2 window:

```
py -3.13 JuiceGuesserMain.py --canary-smoke-test build/canary-reference/development-smoke.json
```

After `build.bat`, run the same diagnostic against the built executable:

```
dist\JuiceGuesserMain.exe --canary-smoke-test build\canary-reference\packaged-smoke.json
```

A JSON report records each passed check or a traceback. Live Discord/Google authentication is not exercised by this diagnostic; OAuth and leaderboard server code is unchanged.

## Per-player era preferences

Era selectors on the Hub, Account, and game screen stay synchronized. All eras opts out of era filtering. A selected era is saved in `game_preferences` for the signed-in account, restored on sign-in, and cleared from the active session on sign-out. Eligibility uses only the confirmed Canary record's `era`, never filename text or embedded local tags. Existing accounts migrate automatically.

## Canary website playback option

The Hub and Account offer Local files (in-app games) or Canary website player. Preferences are stored per account. Canary Shuffle selects a random public catalog song through the documented `/songs` metadata endpoint, respecting the selected Canary recording era, then opens its API-provided `page_url` in the normal browser. Press Play on that website to listen. This does not turn API v1 into an audio API and does not fetch undocumented stream, download, or private storage URLs. The website controls audio; timed in-app games remain local-only.

A native WebView compatibility check reached Canary's public Play control but the media stalled at time zero, including a retry with app-initiated autoplay enabled. Therefore embedded Canary playback is not offered as a working feature. Website playback remains subject to Canary and the user's browser; automated audio playback in the external browser was not verified.

Refresh Canary eras derives the era list from public song metadata and caches it for a day. No era is inferred from local filename text. Local era-filtered rounds include only automatically era-checked or confirmed local songs; unmatched files do not silently enter those rounds.

## Automatic song era checks

Loading a local library starts a background era scan. Canary's complete public metadata index is cached for a day and matched locally, rather than issuing a request for every file. Exact normalized titles, exact aliases, and session naming variants (Sessions / Session Edit) are eligible. An era is assigned only when all matching metadata records agree on one nonempty era. Arbitrary alternate-version suffixes are not stripped to manufacture an era match. Conflicting eras and missing exact matches remain unassigned for review.

Automatic results are stored separately in `era_checks`, keyed by local file path, size, and modification time. They do not link recordings, alter audio files, merge stats, or override a manually confirmed recording. Unchanged checks are reused for a day, changed files are rechecked, and offline failures preserve saved results. Catalog displays progress, per-song era/review labels, and a Recheck song eras button. The era selector updates after scanning completes.

Canary-based in-app guessing remains deferred; this update does not add or modify Canary audio playback.
