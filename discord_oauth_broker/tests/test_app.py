import hashlib
import json
import time
import urllib.parse

import httpx
import pytest
from fastapi.testclient import TestClient

from app import Settings, make_app


class MemoryRedis:
  def __init__(self):
    self.values = {}
    self.hashes = {}
    self.sorted_sets = {}

  def _live(self, key):
    record = self.values.get(key)
    if record and record[1] is not None and record[1] <= time.time():
      self.values.pop(key, None)
      return None
    return record

  async def ping(self):
    return True

  async def aclose(self):
    return None

  async def set(self, key, value, ex=None, nx=False):
    if self._live(key) and nx:
      return None
    expires = time.time() + ex if ex else None
    self.values[key] = (value, expires)
    return True

  async def get(self, key):
    record = self._live(key)
    return record[0] if record else None

  async def getdel(self, key):
    record = self._live(key)
    self.values.pop(key, None)
    return record[0] if record else None

  def expire_now(self, key):
    value, _expires = self.values[key]
    self.values[key] = (value, time.time() - 1)

  async def eval(self, script, _number_of_keys, *args):
    if "local old_raw" in script:
      profiles_key, scores_key, member, provider, display_name, points, correct, wrong = args
      previous = json.loads(self.hashes[profiles_key][member]) if member in self.hashes.get(profiles_key, {}) else {}
      entry = {
          "provider": provider,
          "display_name": display_name,
          "points": max(previous.get("points", 0), int(points)),
          "correct": max(previous.get("correct", 0), int(correct)),
          "wrong": max(previous.get("wrong", 0), int(wrong)),
      }
      encoded = json.dumps(entry)
      self.hashes.setdefault(profiles_key, {})[member] = encoded
      self.sorted_sets.setdefault(scores_key, {})[member] = entry["points"]
      return encoded
    key, desktop_state, redirect_uri = args
    record = await self.get(key)
    if record is None:
      return 0
    ticket = json.loads(record)
    if ticket["desktop_state"] != desktop_state or ticket["redirect_uri"] != redirect_uri:
      return -1
    self.values.pop(key, None)
    return record

  async def hget(self, key, field):
    return self.hashes.get(key, {}).get(field)

  async def hset(self, key, field, value):
    self.hashes.setdefault(key, {})[field] = value
    return 1

  async def hgetall(self, key):
    return dict(self.hashes.get(key, {}))

  async def hsetnx(self, key, field, value):
    records = self.hashes.setdefault(key, {})
    if field in records:
      return 0
    records[field] = value
    return 1

  async def zrevrange(self, key, start, stop):
    members = sorted(
        self.sorted_sets.get(key, {}),
        key=lambda member: (-self.sorted_sets[key][member], member),
    )
    return members[start:stop + 1]

  async def delete(self, key):
    return int(self.values.pop(key, None) is not None)


def make_test_client():
  redis = MemoryRedis()

  async def discord_mock(request):
    if request.url.path.endswith("/oauth2/token"):
      form = urllib.parse.parse_qs(request.content.decode())
      assert form["grant_type"] == ["authorization_code"]
      assert form["code_verifier"]
      assert form["redirect_uri"] == ["https://broker.example.test/oauth/callback"]
      assert request.headers.get("authorization", "").startswith("Basic ")
      return httpx.Response(200, json={
          "access_token": "test-access-token",
          "scope": "identify email",
      })
    if request.url.path.endswith("/users/@me"):
      assert request.headers["authorization"] == "Bearer test-access-token"
      return httpx.Response(200, json={
          "id": "123456789012345678",
          "username": "test_user",
          "global_name": "Test User",
          "email": "test@example.test",
          "verified": True,
      })
    if request.url.path.endswith("/v1/userinfo"):
      assert request.headers["authorization"] == "Bearer google-access-token"
      return httpx.Response(200, json={
          "sub": "google-subject-987",
          "name": "Google User",
          "email": "google@example.test",
          "email_verified": True,
      })
    return httpx.Response(404)

  http_client = httpx.AsyncClient(transport=httpx.MockTransport(discord_mock))
  settings = Settings(
      discord_client_id="test-client-id",
      discord_client_secret="test-client-secret",
      discord_redirect_uri="https://broker.example.test/oauth/callback",
      redis_url="redis://unused",
  )
  app = make_app(settings, redis_client=redis, http_client=http_client)
  app.state.redis = redis
  app.state.http = http_client
  return TestClient(app), redis


def test_desktop_redirect_accepts_only_exact_loopback_root():
  from app import desktop_redirect_is_valid

  assert desktop_redirect_is_valid("http://127.0.0.1:49123/")
  assert not desktop_redirect_is_valid("https://127.0.0.1:49123/")
  assert not desktop_redirect_is_valid("http://localhost:49123/")
  assert not desktop_redirect_is_valid("http://127.0.0.1:49123.evil.example/")
  assert not desktop_redirect_is_valid("http://127.0.0.1:49123/other")
  assert not desktop_redirect_is_valid("http://127.0.0.1:49123/?next=https://evil.example")


def test_discord_flow_contract_pkce_and_single_use_ticket():
  client, _redis = make_test_client()
  desktop_state = "d" * 43
  desktop_redirect = "http://127.0.0.1:49123/"
  start = client.post("/oauth/start", data={
      "provider": "discord",
      "state": desktop_state,
      "redirect_uri": desktop_redirect,
  })
  assert start.status_code == 200
  authorization = urllib.parse.urlsplit(start.json()["authorization_url"])
  assert authorization.hostname == "discord.com"
  query = urllib.parse.parse_qs(authorization.query)
  assert query["scope"] == ["identify email"]
  assert query["code_challenge_method"] == ["S256"]
  assert query["redirect_uri"] == ["https://broker.example.test/oauth/callback"]

  callback = client.get("/oauth/callback", params={
      "code": "one-time-code",
      "state": query["state"][0],
      "iss": "https://discord.com",
  }, follow_redirects=False)
  assert callback.status_code == 303
  returned = urllib.parse.urlsplit(callback.headers["location"])
  assert returned.netloc == "127.0.0.1:49123"
  callback_values = urllib.parse.parse_qs(returned.query)
  assert callback_values["state"] == [desktop_state]
  assert callback_values["iss"] == ["https://discord.com"]
  ticket = callback_values["ticket"][0]

  complete = client.post("/oauth/complete", data={
      "provider": "discord",
      "state": desktop_state,
      "ticket": ticket,
      "redirect_uri": desktop_redirect,
  })
  assert complete.status_code == 200
  assert complete.json() == {
      "provider": "discord",
      "subject": "123456789012345678",
      "email": "test@example.test",
      "display_name": "Test User",
      "username": "test_user",
      "global_token": complete.json()["global_token"],
  }
  global_token = complete.json()["global_token"]
  replay = client.post("/oauth/complete", data={
      "provider": "discord",
      "state": desktop_state,
      "ticket": ticket,
      "redirect_uri": desktop_redirect,
  })
  assert replay.status_code == 410
  assert global_token


def test_mismatched_ticket_binding_does_not_consume_ticket():
  client, _redis = make_test_client()
  state = "s" * 43
  redirect_uri = "http://127.0.0.1:49000/"
  start = client.post("/oauth/start", data={
      "provider": "discord", "state": state, "redirect_uri": redirect_uri,
  })
  broker_state = urllib.parse.parse_qs(
      urllib.parse.urlsplit(start.json()["authorization_url"]).query
  )["state"][0]
  callback = client.get("/oauth/callback", params={
      "code": "code", "state": broker_state, "iss": "https://discord.com",
  }, follow_redirects=False)
  ticket = urllib.parse.parse_qs(urllib.parse.urlsplit(callback.headers["location"]).query)["ticket"][0]
  mismatch = client.post("/oauth/complete", data={
      "provider": "discord", "state": "x" * 43, "ticket": ticket,
      "redirect_uri": redirect_uri,
  })
  assert mismatch.status_code == 403
  redirect_mismatch = client.post("/oauth/complete", data={
      "provider": "discord", "state": state, "ticket": ticket,
      "redirect_uri": "http://127.0.0.1:49001/",
  })
  assert redirect_mismatch.status_code == 403
  valid = client.post("/oauth/complete", data={
      "provider": "discord", "state": state, "ticket": ticket,
      "redirect_uri": redirect_uri,
  })
  assert valid.status_code == 200


def test_expired_ticket_cannot_be_redeemed():
  client, redis = make_test_client()
  state = "e" * 43
  redirect_uri = "http://127.0.0.1:49200/"
  start = client.post("/oauth/start", data={
      "provider": "discord", "state": state, "redirect_uri": redirect_uri,
  })
  broker_state = urllib.parse.parse_qs(
      urllib.parse.urlsplit(start.json()["authorization_url"]).query
  )["state"][0]
  callback = client.get("/oauth/callback", params={
      "code": "code", "state": broker_state, "iss": "https://discord.com",
  }, follow_redirects=False)
  ticket = urllib.parse.parse_qs(urllib.parse.urlsplit(callback.headers["location"]).query)["ticket"][0]
  key = "graild-discord-oauth:v1:ticket:" + hashlib.sha256(ticket.encode()).hexdigest()
  redis.expire_now(key)
  complete = client.post("/oauth/complete", data={
      "provider": "discord", "state": state, "ticket": ticket,
      "redirect_uri": redirect_uri,
  })
  assert complete.status_code == 410


def test_expired_oauth_state_cannot_complete_callback():
  client, redis = make_test_client()
  start = client.post("/oauth/start", data={
      "provider": "discord",
      "state": "t" * 43,
      "redirect_uri": "http://127.0.0.1:49201/",
  })
  broker_state = urllib.parse.parse_qs(
      urllib.parse.urlsplit(start.json()["authorization_url"]).query
  )["state"][0]
  state_key = "graild-discord-oauth:v1:state:" + hashlib.sha256(broker_state.encode()).hexdigest()
  redis.expire_now(state_key)
  callback = client.get("/oauth/callback", params={
      "code": "code", "state": broker_state, "iss": "https://discord.com",
  })
  assert callback.status_code == 400


def test_google_verification_issues_a_global_session():
  client, _redis = make_test_client()
  response = client.post("/oauth/google/verify", data={"access_token": "google-access-token"})
  assert response.status_code == 200
  assert response.json()["provider"] == "google"
  assert response.json()["subject"] == "google-subject-987"
  assert response.json()["global_token"]


def test_global_leaderboard_requires_token_and_ranks_verified_users():
  client, _redis = make_test_client()
  unauthorized = client.post("/leaderboard/update", data={
    "display_name": "Player", "points": 100, "correct": 3, "wrong": 1,
  })
  assert unauthorized.status_code == 401

  verified = client.post("/oauth/google/verify", data={"access_token": "google-access-token"})
  token = verified.json()["global_token"]
  headers = {"Authorization": f"Bearer {token}"}
  update = client.post("/leaderboard/update", headers=headers, data={
    "display_name": "Player", "points": 100, "correct": 3, "wrong": 1,
  })
  assert update.status_code == 200
  stale_update = client.post("/leaderboard/update", headers=headers, data={
    "display_name": "Player", "points": 50, "correct": 1, "wrong": 1,
  })
  assert stale_update.json()["entry"]["points"] == 100
  board = client.get("/leaderboard")
  assert board.json()["entries"][0]["display_name"] == "Player"
  assert board.json()["entries"][0]["provider"] == "google"
  assert client.post("/leaderboard/revoke", headers=headers).json() == {"revoked": True}
  expired_session = client.post("/leaderboard/update", headers=headers, data={
    "display_name": "Player", "points": 110, "correct": 4, "wrong": 1,
  })
  assert expired_session.status_code == 401


def test_start_rejects_external_redirect_and_invalid_state():
  client, _redis = make_test_client()
  external_redirect = client.post("/oauth/start", data={
      "provider": "discord", "state": "z" * 43,
      "redirect_uri": "https://attacker.example/callback",
  })
  assert external_redirect.status_code == 400
  short_state = client.post("/oauth/start", data={
      "provider": "discord", "state": "short",
      "redirect_uri": "http://127.0.0.1:49123/",
  })
  assert short_state.status_code == 400


def test_callback_rejects_wrong_issuer_and_replayed_state():
  client, _redis = make_test_client()
  start = client.post("/oauth/start", data={
      "provider": "discord", "state": "q" * 43,
      "redirect_uri": "http://127.0.0.1:49123/",
  })
  broker_state = urllib.parse.parse_qs(
      urllib.parse.urlsplit(start.json()["authorization_url"]).query
  )["state"][0]
  wrong_issuer = client.get("/oauth/callback", params={
      "code": "code", "state": broker_state, "iss": "https://attacker.example",
  })
  assert wrong_issuer.status_code == 400
  valid = client.get("/oauth/callback", params={
      "code": "code", "state": broker_state, "iss": "https://discord.com",
  }, follow_redirects=False)
  assert valid.status_code == 303
  replay = client.get("/oauth/callback", params={
      "code": "code", "state": broker_state, "iss": "https://discord.com",
  })
  assert replay.status_code == 400
