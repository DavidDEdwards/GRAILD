"""Discord OAuth broker for the GRAIL'D Windows desktop client."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import urllib.parse
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from redis.asyncio import Redis
from tag_rules import ACHIEVEMENT_IDS, TAGS

DISCORD_ISSUER = "https://discord.com"
DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/v10/users/@me"
CALLBACK_PATH = "/oauth/callback"
STATE_TTL_SECONDS = 600
TICKET_TTL_SECONDS = 120
REDIS_PREFIX = "graild-discord-oauth:v1:"
GLOBAL_SESSION_TTL_SECONDS = 90 * 24 * 60 * 60
GLOBAL_SESSION_PREFIX = f"{REDIS_PREFIX}global-session:"
GLOBAL_LEADERBOARD_SCORES = f"{REDIS_PREFIX}leaderboard:scores"
GLOBAL_LEADERBOARD_PROFILES = f"{REDIS_PREFIX}leaderboard:profiles"
GLOBAL_PLAYERS = f"{REDIS_PREFIX}players"
GLOBAL_TAG_PREFIX = f"{REDIS_PREFIX}tag:"
GLOBAL_CUSTOM_TAGS = f"{REDIS_PREFIX}custom-tags"
STATE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

CONSUME_TICKET_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local ticket = cjson.decode(raw)
if ticket.desktop_state ~= ARGV[1] or ticket.redirect_uri ~= ARGV[2] then
  return -1
end
redis.call('DEL', KEYS[1])
return raw
"""


@dataclass(frozen=True)
class Settings:
  discord_client_id: str
  discord_client_secret: str
  discord_redirect_uri: str
  redis_url: str
  owner_discord_ids: str = "1119220334873288777"

  @classmethod
  def from_env(cls) -> "Settings":
    return cls(
        discord_client_id=os.environ.get("DISCORD_CLIENT_ID", "").strip(),
        discord_client_secret=os.environ.get("DISCORD_CLIENT_SECRET", ""),
        discord_redirect_uri=os.environ.get("DISCORD_REDIRECT_URI", "").strip(),
        redis_url=os.environ.get("REDIS_URL", "redis://redis:6379/0").strip(),
        owner_discord_ids=os.environ.get("GRAILD_OWNER_DISCORD_IDS", "1119220334873288777").strip(),
    )

  def validate(self) -> None:
    if not self.discord_client_id or not self.discord_client_secret:
      raise RuntimeError("DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET must be set on the broker.")
    parsed = urllib.parse.urlsplit(self.discord_redirect_uri)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path != CALLBACK_PATH
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
      raise RuntimeError(
          "DISCORD_REDIRECT_URI must be the public HTTPS callback ending in /oauth/callback."
      )
    if not self.redis_url:
      raise RuntimeError("REDIS_URL must point to a Redis 7 service.")
    if any(not re.fullmatch(r'[0-9]{15,22}', value.strip()) for value in self.owner_discord_ids.split(',') if value.strip()):
      raise RuntimeError('GRAILD_OWNER_DISCORD_IDS must contain numeric Discord user IDs separated by commas.')


def desktop_redirect_is_valid(value: str) -> bool:
  """Only permit the exact temporary IPv4 loopback redirect used by web_app.py."""
  try:
    parsed = urllib.parse.urlsplit(value)
    port = parsed.port
  except ValueError:
    return False
  return bool(
      parsed.scheme == "http"
      and parsed.hostname == "127.0.0.1"
      and port is not None
      and 1 <= port <= 65535
      and parsed.path == "/"
      and not parsed.query
      and not parsed.fragment
      and not parsed.username
      and not parsed.password
  )


def parse_form(body: bytes, content_type: str, required: tuple[str, ...]) -> dict[str, str]:
  if content_type.split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
    raise HTTPException(status_code=415, detail="Expected application/x-www-form-urlencoded.")
  if len(body) > 8192:
    raise HTTPException(status_code=413, detail="Request is too large.")
  try:
    values = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
  except (UnicodeDecodeError, ValueError):
    raise HTTPException(status_code=400, detail="Malformed form data.") from None
  result: dict[str, str] = {}
  for name in required:
    items = values.get(name, [])
    if len(items) != 1 or not items[0]:
      raise HTTPException(status_code=400, detail=f"Missing or repeated field: {name}.")
    result[name] = items[0]
  return result


async def issue_global_session(redis: Any, identity: dict[str, str | None]) -> str:
  token = secrets.token_urlsafe(32)
  session_key = GLOBAL_SESSION_PREFIX + hashlib.sha256(token.encode("ascii")).hexdigest()
  session_value = json.dumps({
      "provider": identity["provider"],
      "subject": identity["subject"],
      "display_name": identity.get("display_name") or "",
  }, separators=(",", ":"))
  stored = await redis.set(
      session_key,
      session_value,
      ex=GLOBAL_SESSION_TTL_SECONDS,
      nx=True,
  )
  if not stored:
    raise HTTPException(status_code=503, detail="Could not create leaderboard session.")
  await register_global_player(redis, identity)
  return token


def global_player_id(identity):
  return hashlib.sha256(f"{identity['provider']}:{identity['subject']}".encode()).hexdigest()


async def register_global_player(redis, identity):
  player_id = global_player_id(identity)
  await redis.hset(GLOBAL_PLAYERS, player_id, json.dumps({
      'provider': identity['provider'], 'subject': identity['subject'],
      'display_name': identity.get('display_name') or identity['provider'].title() + ' player',
  }))
  return player_id


async def authenticated_global_identity(request: Request) -> dict[str, str]:
  authorization = request.headers.get("authorization", "")
  scheme, separator, token = authorization.partition(" ")
  if not separator or scheme.casefold() != "bearer" or not token:
    raise HTTPException(status_code=401, detail="A valid leaderboard bearer token is required.")
  key = GLOBAL_SESSION_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()
  value = await request.app.state.redis.get(key)
  if not value:
    raise HTTPException(status_code=401, detail="Leaderboard session expired or was revoked.")
  try:
    identity = json.loads(value)
  except (TypeError, ValueError):
    await request.app.state.redis.delete(key)
    raise HTTPException(status_code=401, detail="Leaderboard session is invalid.") from None
  if identity.get("provider") not in ("google", "discord") or not identity.get("subject"):
    await request.app.state.redis.delete(key)
    raise HTTPException(status_code=401, detail="Leaderboard session is invalid.")
  return identity


def make_app(
    settings: Settings | None = None,
    redis_client: Any | None = None,
    http_client: Any | None = None,
) -> FastAPI:
  config = settings or Settings.from_env()
  owns_redis = redis_client is None
  owns_http = http_client is None

  @asynccontextmanager
  async def lifespan(app: FastAPI):
    config.validate()
    if owns_redis:
      app.state.redis = Redis.from_url(config.redis_url, decode_responses=True)
    else:
      app.state.redis = redis_client
    if owns_http:
      app.state.http = httpx.AsyncClient(
          timeout=httpx.Timeout(15.0, connect=5.0),
          follow_redirects=False,
          headers={"User-Agent": "GRAILD-Discord-OAuth-Broker/1.0"},
      )
    else:
      app.state.http = http_client
    await app.state.redis.ping()
    try:
      yield
    finally:
      if owns_http:
        await app.state.http.aclose()
      if owns_redis:
        await app.state.redis.aclose()

  app = FastAPI(
      title="GRAIL'D Discord OAuth Broker",
      docs_url=None,
      redoc_url=None,
      openapi_url=None,
      lifespan=lifespan,
  )
  owner_ids = {value.strip() for value in config.owner_discord_ids.split(',') if value.strip()}

  def is_owner(identity):
    return identity['provider'] == 'discord' and identity['subject'] in owner_ids

  async def tag_definitions():
    custom = await app.state.redis.hgetall(GLOBAL_CUSTOM_TAGS)
    return {**TAGS, **{tag_id: json.loads(raw) for tag_id, raw in custom.items()}}

  async def global_tags(identity, definitions=None):
    player_id = global_player_id(identity)
    tags = [{**TAGS['owner'], 'awarded_at': None}] if is_owner(identity) else []
    definitions = definitions if definitions is not None else await tag_definitions()
    for tag_id, definition in definitions.items():
      if tag_id == 'owner':
        continue
      raw = await app.state.redis.get(GLOBAL_TAG_PREFIX + player_id + ':' + tag_id)
      if raw:
        tags.append({**definition, 'awarded_at': json.loads(raw)['awarded_at']})
    return {'player_id': player_id, 'provider': identity['provider'], 'tags': tags,
            'can_manage_tags': is_owner(identity)}

  @app.post('/account/tags/sync')
  async def sync_account_tags(request: Request):
    identity = await authenticated_global_identity(request)
    form = parse_form(await request.body(), request.headers.get('content-type', ''), ('achievement_ids',))
    try:
      ids = json.loads(form['achievement_ids'])
      if not isinstance(ids, list) or len(ids) > 50 or any(not isinstance(item, str) for item in ids):
        raise ValueError()
      if not set(ids) <= ACHIEVEMENT_IDS or len(set(ids)) != len(ids):
        raise ValueError()
    except (ValueError, TypeError):
      raise HTTPException(status_code=400, detail='Expected up to 50 distinct, recognized achievement IDs.') from None
    player_id = await register_global_player(app.state.redis, identity)
    if set(ids) == ACHIEVEMENT_IDS:
      await app.state.redis.set(GLOBAL_TAG_PREFIX + player_id + ':top_earner',
                                json.dumps({'awarded_at': int(time.time())}), nx=True)
    return {'success': True, **await global_tags(identity)}

  @app.get('/account/tags')
  async def get_account_tags(request: Request):
    identity = await authenticated_global_identity(request)
    await register_global_player(app.state.redis, identity)
    return {'success': True, **await global_tags(identity)}

  @app.get('/account/tag-players')
  async def tag_players(request: Request):
    identity = await authenticated_global_identity(request)
    if not is_owner(identity):
      raise HTTPException(status_code=403, detail='Only the verified owner can manage global tags.')
    players = await app.state.redis.hgetall(GLOBAL_PLAYERS)
    accounts = []
    definitions = await tag_definitions()
    for player_id, raw in players.items():
      player = json.loads(raw)
      tags = await global_tags(player, definitions)
      accounts.append({'player_id': player_id, 'display_name': player['display_name'],
                       'provider': player['provider'], 'tag_ids': [tag['id'] for tag in tags['tags']],
                       'beta_tester': any(t['id'] == 'beta_tester' for t in tags['tags'])})
    return {'success': True, 'accounts': sorted(accounts, key=lambda p: (p['display_name'].casefold(), p['player_id']))}

  @app.post('/account/tags/assign')
  async def assign_account_tag(request: Request):
    identity = await authenticated_global_identity(request)
    if not is_owner(identity):
      raise HTTPException(status_code=403, detail='Only the verified owner can manage global tags.')
    form = parse_form(await request.body(), request.headers.get('content-type', ''), ('player_id', 'tag_id', 'assigned'))
    await check_assignable_tag(form['tag_id'], form['assigned'])
    if not re.fullmatch(r'[a-f0-9]{64}', form['player_id']):
      raise HTTPException(status_code=400, detail='Invalid global player ID.')
    if not await app.state.redis.hget(GLOBAL_PLAYERS, form['player_id']):
      raise HTTPException(status_code=404, detail='This player must sign in before a tag can be assigned.')
    return await store_assigned_tag(identity, form['player_id'], form['assigned'] == 'true', form['tag_id'])

  async def check_assignable_tag(tag_id, assigned):
    definition = (await tag_definitions()).get(tag_id)
    if not definition or tag_id == 'owner' or definition['kind'] != 'assigned' or assigned not in ('true', 'false'):
      raise HTTPException(status_code=400, detail='Choose an assignable tag. Owner and earned tags cannot be assigned manually.')
    return definition

  async def store_assigned_tag(identity, player_id, assigned, tag_id):
    key = GLOBAL_TAG_PREFIX + player_id + ':' + tag_id
    if assigned:
      await app.state.redis.set(key, json.dumps({'awarded_at': int(time.time()),
                                               'assigned_by': global_player_id(identity)}), nx=True)
    else:
      await app.state.redis.delete(key)
    definition = (await tag_definitions())[tag_id]
    return {'success': True, 'message': definition['name'] + ' tag ' + ('assigned.' if assigned else 'removed.')}

  @app.get('/account/tags/catalog')
  async def custom_tag_catalog(request: Request):
    identity = await authenticated_global_identity(request)
    if not is_owner(identity):
      raise HTTPException(status_code=403, detail='Only the verified owner can manage custom tags.')
    return {'success': True, 'entries': [tag for tag_id, tag in (await tag_definitions()).items()
                                       if tag_id != 'owner' and tag['kind'] == 'assigned']}

  @app.post('/account/tags/create')
  async def create_custom_tag(request: Request):
    identity = await authenticated_global_identity(request)
    if not is_owner(identity):
      raise HTTPException(status_code=403, detail='Only the verified owner can create custom tags.')
    form = parse_form(await request.body(), request.headers.get('content-type', ''), ('name', 'description'))
    name, description = ' '.join(form['name'].split()), form['description'].strip()
    reserved = {'owner', 'creator', 'owner / creator', 'owner/creator'} | {tag['name'].casefold() for tag in TAGS.values()}
    if not 1 <= len(name) <= 32 or not 1 <= len(description) <= 240 or name.casefold() in reserved or any(ord(c) < 32 or ord(c) == 127 for c in name + description):
      raise HTTPException(status_code=400, detail='Use a unique tag name (1–32 characters) and hover description (1–240 characters). Built-in names are reserved.')
    tag_id = 'custom_' + hashlib.sha256(name.casefold().encode()).hexdigest()[:24]
    definition = {'id': tag_id, 'name': name, 'description': description, 'kind': 'assigned'}
    if not await app.state.redis.hsetnx(GLOBAL_CUSTOM_TAGS, tag_id, json.dumps(definition)):
      raise HTTPException(status_code=409, detail='A tag with that name already exists. Choose it from the tag list.')
    return {'success': True, 'message': 'Custom tag created.', 'tag': definition}

  @app.post('/account/tags/discord')
  async def assign_discord_tag(request: Request):
    identity = await authenticated_global_identity(request)
    if not is_owner(identity):
      raise HTTPException(status_code=403, detail='Only the verified owner can manage global tags.')
    form = parse_form(await request.body(), request.headers.get('content-type', ''), ('discord_id', 'tag_id', 'assigned'))
    if not re.fullmatch(r'[0-9]{15,22}', form['discord_id']):
      raise HTTPException(status_code=400, detail='Enter a numeric Discord user ID.')
    await check_assignable_tag(form['tag_id'], form['assigned'])
    player_id = global_player_id({'provider': 'discord', 'subject': form['discord_id']})
    result = await store_assigned_tag(identity, player_id, form['assigned'] == 'true', form['tag_id'])
    result['message'] += ' The change applies when that Discord account signs in on any device.'
    return result

  @app.middleware("http")
  async def no_store_and_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response

  @app.get("/healthz")
  async def health(request: Request):
    try:
      await request.app.state.redis.ping()
    except Exception:
      raise HTTPException(status_code=503, detail="Broker storage unavailable.") from None
    return {"status": "ok"}

  @app.post("/oauth/google/verify")
  async def google_verify(request: Request):
    form = parse_form(await request.body(), request.headers.get("content-type", ""),
                      ("access_token",))
    if len(form["access_token"]) > 8192:
      raise HTTPException(status_code=400, detail="Invalid Google access token.")
    try:
      response = await request.app.state.http.get(
          "https://openidconnect.googleapis.com/v1/userinfo",
          headers={"Authorization": f"Bearer {form['access_token']}", "Accept": "application/json"},
      )
      response.raise_for_status()
      user = response.json()
    except (httpx.HTTPError, ValueError) as error:
      raise HTTPException(status_code=401, detail="Google identity could not be verified.") from error
    subject = str(user.get("sub") or "")
    if not subject or len(subject) > 256 or user.get("email_verified") is not True:
      raise HTTPException(status_code=401, detail="Google account email is not verified.")
    identity = {
        "provider": "google",
        "subject": subject,
        "display_name": str(user.get("name") or user.get("email") or "")[:100],
    }
    global_token = await issue_global_session(request.app.state.redis, identity)
    return {
        **identity,
        "email": user.get("email"),
        "global_token": global_token,
    }

  @app.post("/oauth/start")
  async def oauth_start(request: Request):
    form = parse_form(await request.body(), request.headers.get("content-type", ""),
                      ("provider", "state", "redirect_uri"))
    if form["provider"] != "discord":
      raise HTTPException(status_code=400, detail="Unsupported provider.")
    if not STATE_PATTERN.fullmatch(form["state"]):
      raise HTTPException(status_code=400, detail="Invalid desktop state value.")
    if not desktop_redirect_is_valid(form["redirect_uri"]):
      raise HTTPException(status_code=400, detail="Desktop redirect must be an IPv4 loopback URI.")

    broker_state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = __import__("base64").urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    state_record = json.dumps({
        "desktop_state": form["state"],
        "redirect_uri": form["redirect_uri"],
        "verifier": verifier,
        "created_at": int(time.time()),
    }, separators=(",", ":"))
    stored = await request.app.state.redis.set(
        f"{REDIS_PREFIX}state:{hashlib.sha256(broker_state.encode()).hexdigest()}",
        state_record,
        ex=STATE_TTL_SECONDS,
        nx=True,
    )
    if not stored:
      raise HTTPException(status_code=503, detail="Could not create an OAuth state record.")

    authorization_url = DISCORD_AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": config.discord_client_id,
        "response_type": "code",
        "redirect_uri": config.discord_redirect_uri,
        "scope": "identify email",
        "state": broker_state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {"authorization_url": authorization_url}

  @app.get(CALLBACK_PATH, include_in_schema=False)
  async def discord_callback(request: Request):
    query = request.query_params
    provider_state = query.get("state", "")
    if not STATE_PATTERN.fullmatch(provider_state):
      raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    if query.get("iss") != DISCORD_ISSUER:
      raise HTTPException(status_code=400, detail="Unexpected OAuth issuer.")

    state_key = f"{REDIS_PREFIX}state:{hashlib.sha256(provider_state.encode()).hexdigest()}"
    raw_state = await request.app.state.redis.getdel(state_key)
    if not raw_state:
      raise HTTPException(status_code=400, detail="OAuth state expired or was already used.")
    state_record = json.loads(raw_state)

    error = query.get("error")
    if error:
      redirect_query = urllib.parse.urlencode({
          "error": "access_denied",
          "state": state_record["desktop_state"],
          "iss": DISCORD_ISSUER,
      })
      return RedirectResponse(
          f"{state_record['redirect_uri']}?{redirect_query}",
          status_code=303,
          headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
      )

    code = query.get("code", "")
    if not code or len(code) > 4096:
      raise HTTPException(status_code=400, detail="Missing or invalid authorization code.")

    try:
      token_response = await request.app.state.http.post(
          DISCORD_TOKEN_URL,
          data={
              "grant_type": "authorization_code",
              "code": code,
              "redirect_uri": config.discord_redirect_uri,
              "code_verifier": state_record["verifier"],
          },
          auth=(config.discord_client_id, config.discord_client_secret),
          headers={"Accept": "application/json"},
      )
      token_response.raise_for_status()
      tokens = token_response.json()
      access_token = tokens.get("access_token")
      scopes = set(str(tokens.get("scope", "")).split())
      if not access_token or "identify" not in scopes:
        raise ValueError("Discord did not grant the identify scope.")
      user_response = await request.app.state.http.get(
          DISCORD_USER_URL,
          headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
      )
      user_response.raise_for_status()
      user = user_response.json()
    except (httpx.HTTPError, ValueError, KeyError) as error:
      raise HTTPException(status_code=502, detail="Discord authorization could not be verified.") from error

    subject = str(user.get("id", ""))
    if not subject.isdigit() or len(subject) > 24:
      raise HTTPException(status_code=502, detail="Discord returned an invalid user identity.")
    display_name = user.get("global_name") or user.get("username") or ""
    ticket = secrets.token_urlsafe(32)
    ticket_record = json.dumps({
        "desktop_state": state_record["desktop_state"],
        "redirect_uri": state_record["redirect_uri"],
        "subject": subject,
        "email": user.get("email") if user.get("verified") else None,
        "display_name": str(display_name)[:100],
        "username": str(user.get("username", ""))[:64],
        "issuer": DISCORD_ISSUER,
        "issued_at": int(time.time()),
    }, separators=(",", ":"))
    stored = await request.app.state.redis.set(
        f"{REDIS_PREFIX}ticket:{hashlib.sha256(ticket.encode()).hexdigest()}",
        ticket_record,
        ex=TICKET_TTL_SECONDS,
        nx=True,
    )
    if not stored:
      raise HTTPException(status_code=503, detail="Could not issue a sign-in ticket.")

    redirect_query = urllib.parse.urlencode({
        "ticket": ticket,
        "state": state_record["desktop_state"],
        "iss": DISCORD_ISSUER,
    })
    return RedirectResponse(
        f"{state_record['redirect_uri']}?{redirect_query}",
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )

  @app.post("/oauth/complete")
  async def oauth_complete(request: Request):
    form = parse_form(await request.body(), request.headers.get("content-type", ""),
                      ("provider", "state", "ticket", "redirect_uri"))
    if form["provider"] != "discord":
      raise HTTPException(status_code=400, detail="Unsupported provider.")
    if not STATE_PATTERN.fullmatch(form["state"]):
      raise HTTPException(status_code=400, detail="Invalid desktop state value.")
    if not desktop_redirect_is_valid(form["redirect_uri"]):
      raise HTTPException(status_code=400, detail="Desktop redirect must be an IPv4 loopback URI.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", form["ticket"]):
      raise HTTPException(status_code=400, detail="Invalid sign-in ticket.")

    ticket_key = f"{REDIS_PREFIX}ticket:{hashlib.sha256(form['ticket'].encode()).hexdigest()}"
    result = await request.app.state.redis.eval(
        CONSUME_TICKET_SCRIPT,
        1,
        ticket_key,
        form["state"],
        form["redirect_uri"],
    )
    if result == 0:
      raise HTTPException(status_code=410, detail="Ticket expired or already used.")
    if result == -1:
      raise HTTPException(status_code=403, detail="Ticket does not match this authorization.")
    record = json.loads(result)
    if record.get("issuer") != DISCORD_ISSUER or not record.get("subject", "").isdigit():
      raise HTTPException(status_code=403, detail="Ticket identity validation failed.")
    identity = {
        "provider": "discord",
        "subject": record["subject"],
        "email": record.get("email"),
        "display_name": record.get("display_name", ""),
        "username": record.get("username", ""),
    }
    global_token = await issue_global_session(request.app.state.redis, identity)
    return {**identity, "global_token": global_token}

  @app.post("/leaderboard/update")
  async def leaderboard_update(request: Request):
    identity = await authenticated_global_identity(request)
    form = parse_form(await request.body(), request.headers.get("content-type", ""),
                      ("display_name", "points", "correct", "wrong"))
    display_name = form["display_name"].strip()
    if not display_name or len(display_name) > 64:
      raise HTTPException(status_code=400, detail="Display name must be 1–64 characters.")
    try:
      points = int(form["points"])
      correct = int(form["correct"])
      wrong = int(form["wrong"])
    except ValueError:
      raise HTTPException(status_code=400, detail="Leaderboard totals must be integers.") from None
    if min(points, correct, wrong) < 0 or max(points, correct, wrong) > 2_000_000_000:
      raise HTTPException(status_code=400, detail="Leaderboard totals are out of range.")
    member = f"{identity['provider']}:{identity['subject']}"
    script = """
    local old_raw = redis.call('HGET', KEYS[1], ARGV[1])
    local old = old_raw and cjson.decode(old_raw) or {}
    local points = math.max(tonumber(old.points or 0), tonumber(ARGV[4]))
    local correct = math.max(tonumber(old.correct or 0), tonumber(ARGV[5]))
    local wrong = math.max(tonumber(old.wrong or 0), tonumber(ARGV[6]))
    local record = cjson.encode({
      provider = ARGV[2], display_name = ARGV[3],
      points = points, correct = correct, wrong = wrong
    })
    redis.call('HSET', KEYS[1], ARGV[1], record)
    redis.call('ZADD', KEYS[2], points, ARGV[1])
    return record
    """
    raw_record = await request.app.state.redis.eval(
        script,
        2,
        GLOBAL_LEADERBOARD_PROFILES,
        GLOBAL_LEADERBOARD_SCORES,
        member,
        identity["provider"],
        display_name,
        points,
        correct,
        wrong,
    )
    return {"success": True, "entry": json.loads(raw_record)}

  @app.get("/leaderboard")
  async def global_leaderboard(request: Request):
    members = await request.app.state.redis.zrevrange(
        GLOBAL_LEADERBOARD_SCORES, 0, 49
    )
    entries = []
    definitions = await tag_definitions()
    for member in members:
      raw = await request.app.state.redis.hget(GLOBAL_LEADERBOARD_PROFILES, member)
      if raw:
        entry = json.loads(raw)
        provider, subject = member.split(':', 1)
        await register_global_player(app.state.redis, {'provider': provider, 'subject': subject,
                                                      'display_name': entry['display_name']})
        entry.update({key: value for key, value in (await global_tags({'provider': provider, 'subject': subject}, definitions)).items()
                      if key in ('tags', 'player_id')})
        entry["rank"] = len(entries) + 1
        entries.append(entry)
    return {"entries": entries}

  @app.post("/leaderboard/revoke")
  async def revoke_global_session(request: Request):
    authorization = request.headers.get("authorization", "")
    token = authorization.partition(" ")[2]
    if not token:
      raise HTTPException(status_code=401, detail="A leaderboard bearer token is required.")
    key = GLOBAL_SESSION_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()
    removed = await request.app.state.redis.delete(key)
    return {"revoked": bool(removed)}

  return app


app = make_app()
