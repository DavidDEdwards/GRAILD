import asyncio
import json
import runpy
from pathlib import Path

from app import issue_global_session, global_player_id
from tag_rules import ACHIEVEMENT_IDS
from tests.test_app import make_test_client

OWNER = '1119220334873288777'


def session(redis, subject, provider='discord'):
    identity = {'provider': provider, 'subject': subject, 'display_name': 'Player ' + subject[-3:]}
    token = asyncio.run(issue_global_session(redis, identity))
    return {'Authorization': 'Bearer ' + token}, global_player_id(identity)


def test_catalog_matches_desktop():
    desktop_path = Path(__file__).resolve().parents[2] / 'achievements.py'
    if desktop_path.is_file():
        desktop = runpy.run_path(str(desktop_path))
        assert ACHIEVEMENT_IDS == {item['id'] for item in desktop['ACHIEVEMENTS']}
    assert len(ACHIEVEMENT_IDS) == 50


def test_owner_assigns_and_second_installation_recognizes_same_identity():
    client, redis = make_test_client()
    owner, _ = session(redis, OWNER)
    tester, player_id = session(redis, '123456789012345678')
    assert client.post('/account/tags/assign', headers=owner, data={
        'player_id': player_id, 'tag_id': 'beta_tester', 'assigned': 'true'}).status_code == 200
    before = client.get('/account/tags', headers=tester).json()
    second_installation, second_id = session(redis, '123456789012345678')
    after = client.get('/account/tags', headers=second_installation).json()
    assert player_id == second_id == after['player_id']
    assert before['tags'] == after['tags']
    assert after['tags'][0]['id'] == 'beta_tester'
    players = client.get('/account/tag-players', headers=owner).json()['accounts']
    assert next(p for p in players if p['player_id'] == player_id)['beta_tester']
    assert '123456789012345678' not in json.dumps(players)
    client.post('/account/tags/assign', headers=owner, data={
        'player_id': player_id, 'tag_id': 'beta_tester', 'assigned': 'false'})
    assert client.get('/account/tags', headers=second_installation).json()['tags'] == []


def test_local_flags_and_other_providers_do_not_grant_ownership():
    client, redis = make_test_client()
    tester, player_id = session(redis, '123456789012345678')
    google, _ = session(redis, OWNER, 'google')
    for headers in ({}, tester, google):
        assert client.post('/account/tags/assign', headers=headers, data={
            'player_id': player_id, 'tag_id': 'beta_tester', 'assigned': 'true', 'is_creator': '1'}).status_code in (401, 403)
        assert client.get('/account/tag-players', headers=headers).status_code in (401, 403)
    assert client.get('/account/tags', headers=google).json()['can_manage_tags'] is False
    owner, _ = session(redis, OWNER)
    assert client.get('/account/tags', headers=owner).json()['tags'][0]['id'] == 'owner'


def test_top_earner_requires_all_real_ids_and_is_permanent():
    client, redis = make_test_client()
    player, _ = session(redis, '123456789012345678')
    ids = sorted(ACHIEVEMENT_IDS)
    assert client.post('/account/tags/sync', headers=player, data={'achievement_ids': json.dumps(ids[:-1])}).json()['tags'] == []
    for invalid in (ids[:-1] + ['invented'], ids[:-1] + [ids[0]], 'all', [None]):
        assert client.post('/account/tags/sync', headers=player, data={'achievement_ids': json.dumps(invalid)}).status_code == 400
    earned = client.post('/account/tags/sync', headers=player, data={'achievement_ids': json.dumps(ids)}).json()
    assert earned['tags'][0]['id'] == 'top_earner'
    assert client.post('/account/tags/sync', headers=player, data={'achievement_ids': '[]'}).json()['tags'] == earned['tags']
    other, _ = session(redis, '987654321012345678')
    assert client.get('/account/tags', headers=other).json()['tags'] == []


def test_owner_cannot_assign_earned_owner_or_unknown_tags():
    client, redis = make_test_client()
    owner, _ = session(redis, OWNER)
    _, player_id = session(redis, '123456789012345678')
    for tag in ('top_earner', 'owner', 'unknown'):
        assert client.post('/account/tags/assign', headers=owner, data={
            'player_id': player_id, 'tag_id': tag, 'assigned': 'true'}).status_code == 400
    assert client.post('/account/tags/assign', headers=owner, data={
        'player_id': 'a' * 64, 'tag_id': 'beta_tester', 'assigned': 'true'}).status_code == 404


def test_leaderboard_uses_server_tags():
    client, redis = make_test_client()
    owner, _ = session(redis, OWNER)
    tester, player_id = session(redis, '123456789012345678')
    client.post('/leaderboard/update', headers=tester, data={
        'display_name': 'Tester', 'points': 100, 'correct': 1, 'wrong': 0, 'tags': '["owner"]'})
    client.post('/account/tags/assign', headers=owner, data={
        'player_id': player_id, 'tag_id': 'beta_tester', 'assigned': 'true'})
    entry = client.get('/leaderboard').json()['entries'][0]
    assert entry['player_id'] == player_id
    assert [tag['id'] for tag in entry['tags']] == ['beta_tester']


def test_assign_by_discord_before_first_sign_in():
    client, redis = make_test_client()
    owner, _ = session(redis, OWNER)
    subject = '456789012345678901'
    result = client.post('/account/tags/discord', headers=owner, data={
        'discord_id': subject, 'tag_id': 'beta_tester', 'assigned': 'true'})
    assert result.status_code == 200
    player, _ = session(redis, subject)
    assert client.get('/account/tags', headers=player).json()['tags'][0]['id'] == 'beta_tester'
    assert client.post('/account/tags/discord', headers=player, data={
        'discord_id': subject, 'tag_id': 'beta_tester', 'assigned': 'false'}).status_code == 403
    client.post('/account/tags/discord', headers=owner, data={
        'discord_id': subject, 'tag_id': 'beta_tester', 'assigned': 'false'})
    assert client.get('/account/tags', headers=player).json()['tags'] == []


def test_direct_discord_assignment_validates_id_and_cannot_grant_earned_tags():
    client, redis = make_test_client()
    owner, _ = session(redis, OWNER)
    for discord_id, tag in [('username', 'beta_tester'), ('123', 'beta_tester'), ('456789012345678901', 'owner'), ('456789012345678901', 'top_earner')]:
        assert client.post('/account/tags/discord', headers=owner, data={
            'discord_id': discord_id, 'tag_id': tag, 'assigned': 'true'}).status_code == 400


def test_owner_creates_custom_tag_assigns_globally_and_removes_it():
    client, redis = make_test_client()
    owner, _ = session(redis, OWNER)
    player, player_id = session(redis, '456789012345678901')
    response = client.post('/account/tags/create', headers=owner, data={
        'name': 'Contributor', 'description': 'Helped improve the game.'})
    assert response.status_code == 200
    tag = response.json()['tag']
    assert tag['kind'] == 'assigned' and tag['id'].startswith('custom_')
    assert tag in client.get('/account/tags/catalog', headers=owner).json()['entries']
    assert client.post('/account/tags/create', headers=owner, data={
        'name': 'CONTRIBUTOR', 'description': 'Duplicate'}).status_code == 409
    assert client.post('/account/tags/discord', headers=owner, data={
        'discord_id': '456789012345678901', 'tag_id': tag['id'], 'assigned': 'true'}).status_code == 200
    second_device, _ = session(redis, '456789012345678901')
    assert client.get('/account/tags', headers=second_device).json()['tags'][0]['description'] == tag['description']
    client.post('/leaderboard/update', headers=player, data={'display_name':'Contributor','points':10,'correct':1,'wrong':0})
    assert client.get('/leaderboard').json()['entries'][0]['tags'][0]['name'] == 'Contributor'
    client.post('/account/tags/assign', headers=owner, data={
        'player_id': player_id, 'tag_id': tag['id'], 'assigned': 'false'})
    assert client.get('/account/tags', headers=second_device).json()['tags'] == []


def test_custom_tag_creation_is_owner_only_and_protects_reserved_tags():
    client, redis = make_test_client()
    owner, _ = session(redis, OWNER)
    player, _ = session(redis, '456789012345678901')
    for headers in ({}, player):
        assert client.post('/account/tags/create', headers=headers, data={
            'name':'VIP','description':'Special member'}).status_code in (401,403)
        assert client.get('/account/tags/catalog', headers=headers).status_code in (401,403)
    for name, description in [('Owner','Fake'),('Top earner','Fake'),('Beta Tester','Fake'),('x'*33,'Too long'),('VIP','x'*241),('VIP','\x01')]:
        assert client.post('/account/tags/create', headers=owner, data={
            'name':name,'description':description}).status_code == 400
