"""Read-only live checks. No Discord login, score writes or private profile reads."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import aiohttp
from graild_api import GraildAPI, DEFAULT_BACKEND, ProfileUnavailable
from github_releases import GitHubReleases
from http_client import JSONClient, APIError


async def main():
    report = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'discord_connection_tested': False, 'profile_integration': 'unavailable: no authorised backend endpoint',
              'read_only': True}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20, connect=5),
                                    headers={'User-Agent':'GRAILD-Discord-Bot/0.1-live-check'}) as session:
        api = GraildAPI(JSONClient(session), os.environ.get('GRAILD_BACKEND_URL', DEFAULT_BACKEND))
        releases = GitHubReleases(JSONClient(session))
        try:
            entries = await api.leaderboard()
            report['leaderboard'] = {'tested': True, 'success': True, 'returned_public_entries': len(entries)}
        except APIError as error:
            report['leaderboard'] = {'tested': True, 'success': False, 'error': str(error)}
        try:
            latest = await releases.latest()
            downloads = await releases.downloads()
            report['github'] = {'tested': True, 'success': True, 'latest_beta': latest['tag_name'],
                                'published_platforms': {key: value['version'] for key,value in downloads.items()}}
        except APIError as error:
            report['github'] = {'tested': True, 'success': False, 'error': str(error)}
    path = Path(__file__).with_name('LIVE_CHECK_RESULTS.json')
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': asyncio.run(main())
