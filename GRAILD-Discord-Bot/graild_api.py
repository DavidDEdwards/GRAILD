"""Read-only adapter for the inspected GRAIL'D public leaderboard interface."""
from http_client import APIError, https_origin

DEFAULT_BACKEND = 'https://graild-discord-broker.onrender.com'


class ProfileUnavailable(APIError):
    pass


class GraildAPI:
    def __init__(self, client, base_url=DEFAULT_BACKEND):
        self.client = client
        self.base_url = https_origin(base_url)

    async def leaderboard(self):
        response = await self.client.get(self.base_url + '/leaderboard')
        if not isinstance(response, dict) or not isinstance(response.get('entries'), list):
            raise APIError('The leaderboard returned an unexpected response.')
        result = []
        for entry in response['entries'][:10]:
            if not isinstance(entry, dict):
                raise APIError('The leaderboard returned an invalid player entry.')
            name = entry.get('display_name')
            rank, points = entry.get('rank'), entry.get('points')
            correct, wrong = entry.get('correct'), entry.get('wrong')
            if (not isinstance(name, str) or not name.strip() or
                    any(type(n) is not int or n < 0 for n in (rank, points, correct, wrong)) or rank < 1):
                raise APIError('The leaderboard returned incomplete player totals.')
            # Allowlist public fields; never propagate tokens, emails or identities.
            result.append(dict(display_name=name[:64], rank=rank, points=points,
                               correct=correct, wrong=wrong))
        return result

    async def profile(self, discord_id):
        if type(discord_id) is not int or discord_id <= 0:
            raise APIError('A valid Discord account ID is required.')
        # The inspected broker has no authorised read-by-Discord-ID endpoint.
        # Public leaderboard entries omit IDs; display-name matching is unsafe.
        raise ProfileUnavailable(
            'Linked-profile lookup is not available yet. The current GRAIL\'D backend '
            'does not expose an authorised Discord-ID profile API. View your profile '
            'in the desktop app for now. No private account data was accessed.')
