"""Bounded asynchronous JSON GET requests with short, in-memory TTL caching."""
import asyncio
import json
import time
from urllib.parse import urlsplit

import aiohttp


class APIError(Exception):
    """A safe error message suitable for displaying in Discord."""


def https_origin(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.port not in (None, 443) or
                parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError
    except ValueError:
        raise ValueError('Backend URL must be an HTTPS origin without credentials or a path.') from None
    return value.rstrip('/')


class JSONClient:
    def __init__(self, session, ttl=60, max_bytes=2_000_000):
        self.session, self.ttl, self.max_bytes = session, ttl, max_bytes
        self.cache = {}
        self.lock = asyncio.Lock()

    async def get(self, url):
        async with self.lock:
            saved = self.cache.get(url)
            if saved and saved[0] > time.monotonic():
                return saved[1]
            try:
                async with self.session.get(url, allow_redirects=False) as response:
                    if response.status in (403, 429):
                        raise APIError('The service is rate limiting or denying requests. Try again later.')
                    if response.status == 404:
                        raise APIError('The requested service resource is not available.')
                    if response.status != 200:
                        raise APIError('The service is temporarily unavailable. Try again shortly.')
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data) > self.max_bytes:
                            raise APIError('The service response exceeded its allowed size.')
                    value = json.loads(data)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                raise APIError('The service could not be reached or timed out. Try again shortly.') from None
            except (ValueError, UnicodeError):
                raise APIError('The service returned an invalid JSON response.') from None
            # No stale values served as if they were current after a failed refresh.
            if len(self.cache) >= 64:
                self.cache.clear()
            self.cache[url] = (time.monotonic() + self.ttl, value)
            return value
