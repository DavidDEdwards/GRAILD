// Reading the player's own music folder in the browser.
//
// Files never leave the device: we only ask the browser for File objects and
// read them locally. Two ways to pick a folder:
//  * File System Access API (Chrome, Edge, Opera): showDirectoryPicker(). The
//    folder "handle" can be kept in IndexedDB, so next visit one click reopens it.
//  * <input type="file" webkitdirectory> (Firefox, Safari, everything else):
//    works everywhere, but the browser forgets the folder when the page closes.
import { isAudioFile, trackTitle } from './game-core.js';

const MAX_FILES = 20000;
const DB_NAME = 'graild-web';
const STORE = 'handles';
const HANDLE_KEY = 'music-folder';

export const canRememberFolder = typeof window !== 'undefined' && 'showDirectoryPicker' in window;

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore(mode, action) {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE, mode);
      const request = action(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}

async function saveHandle(handle) {
  try { await withStore('readwrite', store => store.put(handle, HANDLE_KEY)); } catch { /* remembering is optional */ }
}

export async function forgetFolder() {
  try { await withStore('readwrite', store => store.delete(HANDLE_KEY)); } catch { /* nothing saved */ }
}

// Returns { name, needsClick } for a folder remembered from an earlier visit.
export async function rememberedFolder() {
  if (!canRememberFolder) return null;
  let handle;
  try { handle = await withStore('readonly', store => store.get(HANDLE_KEY)); } catch { return null; }
  if (!handle) return null;
  let permission = 'prompt';
  try { permission = await handle.queryPermission({ mode: 'read' }); } catch { /* treat as prompt */ }
  return { handle, name: handle.name, needsClick: permission !== 'granted' };
}

function sortTracks(tracks) {
  return tracks.sort((a, b) => a.key.localeCompare(b.key, undefined, { sensitivity: 'base', numeric: true }));
}

function makeTrack(path, name, getFile) {
  return { key: path, name, title: trackTitle(name), getFile };
}

async function scanHandle(directory) {
  const tracks = [];
  let truncated = false;
  async function walk(folder, prefix) {
    for await (const entry of folder.values()) {
      if (tracks.length >= MAX_FILES) { truncated = true; return; }
      if (entry.kind === 'directory') {
        if (!entry.name.startsWith('.')) await walk(entry, `${prefix}${entry.name}/`);
      } else if (isAudioFile(entry.name)) {
        tracks.push(makeTrack(prefix + entry.name, entry.name, () => entry.getFile()));
      }
    }
  }
  await walk(directory, '');
  return { name: directory.name, tracks: sortTracks(tracks), truncated, remembered: true };
}

// Re-open a remembered folder. Must be called from a click if needsClick.
export async function openRemembered(handle) {
  let permission = await handle.queryPermission({ mode: 'read' });
  if (permission !== 'granted') permission = await handle.requestPermission({ mode: 'read' });
  if (permission !== 'granted') throw new Error('The browser did not allow access to that folder.');
  return scanHandle(handle);
}

// Shows the modern folder picker. Returns null if the player cancelled, or
// throws 'unsupported' so the caller can fall back to the <input> picker.
export async function pickWithDirectoryPicker() {
  if (!canRememberFolder) throw new Error('unsupported');
  let handle;
  try {
    handle = await window.showDirectoryPicker({ id: 'graild-music', mode: 'read', startIn: 'music' });
  } catch (error) {
    if (error && error.name === 'AbortError') return null;
    throw new Error('unsupported'); // e.g. blocked inside an iframe
  }
  await saveHandle(handle);
  return scanHandle(handle);
}

// Turns the FileList from <input webkitdirectory> into tracks.
export function tracksFromFileList(fileList) {
  const files = Array.from(fileList || []);
  const tracks = [];
  let truncated = false;
  let folderName = '';
  for (const file of files) {
    const path = file.webkitRelativePath || file.name;
    const parts = path.split('/');
    if (!folderName && parts.length > 1) folderName = parts[0];
    // Drop the top folder's own name so keys match the File System Access path.
    const inner = parts.length > 1 ? parts.slice(1).join('/') : path;
    if (parts.some(part => part.startsWith('.')) || !isAudioFile(file.name, file.type)) continue;
    if (tracks.length >= MAX_FILES) { truncated = true; break; }
    tracks.push(makeTrack(inner, file.name, async () => file));
  }
  return { name: folderName || 'Selected folder', tracks: sortTracks(tracks), truncated, remembered: false };
}
