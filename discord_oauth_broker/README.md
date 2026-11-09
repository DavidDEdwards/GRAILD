# GRAIL'D Discord OAuth Broker

## Global account tags (0.9.1)

The owner can create custom tags in Account → Profile, with a name of up to 32
characters and a hover description of up to 240 characters. Choose the tag when
assigning by Discord ID, from the registered-player list, or on a leaderboard row.
Custom tags are global display labels; they do not grant owner permissions.

`GET /account/tags/catalog` lists assignable tags for the owner.
`POST /account/tags/create` accepts form fields `name` and `description` and
creates a unique, case-insensitive custom name. Built-in names are reserved.
Assignment endpoints accept `beta_tester` or an existing `custom_…` tag ID.
Only the owner can create or assign custom tags; Owner and Top earner remain protected.

Deploy `app.py` together with `tag_rules.py` and the updated Dockerfile. No Redis
reset or migration command is needed. The default verified owner is Discord user
`1119220334873288777`, as configured by the publisher. Set
`GRAILD_OWNER_DISCORD_IDS` to a comma-separated list to override it; an explicitly
empty value disables owner access. This is a public account identifier, not a secret.

Tags are keyed to the verified provider and subject, never to a local username or
the desktop's old `is_creator` flag. Signing into the same Discord or Google
account on another installation returns the same tags. Different provider
accounts remain separate global identities. The owner can choose registered
players from Account → Profile and assign/remove Beta Tester. Existing local
assignments must be granted globally once; they are not trusted as owner grants.

Authenticated endpoints:

- `GET /account/tags`: read this verified identity's global tags and public player ID.
- `POST /account/tags/sync`: form field `achievement_ids`, a JSON list of unlocked IDs.
  All 50 known achievement IDs unlock Top earner permanently. Progress is reported
  by the desktop, as with the existing global score sync; this is not server-verified gameplay.
- `GET /account/tag-players`: owner-only list of registered players, with public IDs.
- `POST /account/tags/assign`: owner-only `player_id`, `tag_id=beta_tester`,
  and `assigned=true|false`. Owner and earned tags cannot be assigned manually.
- `POST /account/tags/discord`: owner-only `discord_id` (numeric), `tag_id=beta_tester`,
  and `assigned=true|false`. This also supports accounts that have not signed in
  yet; the tag is recognized once that verified Discord identity signs in.
  The desktop accepts IDs or Discord mentions and also exposes owner actions on
  global leaderboard entries. Usernames are not used as identity keys.

Use the same existing bearer session as the leaderboard. Tokens and private
provider subjects are never included in tag or leaderboard responses. Tags are
stored in persistent Redis keys without expiry. Leaderboard entries receive
their tags from these server records, not from submitted client labels.

The desktop refreshes tags asynchronously and caches the last server grants for
offline display, bound to the signed-in local account, broker, and provider session.

This is a separate HTTPS service for Discord sign-in from the GRAIL'D Windows desktop app. The desktop app does not contain a Discord client secret. The broker owns the Discord OAuth code exchange and returns only a short-lived, single-use identity ticket to the desktop app.

## Desktop contract

The existing Python desktop code sends `application/x-www-form-urlencoded` requests:

- `POST /oauth/start`: `provider=discord`, the desktop-generated `state`, and its temporary `redirect_uri` (currently `http://127.0.0.1:<port>/`). The response is `{ "authorization_url": "https://discord.com/..." }`.
- Discord redirects to the broker's registered HTTPS callback at `/oauth/callback`. The broker exchanges Discord's code server-side and redirects to the desktop loopback URI with `ticket`, the original desktop `state`, and `iss=https://discord.com`.
- `POST /oauth/complete`: `provider`, `state`, `ticket`, and the same `redirect_uri`. The response contains `subject`, optional `email`, `display_name`, and `username`, matching what the desktop account code consumes.

The broker restricts desktop redirects to `http://127.0.0.1:<valid-port>/`. It binds state to that redirect, verifies Discord's issuer, uses PKCE, and stores state/tickets in Redis with expiry. Ticket redemption atomically checks both the desktop state and redirect URI and consumes the ticket exactly once. Access and refresh tokens are not stored.

## Requirements

- A Linux server or VM with Docker and Docker Compose v2.
- A domain name whose DNS points to that server.
- Inbound TCP ports 80 and 443 allowed so Caddy can issue and renew HTTPS certificates.
- A Discord Developer application with its client ID and client secret.
- Python 3.11+ only if running tests or running the service directly without Docker.

## 1. Register the Discord callback

1. Open the Discord Developer Portal and create/select the GRAIL'D OAuth application.
2. In OAuth2 settings, add this redirect URI, replacing the example domain with your real broker domain:

   `https://oauth.example.com/oauth/callback`

3. Save the settings and copy the application's client ID and client secret. The secret belongs only on the broker server; do not put it in `web_app.py`, `index.html`, `build.bat`, or the desktop environment.

## 2. Configure and deploy the broker

Copy `.env.example` to `.env` on the server. Replace each placeholder with your own values:

- `BROKER_DOMAIN`: the public DNS hostname, without `https://`.
- `DISCORD_CLIENT_ID`: the Discord application's client ID.
- `DISCORD_CLIENT_SECRET`: the Discord application's secret. Keep this only in the server's ignored `.env` or its secret manager.
- `DISCORD_REDIRECT_URI`: exactly `https://<BROKER_DOMAIN>/oauth/callback`; it must match the Discord Developer Portal entry.
- `REDIS_URL`: leave as `redis://redis:6379/0` for the supplied Compose stack.

Start the services from this folder:

```sh
docker compose up --build -d
```

Caddy terminates public HTTPS and forwards requests to FastAPI. Redis is not published to the public network and stores temporary OAuth state/tickets. Check service status with `docker compose ps`; check broker readiness at `https://<BROKER_DOMAIN>/healthz`. The health route does not reveal configuration or secrets.

For updates, pull/copy the new broker source and run `docker compose up --build -d` again. Back up the `redis_data` volume if you need active in-flight OAuth transactions to survive server maintenance; expired transactions do not need to be restored.

## 3. Point the Windows app at the broker

In PowerShell, set the public HTTPS broker origin before launching the desktop executable:

```powershell
$env:GRAILD_DISCORD_BROKER_URL = "https://oauth.example.com"
.\dist\JuiceGuesserMain.exe
```

Replace the example hostname with yours. This variable is not a secret. The desktop app submits the loopback redirect to `/oauth/start`; the broker uses it only after strict loopback validation.

## 4. Run the broker tests

On a development machine, from this folder:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements-dev.txt
py -m pytest -q
```

The tests use a fake Redis store and mocked Discord endpoints; they do not require real Discord credentials or claim that a live provider deployment has been tested. A live test requires your own registered application, HTTPS domain, Redis service, and secrets.

## Security and operations

- Keep `.env` private; it is excluded by `.gitignore`. Rotate the Discord secret immediately if it is exposed.
- Do not put the Discord secret into the Windows executable or `GRAILD_DISCORD_BROKER_URL`.
- Redis must remain private to the Compose network. Do not publish port 6379.
- Run behind HTTPS only. Caddy needs a public DNS record and reachable ports 80/443.
- Uvicorn access logs are disabled because callback URLs carry one-time authorization codes. Keep reverse-proxy logs configured not to record query strings.
- The broker accepts only Discord's issuer, short-lived state, and the exact loopback redirect supplied at `/oauth/start`; a completed or mismatched ticket cannot be redeemed again.
- No CORS access is needed: the desktop Python bridge calls the broker directly.

## Global leaderboard deployment

The desktop global leaderboard requires the current `app.py` from this directory on the broker server. A `404` from `GET /leaderboard` means that the running deployment does not provide the required route. Rebuilding the Windows executable does not update the server.

Deploy the updated broker source to the existing service, preserving its Discord and Redis environment settings. For the Docker Compose setup above, run `docker compose up --build -d` from this directory. For the existing hosted service, deploy the updated source through the account that manages that service.

Verify `GET /healthz` returns `{"status":"ok"}` and `GET /leaderboard` returns `{"entries":[]}` or a populated entries array. Then reconnect Google or Discord once in the desktop Account tab and refresh the leaderboard. OAuth completion now issues an encrypted-at-rest desktop bearer credential; credentials from an older sign-in cannot sync scores.

Redis contains persistent leaderboard profiles and totals in addition to expiring OAuth/session records. Preserve the Redis volume when deploying updates. Scores are client-reported lifetime totals, so this leaderboard does not enforce competitive anti-cheat validation.
