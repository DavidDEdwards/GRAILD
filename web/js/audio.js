// Snippet playback with the Web Audio API. Replaces pygame + FFmpeg from the
// desktop app (random_snippets.py, audio_files.py): the browser decodes the
// file itself, and we start/stop at exact times, so Random Drop needs no WAV
// conversion. Only one decoded song is kept in memory at a time.

export class SnippetPlayer {
  constructor() {
    this.context = null;
    this.gain = null;
    this.source = null;
    this.volume = 0.7;
    this.cached = { key: null, buffer: null };
    this.loading = null;
    this.onEnded = null;
  }

  // Browsers only allow sound after a click, so call this inside click handlers.
  unlock() {
    if (!this.context) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) throw new Error('This browser cannot play audio with the Web Audio API.');
      this.context = new AudioContextClass();
      this.gain = this.context.createGain();
      this.gain.gain.value = this.volume;
      this.gain.connect(this.context.destination);
    }
    if (this.context.state === 'suspended') this.context.resume().catch(() => {});
  }

  setVolume(value) {
    this.volume = Math.max(0, Math.min(1, value));
    if (this.gain) this.gain.gain.value = this.volume;
  }

  async load(track) {
    if (this.cached.key === track.key) return this.cached.buffer;
    if (this.loading && this.loading.key === track.key) return this.loading.promise;
    const promise = (async () => {
      const file = await track.getFile();
      const bytes = await file.arrayBuffer();
      try {
        // The callback form also works in older Safari. Newer browsers also
        // return a promise; silence it so a bad file is not logged twice.
        return await new Promise((resolve, reject) => {
          const pending = this.context.decodeAudioData(bytes, resolve, reject);
          if (pending && typeof pending.catch === 'function') pending.catch(() => {});
        });
      } catch {
        throw new Error('this browser cannot decode that audio format');
      }
    })();
    this.loading = { key: track.key, promise };
    try {
      const buffer = await promise;
      this.cached = { key: track.key, buffer };
      return buffer;
    } finally {
      if (this.loading && this.loading.key === track.key) this.loading = null;
    }
  }

  stop() {
    if (this.source) {
      this.source.onended = null;
      try { this.source.stop(); } catch { /* already stopped */ }
      this.source.disconnect();
      this.source = null;
    }
  }

  // Plays `seconds` of the decoded song starting at `offset`.
  // Returns { startedAt, duration } in AudioContext time for the progress bar.
  play(buffer, offset, seconds) {
    this.stop();
    const start = Math.max(0, Math.min(offset, Math.max(0, buffer.duration - 0.05)));
    const duration = Math.max(0.05, Math.min(seconds, buffer.duration - start));
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gain);
    source.onended = () => {
      if (this.source === source) this.source = null;
      if (this.onEnded) this.onEnded();
    };
    source.start(0, start, duration);
    this.source = source;
    return { startedAt: this.context.currentTime, duration };
  }

  get now() { return this.context ? this.context.currentTime : 0; }
}
