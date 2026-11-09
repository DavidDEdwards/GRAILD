# GRAILD-Discord-Bot

A separate Python 3.11+ / discord.py 2.x slash-command bot for the GRAIL'D community. This directory can be copied to its own Git repository and deployed independently. It does not import, modify or package the desktop application or Discord OAuth broker. No bot credentials are included.

## Commands and actual integration status

| Command | Behaviour |
| --- | --- |
| `/graild download` | Lists recognised, actually uploaded Windows/Intel Mac/Apple Silicon app assets from published GitHub prereleases. Each platform shows its own release version; older platform releases may be used if the newest beta lacks that platform. Source/build-kit ZIPs and the updater helper are excluded. Both versioned and currently published versionless Mac package names are recognised. |
| `/graild updates` | Shows the latest beta by publication date, its version, UTC date and release notes, with a link to the full notes. Drafts and bare Git tags are excluded. |
| `/graild leaderboard` | Read-only top 10 from the existing public `GET /leaderboard`, preserving server ranks/totals. Empty boards are reported as empty, never replaced with sample scores. |
| `/graild profile` | Private/ephemeral response explaining that linked-profile lookup needs a backend interface. Receives only the invoking member's Discord ID; no member-selector or public identity lookup is exposed. **Not a working linked-profile integration yet.** |
| `/graild help` | Command list and descriptions. |

Repository: https://github.com/DavidDEdwards/GRAILD-Releases

### Backend inspection and the profile limitation

Inspected the existing `discord_oauth_broker/app.py`, the deployed-source copy in `render-broker`, and the desktop's `get_global_leaderboard` caller, without changing them. The broker provides:

- `GET /leaderboard`: public `{ "entries": [...] }`; each entry has rank, display_name, provider, points, correct and wrong.
- `POST /leaderboard/update`: requires a player's OAuth-derived bearer credential; **the bot does not call it**.
- `POST /leaderboard/revoke` and OAuth flows: **the bot does not call them**.

The public board deliberately omits Discord account IDs. The inspected API contains no authorised profile-by-Discord-ID route. The bot cannot safely reconstruct a user's identity from display names or read desktop profile files. Discord's bot token is not a credential for GRAIL'D private profile data.

To finish `/graild profile`, the backend owner must provide an approved read-only endpoint, its response schema and bot-scoped authorisation method. It must verify/authorise lookup of the invoking Discord member and return only approved profile fields. Do not supply Redis, backend-admin, desktop OAuth tokens or client secrets. No guessed URL or unused profile secret variable is included here. Implementing a new broker route requires a separate authorised backend change; this project does not alter the broker.

## 1. Create a separate Discord application

1. Open https://discord.com/developers/applications and create **GRAILD Bot** as a **new application**. Keep it separate from the existing desktop OAuth application/broker.
2. Under **General Information**, copy the **Application ID**. This identifies the application; it is not the bot token.
3. Open **Bot**, create/enable its bot user if necessary, and use **Reset Token** to obtain the bot token. Store it locally as `DISCORD_BOT_TOKEN`. Never paste it into chat, screenshots, source code or GitHub. If exposed, reset it immediately.
4. Leave **Presence Intent**, **Server Members Intent**, and **Message Content Intent** disabled. No privileged intent is used. This project does not need an Interactions Endpoint URL: discord.py receives interactions through its outgoing Gateway connection.

## 2. Find the test server ID

In Discord, enable **User Settings > Advanced > Developer Mode**. Right-click your test server icon and select **Copy Server ID**. Set `DISCORD_GUILD_ID` to that number, not a channel ID or your own account ID. Public commands always register globally. The optional test server ID identifies the old guild-specific /graild registration for automatic cleanup after global sync succeeds.

## 3. Install in the test server

Use the Developer Portal's installation/OAuth2 URL generator with **Guild Install**, scopes **bot** and **applications.commands**, and only:

- View Channels
- Send Messages
- Embed Links

Do not select Administrator, Manage Server, Manage Roles, members/presence/message-content intents or unrelated permissions. Permissions integer for the three listed permissions is `19456`.

Replace YOUR_APPLICATION_ID in:

```text
https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&scope=bot%20applications.commands&permissions=19456
```

Open the link, choose your test server and authorise installation. Your Discord account needs permission to install apps there. Allow members to use application commands in the test channel. Channel permission overrides can block the bot even if its invite requested the correct permissions.

## 4. Configure and run locally

Open a terminal **inside GRAILD-Discord-Bot**. On Windows:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

A virtual environment was already created/tested on the development computer; it is not distributed or committed. If the Windows `py` launcher is unavailable, use your installed Python executable for the venv command.

On macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally:

```dotenv
DISCORD_BOT_TOKEN=your_actual_bot_token
DISCORD_APPLICATION_ID=your_application_id
DISCORD_GUILD_ID=your_test_server_id
DISCORD_COMMAND_SCOPE=global
GRAILD_BACKEND_URL=https://graild-discord-broker.onrender.com
```

Then run:

```powershell
.\.venv\Scripts\python.exe bot.py
```

or on macOS/Linux:

```bash
.venv/bin/python bot.py
```

The code reads only its own `.env`, with real process environment variables taking precedence. Leave it running; Ctrl+C stops the bot and closes its HTTP sessions. Do not run multiple copies during registration. Commands sync once in `setup_hook`, not on every Gateway reconnect. No command sends unsolicited announcements or DMs.

## 5. Test every command

In the test server, type `/graild` and check all five subcommands:

1. **help**: private purple command list.
2. **download**: links match assets actually attached to published prereleases. A missing platform must not appear. No build-kit ZIP should be offered. If no app assets exist, it says so.
3. **updates**: compare version, publication date and notes against GitHub. Long notes link to the full release; mentions cannot ping members.
4. **leaderboard**: compare the displayed top 10 against the live public backend. No invented fallback scores. An empty board is legitimate. This integration is only verified when a real request passes.
5. **profile**: private backend-interface-unavailable explanation, not fabricated profile statistics. Other members must not see it. This command intentionally remains incomplete pending an approved endpoint.
6. Repeat commands quickly to check cooldown responses. Test an unavailable backend or offline network using a separate local test configuration; requests should fail safely after the configured timeout rather than hang. Slow commands acknowledge immediately with deferred responses.

Run isolated automated tests (no token, Discord connection or real messages):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Run the bot clients against real **public**, read-only services without Discord:

```powershell
.\.venv\Scripts\python.exe check_live.py
```

It writes `LIVE_CHECK_RESULTS.json` with time/status, entry count and platform/version availability, but no player names, credentials or private data. It never posts a score. This is not a test of Discord authentication, actual slash-command delivery or private-profile authorisation. Check the results file for the latest live-test outcome; failures must not be described as working integrations.

## 6. Caching and response limits

All web requests use aiohttp asynchronously with a 15-second total timeout and 5-second connection timeout. JSON responses are bounded to 2 MB. GitHub release pages cache for five minutes and the leaderboard for one minute, in process memory only. Concurrent identical service requests share a lock to avoid request storms. GitHub lookup examines at most the first 500 releases (five pages of 100), considers only published prereleases and orders them by publication date. HTTP errors, rate limits, invalid JSON, timeouts and invalid leaderboard totals return safe responses. No stale cache is labelled as current following a failed refresh.

Discord responses are bounded to embed limits. Per-user command cooldowns reduce accidental spam. Member display names are escaped and messages disable mentions. Only approved leaderboard fields are copied into responses. `/profile` always uses the authenticated interaction's own user ID.

## 7. Global command registration

All public commands are loaded in the command tree before synchronization in `setup_hook`. Startup syncs globally once; Gateway reconnects do not sync again. The legacy `DISCORD_COMMAND_SCOPE=guild` setting is accepted for compatibility but no longer restricts registration. No credential changes are needed.

Startup logs the number of synchronized top-level groups and all five subcommand names. A failed global sync stops startup with an error. After successful global sync, the bot removes only its old guild-specific `/graild` slash group from `DISCORD_GUILD_ID`, if present. Other guild commands are preserved. Cleanup failure is logged and retried next startup; global commands remain registered.

Stop the old bot with Ctrl+C, then double-click `Start Bot.cmd` once (or run `.\.venv\Scripts\python.exe bot.py`). Check for the global synchronization success log. Test all five `/graild` subcommands in both servers. Discord may need time to show global updates; refresh the client if needed. Profile lookup still reports its existing backend limitation.

## 8. Always-on hosting: separate Render background worker

Create a new Git repository for **this directory only**. Commit `.env.example` but never `.env` or `.venv`. Do not deploy the desktop project or replace the existing OAuth broker service.

On Render:

1. Choose **New > Background Worker**, connect the bot's own source repository, and select a Python runtime. This bot needs an always-running process, not a static site or a web service waiting for a listening port.
2. Build command: `pip install -r requirements.txt`.
3. Start command: `python bot.py`.
4. Add `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, optional `DISCORD_APPLICATION_ID`, `DISCORD_COMMAND_SCOPE=global`, and `GRAILD_BACKEND_URL` in Render's environment settings. Use a supported Python 3.11+ runtime (3.13 was tested locally).
5. Select an appropriate always-on worker plan after checking its current cost. Run one instance. No public inbound port, database, Redis instance or administrator credential is required by the bot.
6. Deploy manually, check startup logs for successful guild registration, and test the commands in the server. Store the token in hosting secrets, never the repository. Rotate it if exposed. The worker needs outbound HTTPS and Discord Gateway/WebSocket access.
7. Keep the existing `graild-discord-broker` deployment unchanged. If it sleeps or is unavailable, leaderboard requests may time out; the bot reports that rather than inventing data.

A VPS/service manager running `python bot.py` continuously is also possible. GitHub Actions is not an always-on bot host. Hosting costs, deployment and Discord messages were not initiated automatically.

## Files

`bot.py`: slash commands/lifecycle/configuration; `graild_api.py`: existing backend's public adapter and explicit profile limitation; `github_releases.py`: published beta/app asset discovery; `http_client.py`: async bounded requests/cache; `tests/`: offline coverage; `check_live.py`: public live verification; `.env.example`: credential variable names only.

No backend administrator functionality exists. Registration settings and credentials are operator-controlled process configuration, not user-supplied slash arguments. Intents are restricted to the non-privileged guild intent; no chat history, local player files or private profiles are read.

## Official references

- Discord application setup: https://docs.discord.com/developers/quick-start/getting-started
- discord.py commands, sync and deferred responses: https://discordpy.readthedocs.io/en/stable/interactions/api.html
- Discord permissions: https://docs.discord.com/developers/topics/permissions
- GitHub's prerelease-aware release listing: https://docs.github.com/en/rest/releases/releases#list-releases
- Render workers: https://render.com/docs/background-workers

Published Mac packages may be an outer Actions artifact ZIP containing the app ZIP. Extract the downloaded package and, if present, its inner app ZIP to get GRAILD.app. The bot links the actual published URL without renaming or constructing an unpublished download.


## Verification completed for this initial project

18 offline automated tests passed, and pip reported no dependency conflicts. The bot's own aiohttp clients also passed read-only requests to the real services on 2026-11-01: the public leaderboard returned one entry; GitHub returned `v0.9.0_MAC` as the latest published beta, with both Mac platforms available, and Windows available from `v0.8.1`. See LIVE_CHECK_RESULTS.json for the exact UTC test time. This is API-level verification, not an in-server Discord test.

No Discord token or test guild ID was supplied, no real slash-command registration/Discord connection occurred, and no messages were sent. Linked-profile integration remains unavailable because the existing backend has no authorised interface for it. The desktop app and OAuth broker were not changed.
