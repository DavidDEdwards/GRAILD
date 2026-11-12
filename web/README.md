# GRAIL'D web edition (stage 1)

A browser version of GRAIL'D. Players pick a music folder on their own device,
the browser plays short snippets, and they guess the song. No `.exe`, no
server, no uploads.

- **Music never leaves the device.** The browser reads the files locally. Song
  audio is never uploaded or hosted anywhere.
- **Stats live in the browser** (`localStorage`): points, streaks, grails and
  the 48 achievements from the desktop app (the two Google/Discord ones need
  sign-in, so they are left out).
- **Chrome / Edge** remember the chosen folder (File System Access API), so next
  visit it is one click to reopen. **Firefox / Safari** use the standard folder
  picker and ask again each visit.
- **Canary** (canary.best) is used only after a round ends, to show cover art,
  era and a link. Only the song title is sent. Answers are cached for a day, and
  if Canary says "too many requests" (HTTP 429) the page waits as long as it
  asks. Players can turn this off in Settings.

**Game modes** (the **Games** tab), same rules as the desktop app:

- **Classic Snippets**: guess from the intro; each attempt reveals more.
- **Random Drop**: guess from a random moment that stays fixed for the round.
- **Challenges**, played with the chosen game and difficulty. Personal bests
  are saved in the browser:
  - **Sudden Death**: one wrong guess ends the run (skipping is allowed).
  - **Three Lives**: each missed song costs a life.
  - **Time Attack**: 90 seconds; songs load and play by themselves.
  - **Sprint**: ten songs, most points wins.
- **Canary Shuffle**: no folder needed; picks a random song from Canary's
  catalogue and links to Canary's own player.

Not in the web edition yet: sign-in, the global leaderboard, the updater.

## What is in this folder

| File | What it does |
| --- | --- |
| `index.html` | The page (same look as the desktop app). |
| `web.css` | A few extra styles for the web edition. |
| `assets/` | Copies of the desktop app's `tailwind.css`, `graild-ui.css`, fonts and logo. |
| `js/game-core.js` | The game rules, ported from `web_app.py`, `audio_files.py`, `achievements.py` and `assets/graild-challenges.js`. |
| `js/audio.js` | Plays snippets with the Web Audio API (replaces pygame/FFmpeg and `random_snippets.py`). |
| `js/library.js` | Folder picking and remembering the folder. |
| `js/canary.js` | Optional Canary song details and Canary Shuffle, with caching and rate-limit handling. |
| `js/app.js` | Connects the buttons on the page to the game. |
| `tests/` | Tests for the game rules. Open `/tests/` in the browser. |
| `_headers` | Security headers that Cloudflare Pages adds to every page. |

There is no build step: these files are the website.

## Try it on your computer

The page uses JavaScript modules, which browsers refuse to load from a
double-clicked file, so it needs a tiny local web server. Python has one built
in. From the project folder run:

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory web
```

Then open <http://localhost:8000> in Chrome or Firefox, click **Choose a music
folder** and play. The rule tests are at <http://localhost:8000/tests/>. Stop
the server with `Ctrl+C`.

## Publish it for free on Cloudflare Pages

Cloudflare Pages hosts static sites like this one for free, with HTTPS. Pick
one of these two ways.

### Option A: drag and drop (simplest, no Git needed)

1. Sign in at <https://dash.cloudflare.com> (a free account is enough).
2. Go to **Workers & Pages** → **Create** → **Pages** → **Upload assets**.
3. Name the project, for example `graild`. The site will be
   `https://graild.pages.dev`.
4. Drag the **`web` folder** (this folder) onto the upload box and click
   **Deploy site**.
5. To update later: open the project → **Create new deployment** → upload the
   `web` folder again.

### Option B: deploy automatically from GitHub

1. Push this repository to GitHub (it already has the `web/` folder).
2. In Cloudflare: **Workers & Pages** → **Create** → **Pages** →
   **Connect to Git**, and choose the repository.
3. Build settings:
   - **Framework preset:** None
   - **Build command:** leave empty
   - **Build output directory:** `web`
4. Click **Save and Deploy**. Every push to the chosen branch now updates the
   site within about a minute. (This is a separate service from the Render
   sign-in broker; it does not touch it.)

Optional: under the project's **Custom domains** tab you can add your own
domain instead of `*.pages.dev`.

### GitHub Pages (what this repository uses)

`.github/workflows/pages.yml` publishes the `web` folder to
<https://daviddedwards.github.io/GRAILD/> whenever something in `web/` changes
on the `main` branch. You can also start it by hand: GitHub → **Actions** →
**Publish web edition to GitHub Pages** → **Run workflow**.

One-time setup: GitHub → the repository → **Settings** → **Pages** → under
**Build and deployment**, set **Source** to **GitHub Actions**.

GitHub Pages cannot send the `_headers` file, so the same security rules are
also in a `<meta http-equiv="Content-Security-Policy">` tag in `index.html`.

## Browser notes

- Which formats play depends on the browser. MP3, M4A/AAC, WAV, OGG and FLAC
  work in current Chrome, Edge and Firefox. WMA, APE and similar desktop-only
  formats do not; those songs are skipped with a message.
- Each snippet decodes the whole song in memory first, so a very long file can
  take a second to start on slow devices.
- The page must be served over `https://` (or `localhost`) for the folder
  picker and audio to work. Cloudflare Pages does this automatically.
