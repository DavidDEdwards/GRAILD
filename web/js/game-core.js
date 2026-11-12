// Pure game rules for the browser version of GRAIL'D.
// Ported from web_app.py (rounds, scoring, title matching), audio_files.py
// (which files count as audio) and achievements.py (the trophy catalog).
// Nothing here touches the page, audio or storage, so it can be tested in Node.

export const DIFFICULTIES = {
  Easy: [1, 2, 4, 7, 11, 16],
  Medium: [1, 3, 6, 10],
  Hard: [1, 3, 6],
};
export const GAME_MODES = {
  classic: { title: 'Classic Snippets', description: 'Guess the song from its intro.' },
  random: { title: 'Random Drop', description: 'Guess the song from a random moment in it.' },
};
export const ANSWER_SECONDS = 10;

export const AUDIO_EXTENSIONS = new Set([
  '.mp3', '.wav', '.wave', '.ogg', '.oga', '.opus', '.flac', '.m4a',
  '.aac', '.wma', '.aif', '.aiff', '.aifc', '.alac', '.ape', '.wv',
  '.amr', '.awb', '.au', '.snd', '.caf', '.mka', '.m4b', '.m4r',
  '.mp2', '.mp1', '.ac3', '.eac3', '.dts', '.tta', '.tak', '.spx',
  '.dsf', '.dff', '.webm', '.weba', '.mp4', '.3gp', '.3g2',
]);

export function extensionOf(name) {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot).toLowerCase() : '';
}

export function isAudioFile(name, mimeType = '') {
  if (name.startsWith('.')) return false; // hidden files such as macOS "._song.mp3"
  return AUDIO_EXTENSIONS.has(extensionOf(name)) || String(mimeType).startsWith('audio/');
}

// "Lucid Dreams.mp3" -> "Lucid Dreams" (Python's os.path.splitext(...)[0]).
export function trackTitle(name) {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(0, dot) : name;
}

const VERSION_SUFFIX = new RegExp(
  String.raw`\s*(?:\(|\[)?\s*(?:session(?:\s+edit|s)?|normal(?:\s+version)?|` +
  String.raw`original(?:\s+version)?|standard(?:\s+version)?|studio(?:\s+version)?|` +
  String.raw`album(?:\s+version)?|alternate(?:\s+version)?|alt(?:\s+version)?|` +
  String.raw`demo|version\s*\d+|v\d+)\s*(?:\)|\])?\s*$`,
  'i',
);

function stripChars(value, chars) {
  let start = 0;
  let end = value.length;
  while (start < end && chars.includes(value[start])) start += 1;
  while (end > start && chars.includes(value[end - 1])) end -= 1;
  return value.slice(start, end);
}

// Same rules as normalize_song_title in web_app.py: case, spacing and
// underscores are ignored, and "(Session)", "v2", "Demo" style endings are dropped.
export function normalizeSongTitle(title) {
  let normalized = String(title).replace(/_/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  let previous = null;
  while (normalized !== previous) {
    previous = normalized;
    normalized = stripChars(normalized.replace(VERSION_SUFFIX, '').trim(), ' -_()[]');
  }
  return normalized;
}

export function pointsFor(durations, attempt) {
  return (durations.length - attempt) * 10;
}

// Where a Random Drop snippet starts, so the longest preview still fits.
export function randomStart(totalSeconds, longestPreview, random = Math.random) {
  const room = Math.max(0, totalSeconds - Math.min(totalSeconds, longestPreview));
  return random() * room;
}

function pick(list, random) {
  return list[Math.floor(random() * list.length)];
}

// ---------------------------------------------------------------- stats

export function emptyStats() {
  return {
    version: 1,
    total_correct: 0, total_wrong: 0, total_points: 0,
    current_streak: 0, best_streak: 0, songs_played: 0,
    counters: { first_try: 0, hard: 0 },
    grails: {},        // track key -> { title, collected_at }
    song_stats: {},    // track key -> { title, correct, wrong }
    achievements: {},  // achievement id -> unlocked_at
  };
}

export function sanitizeStats(saved) {
  const stats = emptyStats();
  if (!saved || typeof saved !== 'object') return stats;
  for (const key of ['total_correct', 'total_wrong', 'total_points', 'current_streak', 'best_streak', 'songs_played']) {
    const value = Number(saved[key]);
    if (Number.isFinite(value) && value >= 0) stats[key] = Math.floor(value);
  }
  for (const key of ['first_try', 'hard']) {
    const value = Number(saved.counters?.[key]);
    if (Number.isFinite(value) && value >= 0) stats.counters[key] = Math.floor(value);
  }
  for (const field of ['grails', 'song_stats', 'achievements']) {
    if (saved[field] && typeof saved[field] === 'object') stats[field] = { ...saved[field] };
  }
  return stats;
}

function songRecord(stats, key, title) {
  const record = stats.song_stats[key] || { title, correct: 0, wrong: 0 };
  record.title = title;
  stats.song_stats[key] = record;
  return record;
}

// ---------------------------------------------------------------- achievements
// Same catalog as achievements.py, minus the Google/Discord "Connections" ones,
// which need sign-in (not part of the website yet).

export const ACHIEVEMENTS = [];

function milestones(category, metric, targets, names, requirement) {
  targets.forEach((target, index) => {
    ACHIEVEMENTS.push({
      id: `${metric}_${target}`, name: names[index], category, metric, target,
      description: requirement.replace('{n}', target.toLocaleString('en-US')),
    });
  });
}

milestones('Recognition', 'correct', [1, 10, 25, 50, 100, 250, 500, 999],
  ['First Hit', 'Finding Your Sound', 'On the Wavelength', 'Fifty Shades of Juice',
    'Century Club', 'Deep Cut Detective', 'Human Shazam', '999 Forever'],
  'Make {n} correct song guesses in total.');
milestones('Points', 'points', [100, 500, 1000, 2500, 5000, 10000, 25000, 99999],
  ['On the Board', 'Pocket Change', 'Four Figures', 'Stacking Up', 'High Roller',
    'Five Figures', 'Vault Builder', '999 Fortune'],
  'Earn {n} lifetime points.');
milestones('Streaks', 'streak', [3, 5, 10, 15, 25, 50, 99],
  ['Three-Peat', 'Heating Up', 'Unstoppable', 'In the Zone', 'Purple Flame',
    'Never Miss a Beat', 'Streak Legend'],
  'Win {n} rounds in a row without losing a round. Wrong guesses within a winning round are allowed.');
milestones('Collection', 'grails', [1, 5, 10, 25, 50, 100, 250],
  ['First Grail', 'Crate Digger', 'Hidden Gems', 'Grail Hunter', 'Private Vault',
    'Archive Keeper', 'Museum of Juice'],
  'Correctly identify {n} different songs to collect their grails.');
milestones('Dedication', 'rounds', [10, 50, 100, 250, 500, 1000],
  ['Settling In', 'Regular Listener', 'On Repeat', 'Long Session', 'No Skips in Spirit',
    'Thousand-Round Tour'],
  'Finish {n} rounds, won or lost. Changing or rerolling a song does not count.');
milestones('Quick Ears', 'first_try', [1, 10, 25, 50, 100, 250],
  ['Instant Recognition', 'One-Shot Wonder', 'Quick Draw', 'Split-Second Ear',
    'First-Try Specialist', 'One Second Legend'],
  'Win {n} rounds on the first attempt, without a wrong guess or skipped attempt.');
milestones('Hard Mode', 'hard', [1, 10, 25, 50, 100, 250],
  ['Hard Debut', 'Pressure Tested', 'Hard-Hitting', 'Against the Odds', 'Expert Ear',
    'Hard Mode Royalty'],
  'Win {n} rounds on Hard difficulty.');

export function achievementMetrics(stats) {
  return {
    correct: stats.total_correct, points: stats.total_points, streak: stats.best_streak,
    rounds: stats.songs_played, grails: Object.keys(stats.grails).length,
    first_try: stats.counters.first_try, hard: stats.counters.hard,
  };
}

// Unlocks anything newly reached (mutating stats.achievements) and returns
// the full list plus the ones unlocked by this call.
export function evaluateAchievements(stats, now = new Date().toISOString()) {
  const metrics = achievementMetrics(stats);
  const newlyUnlocked = [];
  const entries = ACHIEVEMENTS.map(item => {
    const value = metrics[item.metric] || 0;
    if (value >= item.target && !stats.achievements[item.id]) {
      stats.achievements[item.id] = now;
      newlyUnlocked.push(item);
    }
    const unlocked = Boolean(stats.achievements[item.id]);
    return { ...item, progress: unlocked ? item.target : Math.min(value, item.target), unlocked,
      unlocked_at: stats.achievements[item.id] || null };
  });
  return { entries, newlyUnlocked, unlocked: entries.filter(entry => entry.unlocked).length, total: ACHIEVEMENTS.length };
}

// ---------------------------------------------------------------- the round

// tracks: [{ key, name, title }]. key must be unique (we use the file's path
// inside the chosen folder). The Game only decides *what* happens; app.js plays
// the audio and draws the page.
export class Game {
  constructor({ stats = emptyStats(), difficulty = 'Easy', mode = 'classic', random = Math.random } = {}) {
    this.stats = stats;
    this.random = random;
    this.difficulty = DIFFICULTIES[difficulty] ? difficulty : 'Easy';
    this.mode = GAME_MODES[mode] ? mode : 'classic';
    this.tracks = [];
    this.current = null;
    this.attempt = 0;
    this.gameOver = false;
    this.randomStart = null; // seconds into the song, chosen once per round
    this.session = { score: 0, correct: 0, wrong: 0, rounds: 0 };
  }

  get durations() { return DIFFICULTIES[this.difficulty]; }
  get longestPreview() { return Math.max(...this.durations); }
  get currentDuration() { return this.durations[Math.min(this.attempt, this.durations.length - 1)]; }
  get worth() { return pointsFor(this.durations, this.attempt); }

  setTracks(tracks) {
    this.tracks = tracks.slice();
    if (this.current && !this.tracks.some(track => track.key === this.current.key)) this.current = null;
  }

  removeTrack(key) {
    this.tracks = this.tracks.filter(track => track.key !== key);
  }

  nextRound(excludeKey = null) {
    let eligible = this.tracks;
    if (excludeKey !== null) eligible = eligible.filter(track => track.key !== excludeKey).length ? eligible.filter(track => track.key !== excludeKey) : eligible;
    this.current = eligible.length ? pick(eligible, this.random) : null;
    this.attempt = 0;
    this.gameOver = false;
    this.randomStart = null;
    return this.current;
  }

  setDifficulty(difficulty) {
    if (!DIFFICULTIES[difficulty]) return false;
    this.difficulty = difficulty;
    this.nextRound();
    return true;
  }

  setMode(mode) {
    if (!GAME_MODES[mode] || mode === this.mode) return false;
    const previous = this.current?.key ?? null;
    this.mode = mode;
    this.nextRound(previous);
    return true;
  }

  // Changes the song without touching score or stats (same as the desktop app).
  reroll() {
    if (!this.current || this.gameOver) return { changed: false, message: 'Start a round before rerolling.' };
    const alternatives = this.tracks.filter(track => track.key !== this.current.key);
    if (!alternatives.length) return { changed: false, message: 'There are no other songs to reroll to.' };
    this.current = pick(alternatives, this.random);
    this.attempt = 0;
    this.randomStart = null;
    return { changed: true, message: 'Song changed. Your score and stats are unchanged.' };
  }

  // Called by the audio code once it knows the song length.
  snippetStart(songSeconds) {
    if (this.mode !== 'random') return 0;
    if (this.randomStart === null || this.randomStart + this.longestPreview > songSeconds + 0.001) {
      this.randomStart = randomStart(songSeconds, this.longestPreview, this.random);
    }
    return this.randomStart;
  }

  guess(text, now = new Date().toISOString()) {
    if (!this.current || this.gameOver) return { success: false, message: 'Choose a music folder to start.', ignored: true };
    const title = this.current.title;
    if (normalizeSongTitle(text) === normalizeSongTitle(title)) {
      const points = this.worth;
      const s = this.stats;
      this.session.score += points;
      this.session.correct += 1;
      this.session.rounds += 1;
      s.total_correct += 1;
      s.total_points += points;
      s.current_streak += 1;
      s.best_streak = Math.max(s.best_streak, s.current_streak);
      s.songs_played += 1;
      songRecord(s, this.current.key, title).correct += 1;
      if (!s.grails[this.current.key]) s.grails[this.current.key] = { title, collected_at: now };
      if (this.attempt === 0) s.counters.first_try += 1;
      if (this.difficulty === 'Hard') s.counters.hard += 1;
      this.gameOver = true;
      const achievements = evaluateAchievements(s, now);
      return { success: true, points, title, gameOver: true, message: `Correct! It was '${title}'. +${points} points.`,
        newlyUnlocked: achievements.newlyUnlocked };
    }
    this.session.wrong += 1;
    this.stats.total_wrong += 1;
    songRecord(this.stats, this.current.key, title).wrong += 1;
    const result = this.skip(now);
    result.message = result.gameOver
      ? `Incorrect guess. The track was '${title}'.`
      : 'Incorrect guess. Revealing a longer snippet...';
    result.wrongGuess = true;
    return result;
  }

  skip(now = new Date().toISOString()) {
    if (!this.current || this.gameOver) return { success: false, message: 'Choose a music folder to start.', ignored: true };
    this.attempt += 1;
    if (this.attempt >= this.durations.length) {
      this.attempt = this.durations.length - 1;
      this.stats.current_streak = 0;
      this.stats.songs_played += 1;
      this.session.rounds += 1;
      this.gameOver = true;
      const achievements = evaluateAchievements(this.stats, now);
      return { success: false, gameOver: true, title: this.current.title,
        message: `Round over. The track was '${this.current.title}'.`, newlyUnlocked: achievements.newlyUnlocked };
    }
    return { success: false, gameOver: false, message: '' };
  }

  // A small object saved between visits so reloading the page cannot be used
  // to dodge a hard round (the desktop app saves its round the same way).
  snapshot() {
    if (!this.current) return null;
    return { key: this.current.key, attempt: this.attempt, gameOver: this.gameOver,
      randomStart: this.randomStart, difficulty: this.difficulty, mode: this.mode };
  }

  restore(saved) {
    if (!saved || typeof saved !== 'object' || !DIFFICULTIES[saved.difficulty] || !GAME_MODES[saved.mode]) return false;
    const track = this.tracks.find(item => item.key === saved.key);
    const durations = DIFFICULTIES[saved.difficulty];
    if (!track || !Number.isInteger(saved.attempt) || saved.attempt < 0 || saved.attempt >= durations.length || saved.gameOver) return false;
    this.difficulty = saved.difficulty;
    this.mode = saved.mode;
    this.current = track;
    this.attempt = saved.attempt;
    this.gameOver = false;
    this.randomStart = typeof saved.randomStart === 'number' && saved.randomStart >= 0 ? saved.randomStart : null;
    return true;
  }
}

// ---------------------------------------------------------------- challenges
// Ported from assets/graild-challenges.js. A challenge is a run of normal
// rounds with extra rules; points still count toward lifetime stats.

export const CHALLENGES = {
  sudden_death: { name: 'Sudden Death', unit: 'songs', icon: '1×', tone: 'red', short: 'One wrong guess ends the run.',
    blurb: 'One wrong guess ends the run. Skipping is allowed, so listen longer if you need to.' },
  three_lives: { name: 'Three Lives', unit: 'songs', lives: 3, icon: '♥♥♥', tone: 'pink', short: 'Every missed song costs a life.',
    blurb: 'Miss a song and you lose a life. See how far three lives take you.' },
  time_attack: { name: 'Time Attack', unit: 'pts', seconds: 90, icon: '90s', tone: 'lime', short: 'Most points in 90 seconds.',
    blurb: '90 seconds on the clock. New songs load and play by themselves, so keep guessing.' },
  sprint: { name: 'Sprint', unit: 'pts', songs: 10, icon: '10', tone: 'blue', short: 'Ten songs, highest score wins.',
    blurb: 'Ten songs. Score as many points as you can. Fewer attempts means more points.' },
};

export const CHALLENGE_END_REASONS = {
  wrong: 'A wrong guess ended the run.',
  missed: 'You ran out of attempts on a song.',
  lives: 'Out of lives.',
  time: "Time's up!",
  done: 'All ten songs played.',
  quit: 'You ended the run.',
};

export function challengeUnitText(mode, value) {
  return CHALLENGES[mode].unit === 'songs'
    ? `${value} song${value === 1 ? '' : 's'}`
    : `${Number(value).toLocaleString('en-US')} pts`;
}

export class ChallengeRun {
  constructor(mode, now = Date.now()) {
    if (!CHALLENGES[mode]) throw new Error(`Unknown challenge: ${mode}`);
    const rules = CHALLENGES[mode];
    this.mode = mode;
    this.rules = rules;
    this.solved = 0;
    this.played = 0;
    this.points = 0;
    this.lives = rules.lives || 0;
    this.endsAt = rules.seconds ? now + rules.seconds * 1000 : 0;
    this.wrongGuess = false;
  }

  get score() { return this.rules.unit === 'songs' ? this.solved : this.points; }

  secondsLeft(now = Date.now()) {
    return this.endsAt ? Math.max(0, Math.ceil((this.endsAt - now) / 1000)) : null;
  }

  timeUp(now = Date.now()) { return Boolean(this.endsAt) && now >= this.endsAt; }

  // After a wrong guess that did not end the round: in Sudden Death the song
  // must be forfeited (the caller skips the remaining attempts).
  wrongGuessEndsSong() {
    if (this.mode !== 'sudden_death') return false;
    this.wrongGuess = true;
    return true;
  }

  // Call once per finished round. Returns the reason the run ended, or null.
  roundFinished(won, points = 0) {
    this.played += 1;
    if (won) { this.solved += 1; this.points += points; }
    let reason = null;
    if (this.mode === 'sudden_death' && !won) reason = this.wrongGuess ? 'wrong' : 'missed';
    else if (this.mode === 'three_lives' && !won) { this.lives -= 1; if (this.lives <= 0) reason = 'lives'; }
    else if (this.mode === 'sprint' && this.played >= this.rules.songs) reason = 'done';
    this.wrongGuess = false;
    return reason;
  }
}

// bests: { mode: { best_score, best_songs, runs } } (same shape as the desktop app).
export function saveChallengeBest(bests, mode, score, songs) {
  const previous = bests[mode];
  const newBest = score > (previous ? previous.best_score : 0);
  bests[mode] = {
    best_score: Math.max(previous ? previous.best_score : 0, score),
    best_songs: Math.max(previous ? previous.best_songs : 0, songs),
    runs: (previous ? previous.runs : 0) + 1,
  };
  return newBest;
}

export function sanitizeBests(saved) {
  const bests = {};
  if (!saved || typeof saved !== 'object') return bests;
  for (const mode of Object.keys(CHALLENGES)) {
    const entry = saved[mode];
    if (!entry || typeof entry !== 'object') continue;
    const clean = {};
    for (const key of ['best_score', 'best_songs', 'runs']) {
      const value = Number(entry[key]);
      clean[key] = Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
    }
    bests[mode] = clean;
  }
  return bests;
}

// Ends the current round by using up its remaining attempts (Sudden Death).
export function forfeitRound(game, now) {
  let result = null;
  for (let step = 0; step < 20 && !game.gameOver; step += 1) result = game.skip(now);
  return result;
}
