"""Published beta releases and strictly recognised app assets from GitHub."""
from datetime import datetime
import re
from urllib.parse import quote

from http_client import APIError

REPOSITORY = 'DavidDEdwards/GRAILD-Releases'
RELEASES_URL = 'https://github.com/' + REPOSITORY + '/releases'
MAC = re.compile(r'^GRAILD-(?:[0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.+-]*-)?macOS-(arm64|x86_64)(?:-notarized)?\.zip$', re.I)


def platform_for(name):
    if name.casefold() in ('graild.exe', 'juiceguessermain.exe'):
        return 'Windows'
    match = MAC.fullmatch(name)
    if match:
        return 'Apple Silicon Mac' if match[1].lower() == 'arm64' else 'Intel Mac'
    return None


def release_date(release):
    try:
        date = datetime.fromisoformat(release['published_at'].replace('Z', '+00:00'))
        if date.tzinfo is None: raise ValueError
        return date
    except (KeyError, TypeError, AttributeError, ValueError):
        raise APIError('GitHub returned an invalid publication date.') from None


class GitHubReleases:
    def __init__(self, client):
        self.client = client

    async def beta_releases(self):
        releases = []
        # /latest excludes prereleases: use the paginated public releases list.
        for page in range(1, 6):
            data = await self.client.get('https://api.github.com/repos/' + REPOSITORY +
                                         '/releases?per_page=100&page=' + str(page))
            if not isinstance(data, list):
                raise APIError('GitHub returned an unexpected releases response.')
            for release in data:
                if (isinstance(release, dict) and release.get('draft') is False and
                        release.get('prerelease') is True and release.get('published_at')):
                    if not isinstance(release.get('tag_name'), str):
                        raise APIError('GitHub returned an invalid release tag.')
                    releases.append(release)
            if len(data) < 100:
                break
        if not releases:
            raise APIError('No published beta releases were found. Git tags and drafts are not downloadable releases.')
        # Latest means publication time, not GitHub's stable-only Latest badge.
        return sorted(releases, key=release_date, reverse=True)

    @staticmethod
    def page_url(release):
        return RELEASES_URL + '/tag/' + quote(release['tag_name'], safe='')

    async def latest(self):
        return (await self.beta_releases())[0]

    async def downloads(self):
        platforms = {}
        for release in await self.beta_releases():
            assets = release.get('assets', [])
            if not isinstance(assets, list):
                raise APIError('GitHub returned an invalid asset list.')
            for asset in assets:
                if not isinstance(asset, dict) or not isinstance(asset.get('name'), str):
                    continue
                name = asset['name']
                platform = platform_for(name)
                if not platform or platform in platforms or asset.get('state') != 'uploaded' or type(asset.get('size')) is not int or asset['size'] <= 0:
                    continue
                url = asset.get('browser_download_url', '')
                # Only use a URL actually returned for this asset and repository.
                expected = 'https://github.com/' + REPOSITORY + '/releases/download/' + quote(release['tag_name'], safe='') + '/' + quote(name, safe='')
                if url != expected:
                    continue
                platforms[platform] = dict(url=url, version=release['tag_name'], name=name)
        return platforms
