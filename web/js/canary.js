// Optional song details from Canary (canary.best), fetched straight from the
// browser. Canary's API allows any website to call it (CORS "*").
// Only the song title is sent; never audio. Answers are cached in
// localStorage for a day, and a 429 "slow down" reply pauses all requests for
// as long as Canary's Retry-After header asks.

const BASE_URL = 'https://canary.best/api/v1';
const CACHE_PREFIX = 'graild-canary-v1:';
const COOLDOWN_KEY = 'graild-canary-cooldown';
const TTL_MS = 24 * 60 * 60 * 1000;
const MIN_GAP_MS = 800;
let lastRequest = 0;

function storageGet(key) {
  try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage full or blocked */ }
}

// Same clean-up as canary_integration.py: drop "Juice WRLD - ", track numbers
// and version words so "03 Rental (Session).mp3" searches for "Rental".
export function searchTitle(title) {
  return String(title).replace(/_/g, ' ')
    .replace(/^juice\s*wrld\s*[-:]+\s*/i, '')
    .replace(/^\d{1,3}[. _-]+/, '')
    .replace(/\s*[-([]?\s*(?:session(?:s| edit)?|alternate(?: version)?|alt(?: version)?|demo|original(?: version)?|normal(?: version)?|studio(?: version)?|album version|v\d+|version \d+)[)\]]?\s*$/i, '')
    .replace(/^[\s\-_()[\]]+|[\s\-_()[\]]+$/g, '');
}

export function matchKey(value) {
  return (String(value).normalize('NFKC').toLowerCase().replace(/_/g, ' ')
    .replace(/^juice\s*wrld\s*[-:]+\s*/, '').replace(/^\d{1,3}[. _-]+/, '')
    .match(/[\p{L}\p{N}]+/gu) || []).join(' ');
}

export function cooldownSeconds() {
  const until = Number(storageGet(COOLDOWN_KEY)) || 0;
  return Math.max(0, Math.ceil((until - Date.now()) / 1000));
}

async function getJson(path, params) {
  const url = new URL(BASE_URL + path);
  Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
  const cacheKey = CACHE_PREFIX + url.pathname + url.search;
  const cached = storageGet(cacheKey);
  if (cached && Date.now() - cached.saved < TTL_MS) return cached.payload;
  const wait = cooldownSeconds();
  if (wait) {
    if (cached) return cached.payload;
    throw new Error(`Canary asked us to slow down. Song details will be back in about ${wait}s.`);
  }
  const gap = MIN_GAP_MS - (Date.now() - lastRequest);
  if (gap > 0) await new Promise(resolve => setTimeout(resolve, gap));
  lastRequest = Date.now();
  let response;
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' } });
  } catch {
    if (cached) return cached.payload;
    throw new Error('Could not reach Canary. Playing still works offline.');
  }
  if (response.status === 429) {
    const retry = Math.max(1, Math.min(600, parseInt(response.headers.get('Retry-After') || '60', 10) || 60));
    storageSet(COOLDOWN_KEY, Date.now() + retry * 1000);
    if (cached) return cached.payload;
    throw new Error(`Canary asked us to slow down. Song details will be back in about ${retry}s.`);
  }
  if (!response.ok) {
    if (cached) return cached.payload;
    throw new Error('Canary is unavailable right now.');
  }
  const payload = await response.json();
  storageSet(cacheKey, { saved: Date.now(), payload });
  return payload;
}

// Returns the Canary song whose title exactly matches, or null. Like the
// desktop app, similar titles are never treated as the same recording.
export async function findSong(title) {
  const query = searchTitle(title);
  if (!query) return null;
  const data = await getJson('/songs', { q: query, limit: 10 });
  const songs = Array.isArray(data && data.songs) ? data.songs : [];
  const wanted = matchKey(query);
  const exact = songs.filter(song => song && matchKey(song.title || '') === wanted);
  if (!exact.length) return null;
  const song = exact.find(item => item.category === 'Released') || exact[0];
  const safeUrl = value => (typeof value === 'string' && value.startsWith('https://canary.best/') ? value : '');
  return {
    title: String(song.title || ''), era: String(song.era || ''), category: String(song.category || ''),
    duration: String(song.duration_str || ''), pageUrl: safeUrl(song.page_url), coverUrl: safeUrl(song.cover_url),
  };
}

// Canary Shuffle: a random song from Canary's whole catalogue, the same way
// canary_client.py does it (ask how many songs exist, then fetch one random page
// of size 1). The player listens on Canary's own website.
export async function randomSong(random = Math.random) {
  const first = await getJson('/songs', { page: 0, limit: 1 });
  const total = Number(first && first.total) || 0;
  if (!total) throw new Error('Canary has no songs to shuffle right now.');
  const page = Math.floor(random() * total);
  const data = page === 0 ? first : await getJson('/songs', { page, limit: 1 });
  const song = data && Array.isArray(data.songs) ? data.songs[0] : null;
  if (!song || typeof song.page_url !== 'string' || !song.page_url.startsWith('https://canary.best/')) {
    throw new Error("Canary's catalogue changed. Try again.");
  }
  return { title: String(song.title || 'Unknown'), era: String(song.era || ''), category: String(song.category || ''), pageUrl: song.page_url };
}
