// Connects the page to the game. This replaces the desktop app's
// window.pywebview.api.* calls: everything runs in the browser.
import {
  ANSWER_SECONDS, CHALLENGES, CHALLENGE_END_REASONS, ChallengeRun, GAME_MODES, Game, challengeUnitText,
  evaluateAchievements, forfeitRound, sanitizeBests, sanitizeStats, saveChallengeBest,
} from './game-core.js';
import { SnippetPlayer } from './audio.js';
import * as library from './library.js';
import * as canary from './canary.js';

const STATS_KEY = 'graild-web-stats-v1';
const ROUND_KEY = 'graild-web-round-v1';
const PREFS_KEY = 'graild-web-prefs-v1';
const BESTS_KEY = 'graild-web-challenge-bests-v1';

const $ = id => document.getElementById(id);

function load(key, fallback) {
  try { const value = JSON.parse(localStorage.getItem(key)); return value ?? fallback; } catch { return fallback; }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}

const prefs = { difficulty: 'Easy', mode: 'classic', volume: 70, canary: true, ...load(PREFS_KEY, {}) };
const game = new Game({ stats: sanitizeStats(load(STATS_KEY, null)), difficulty: prefs.difficulty, mode: prefs.mode });
const player = new SnippetPlayer();
player.setVolume(prefs.volume / 100);

let folder = null;       // { name, tracks, remembered }
let remembered = null;   // folder handle from an earlier visit (Chrome/Edge)
let roundLog = [];       // this round's wrong guesses / skips
let playback = null;     // { startedAt, duration, frame }
let busy = false;
let canaryRequest = 0;
let challenge = null;    // the running ChallengeRun, if any
let lastRun = null;      // the finished run shown in the summary box
let bests = sanitizeBests(load(BESTS_KEY, null));
let clockTimer = 0;
let advanceTimer = 0;

// ------------------------------------------------------------ saving

function persist() {
  const ok = save(STATS_KEY, game.stats);
  save(ROUND_KEY, game.gameOver ? null : game.snapshot());
  if (!ok) showFeedback('Your browser would not let GRAIL\'D save stats (storage is full or blocked).');
}
function savePrefs() {
  save(PREFS_KEY, prefs);
}

// ------------------------------------------------------------ tabs

function switchTab(name) {
  ['games', 'play', 'stats', 'settings'].forEach(id => {
    $(`tab-${id}`).classList.toggle('hidden', id !== name);
    const button = document.querySelector(`[data-tab="${id}"]`);
    button.className = id === name ? 'nav-btn is-active bg-purple-600' : 'nav-btn';
    if (id === name) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  if (name === 'stats') renderStats();
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------ drawing

function showFeedback(message, success = false) {
  const banner = $('feedback-banner');
  banner.textContent = message;
  banner.className = `feedback ${success ? 'is-ok' : 'is-bad'}`;
}

function songHue(title) {
  let hash = 0;
  for (const char of title) hash = (hash * 31 + char.codePointAt(0)) % 360;
  return hash;
}

function renderTimeline() {
  const bars = $('timeline-bars');
  bars.replaceChildren();
  game.durations.forEach((seconds, index) => {
    const segment = document.createElement('div');
    segment.className = 'attempt-seg';
    segment.textContent = `${seconds}s`;
    let state = 'future';
    if (index < roundLog.length) state = roundLog[index].kind === 'skip' ? 'skipped' : 'wrong';
    else if (index < game.attempt) state = 'past';
    if (index === game.attempt && !game.gameOver) state = 'current';
    if (index === game.attempt && game.gameOver && roundLog.won) state = 'won';
    segment.dataset.state = state;
    bars.append(segment);
  });
}

function renderRoundLog() {
  const list = $('round-log');
  list.replaceChildren(...roundLog.map((entry, index) => {
    const item = document.createElement('li');
    const n = document.createElement('span'); n.className = 'n'; n.textContent = `${game.durations[index] ?? ''}s`;
    const text = document.createElement('span'); text.className = 'txt'; text.textContent = entry.kind === 'skip' ? 'Skipped' : entry.guess;
    const tag = document.createElement('span');
    tag.className = entry.kind === 'skip' ? 'tag-s' : 'tag-x';
    tag.textContent = entry.kind === 'skip' ? 'SKIP' : 'WRONG';
    item.append(n, text, tag);
    return item;
  }));
  list.classList.toggle('hidden', roundLog.length === 0);
}

function renderGame() {
  const hasFolder = Boolean(folder);
  $('welcome').classList.toggle('hidden', hasFolder && game.tracks.length > 0);
  $('game').classList.toggle('hidden', !hasFolder || game.tracks.length === 0);
  if (!hasFolder) return;
  const mode = challenge ? { title: challenge.rules.name, description: challenge.rules.blurb } : GAME_MODES[game.mode];
  $('game-mode-title').textContent = mode.title;
  $('game-mode-description').textContent = mode.description;
  $('mode-select').disabled = Boolean(challenge);
  $('difficulty-select').disabled = Boolean(challenge);
  $('mode-select').value = game.mode;
  $('difficulty-select').value = game.difficulty;
  $('current-attempt').textContent = String(game.attempt + 1);
  $('attempt-count').textContent = String(game.durations.length);
  $('snippet-sec').textContent = String(game.currentDuration);
  $('round-worth').textContent = game.gameOver ? '' : `Worth ${game.worth} pts`;
  $('game-score').textContent = `Score: ${game.session.score}`;
  $('game-streak').textContent = String(game.stats.current_streak);
  $('library-line').textContent = `${folder.name} · ${game.tracks.length.toLocaleString()} songs${folder.truncated ? ' (first 20,000 only)' : ''}`;
  const over = game.gameOver;
  $('play-btn').disabled = over || !game.current;
  ['guess-input', 'submit-btn', 'skip-btn', 'reroll-btn'].forEach(id => { $(id).disabled = over || !game.current; });
  if (challenge) $('reroll-btn').disabled = true;
  $('input-area').classList.toggle('hidden', over);
  $('next-round-btn').classList.toggle('hidden', !over);
  renderTimeline();
  renderRoundLog();
  renderSession();
  renderChallengeHud();
}

function renderSession() {
  const { correct, wrong, rounds } = game.session;
  $('side-correct').textContent = String(correct);
  $('side-wrong').textContent = String(wrong);
  $('side-rounds').textContent = String(rounds);
  $('side-accuracy').textContent = correct + wrong ? `${Math.round((correct / (correct + wrong)) * 100)}%` : '-';
}

function addHistory(title, won, points) {
  const item = document.createElement('li');
  if (won) item.className = 'is-win';
  const dot = document.createElement('span'); dot.className = 'dot';
  const t = document.createElement('span'); t.className = 't'; t.textContent = title;
  const p = document.createElement('span'); p.className = 'p'; p.textContent = won ? `+${points}` : 'Missed';
  item.append(dot, t, p);
  $('round-history').prepend(item);
  $('round-history-empty').classList.add('hidden');
}

function renderStats() {
  const s = game.stats;
  const guesses = s.total_correct + s.total_wrong;
  const achievements = evaluateAchievements(s);
  $('stat-points').textContent = s.total_points.toLocaleString();
  $('stat-accuracy').textContent = guesses ? `${Math.round((s.total_correct / guesses) * 100)}%` : '-';
  $('stat-best-streak').textContent = String(s.best_streak);
  $('stat-streak').textContent = String(s.current_streak);
  $('stat-played').textContent = s.songs_played.toLocaleString();
  $('stat-guesses').textContent = `${s.total_correct.toLocaleString()} / ${s.total_wrong.toLocaleString()}`;
  $('stat-grails').textContent = Object.keys(s.grails).length.toLocaleString();
  $('stat-achievements').textContent = `${achievements.unlocked} / ${achievements.total}`;
  $('achievement-list').replaceChildren(...achievements.entries.map(entry => {
    const item = document.createElement('li');
    item.className = entry.unlocked ? 'is-unlocked' : '';
    const name = document.createElement('strong'); name.textContent = entry.name;
    const category = document.createElement('span'); category.className = 'tiny'; category.textContent = entry.category;
    const description = document.createElement('span'); description.className = 'small'; description.textContent = entry.description;
    const bar = document.createElement('progress'); bar.max = entry.target; bar.value = entry.progress;
    bar.setAttribute('aria-label', `${entry.name} progress`);
    const count = document.createElement('span'); count.className = 'tiny tabular';
    count.textContent = entry.unlocked ? 'Unlocked' : `${entry.progress.toLocaleString()} / ${entry.target.toLocaleString()}`;
    item.append(category, name, description, bar, count);
    return item;
  }));
}

function renderFolderSettings() {
  $('settings-folder').textContent = folder
    ? `${folder.name} (${folder.tracks.length.toLocaleString()} songs)${folder.remembered ? ', remembered by this browser' : ''}`
    : (remembered ? `${remembered.name} (remembered, not opened yet)` : 'No folder chosen.');
  $('forget-folder').disabled = !folder && !remembered;
}

// ------------------------------------------------------------ cover / Canary

function resetCover() {
  canaryRequest += 1;
  $('cover-container').classList.add('hidden');
  $('cover-art-inner').replaceChildren('💿');
  $('canary-details').replaceChildren();
}

async function showCover(title, won) {
  const box = $('cover-container');
  box.classList.remove('hidden');
  box.classList.toggle('is-miss', !won);
  $('correct-song-title').textContent = title;
  $('cover-art-inner').replaceChildren('💿');
  const details = $('canary-details');
  details.replaceChildren();
  if (!prefs.canary) return;
  const request = ++canaryRequest;
  details.textContent = 'Looking up Canary details...';
  try {
    const song = await canary.findSong(title);
    if (request !== canaryRequest) return;
    details.replaceChildren();
    if (!song) { details.textContent = 'No exact match on Canary.'; return; }
    if (song.coverUrl) {
      const image = document.createElement('img');
      image.src = song.coverUrl;
      image.alt = `Cover art for ${song.title}`;
      image.referrerPolicy = 'no-referrer';
      image.className = 'cover-img';
      image.onerror = () => $('cover-art-inner').replaceChildren('💿');
      $('cover-art-inner').replaceChildren(image);
    }
    const facts = [song.era && `Era: ${song.era}`, song.category, song.duration].filter(Boolean).join(' · ');
    if (facts) details.append(facts);
    if (song.pageUrl) {
      const link = document.createElement('a');
      link.href = song.pageUrl; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.className = 'link-btn is-p canary-link';
      link.textContent = 'Open on Canary ↗';
      details.append(link);
    }
  } catch (error) {
    if (request === canaryRequest) details.textContent = error.message;
  }
}

// ------------------------------------------------------------ audio

function resetPlayButton() {
  if (playback) cancelAnimationFrame(playback.frame);
  playback = null;
  $('snippet-deck').classList.remove('is-playing');
  $('snippet-play-label').textContent = 'PLAY';
  $('snippet-play-icon').textContent = '▶';
  $('snippet-progress').value = 0;
}

function tick() {
  if (!playback) return;
  const elapsed = Math.max(0, player.now - playback.startedAt);
  $('snippet-progress').value = Math.min(1000, (elapsed / playback.duration) * 1000);
  $('snippet-clock').textContent = `${Math.min(elapsed, playback.duration).toFixed(1)}s`;
  playback.frame = requestAnimationFrame(tick);
}

player.onEnded = () => {
  if (playback) { $('snippet-clock').textContent = `${playback.duration.toFixed(1)}s`; }
  resetPlayButton();
};

async function playSegment(kind) {
  const track = game.current;
  if (!track) return;
  try { player.unlock(); } catch (error) { showFeedback(error.message); return; }
  if (kind === 'snippet') {
    $('snippet-play-label').textContent = 'LOADING';
    $('snippet-play-icon').textContent = '⏳';
  }
  let buffer;
  try {
    buffer = await player.load(track);
  } catch (error) {
    resetPlayButton();
    if (game.current !== track) return;
    game.removeTrack(track.key);
    game.nextRound();
    roundLog = [];
    persist();
    renderGame();
    showFeedback(game.current
      ? `Couldn't play '${track.name}': ${error.message}. Skipped it and picked another song.`
      : `Couldn't play '${track.name}': ${error.message}. No other songs are available.`);
    return;
  }
  if (game.current !== track) return; // the round changed while loading
  const offset = kind === 'answer' ? 0 : game.snippetStart(buffer.duration);
  const seconds = kind === 'answer' ? ANSWER_SECONDS : game.currentDuration;
  if (kind === 'snippet' && game.mode === 'random') persist(); // keep the random start for this round
  resetPlayButton();
  playback = { ...player.play(buffer, offset, seconds), frame: 0 };
  if (kind === 'snippet') {
    $('snippet-deck').classList.add('is-playing');
    $('snippet-play-label').textContent = 'PLAYING';
    $('snippet-play-icon').textContent = '♫';
  }
  tick();
}

// ------------------------------------------------------------ round actions

function clearGuess() {
  $('guess-input').value = '';
  hideSuggestions();
}

function afterResult(result, action) {
  if (result.ignored) { showFeedback(result.message); return; }
  if (action) roundLog.push(action);
  if (result.gameOver) {
    roundLog.won = result.success;
    addHistory(result.title, result.success, result.points || 0);
  }
  persist();
  clearGuess();
  renderGame();
  let message = result.message;
  if (result.newlyUnlocked && result.newlyUnlocked.length) {
    message += ` 🏆 Unlocked: ${result.newlyUnlocked.map(item => item.name).join(', ')}.`;
  }
  showFeedback(message, result.success === true);
  if (result.gameOver) {
    showCover(result.title, result.success);
    if (result.success) playSegment('answer');
    $('next-round-btn').focus();
    challengeRoundFinished(result);
  }
}

function submitGuess() {
  const guess = $('guess-input').value.trim();
  if (!guess) { showFeedback('Type a song title first.'); return; }
  if (busy) return;
  player.stop();
  try { player.unlock(); } catch { /* sound is optional for guessing */ }
  const result = game.guess(guess);
  if (challenge && result.wrongGuess && !result.gameOver && challenge.wrongGuessEndsSong()) {
    // Sudden Death: a wrong guess loses the song straight away.
    roundLog.push({ kind: 'guess', guess });
    const title = game.current.title;
    const forfeit = forfeitRound(game);
    forfeit.message = `Wrong guess - Sudden Death! The track was '${title}'.`;
    afterResult(forfeit, null);
    return;
  }
  afterResult(result, result.success || result.ignored ? null : { kind: 'guess', guess });
}

function skipAttempt() {
  if (busy) return;
  player.stop();
  try { player.unlock(); } catch { /* ignore */ }
  afterResult(game.skip(), { kind: 'skip' });
}

function startNewRound(message = '') {
  player.stop();
  resetPlayButton();
  resetCover();
  game.nextRound();
  roundLog = [];
  persist();
  clearGuess();
  renderGame();
  showFeedback(message, Boolean(message));
  if (game.current) $('guess-input').focus();
}

function reroll() {
  const result = game.reroll();
  if (result.changed) {
    player.stop();
    resetPlayButton();
    roundLog = [];
    persist();
    clearGuess();
    renderGame();
  }
  showFeedback(result.message, result.changed);
}

// ------------------------------------------------------------ autocomplete

let suggestionIndex = -1;

function hideSuggestions() {
  $('suggestions').classList.add('hidden');
  $('guess-input').setAttribute('aria-expanded', 'false');
  suggestionIndex = -1;
}

function uniqueTitles() {
  if (!folder) return [];
  if (folder.titles) return folder.titles;
  const seen = new Map();
  game.tracks.forEach(track => { const key = track.title.toLowerCase(); if (!seen.has(key)) seen.set(key, track.title); });
  folder.titles = [...seen.values()].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
  return folder.titles;
}

function handleTyping() {
  const input = $('guess-input');
  const query = input.value.trim().toLocaleLowerCase();
  const box = $('suggestions');
  box.replaceChildren();
  suggestionIndex = -1;
  const all = query ? uniqueTitles().filter(title => title.toLocaleLowerCase().includes(query)) : [];
  const matches = all.slice(0, 6);
  if (matches.length) {
    const head = document.createElement('div');
    head.className = 'suggest-head tabular';
    head.textContent = `${all.length.toLocaleString()} match${all.length === 1 ? '' : 'es'}`;
    box.append(head);
  }
  matches.forEach(title => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'suggestion';
    item.setAttribute('role', 'option');
    const thumb = document.createElement('span');
    thumb.className = 'song-thumb';
    thumb.style.setProperty('--h', songHue(title));
    const label = document.createElement('span');
    label.className = 'label';
    const at = title.toLocaleLowerCase().indexOf(query);
    const mark = document.createElement('mark');
    mark.textContent = title.slice(at, at + query.length);
    label.append(title.slice(0, at), mark, title.slice(at + query.length));
    item.append(thumb, label);
    item.addEventListener('mousedown', event => event.preventDefault()); // keep focus in the input
    item.addEventListener('click', () => { input.value = title; hideSuggestions(); input.focus(); });
    box.append(item);
  });
  box.classList.toggle('hidden', matches.length === 0);
  input.setAttribute('aria-expanded', String(matches.length > 0));
}

function handleGuessKey(event) {
  const items = [...document.querySelectorAll('#suggestions .suggestion')];
  const open = !$('suggestions').classList.contains('hidden');
  if (open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    event.preventDefault();
    const step = event.key === 'ArrowDown' ? 1 : -1;
    suggestionIndex = suggestionIndex < 0 ? (step > 0 ? 0 : items.length - 1) : (suggestionIndex + step + items.length) % items.length;
    items.forEach((item, index) => item.classList.toggle('is-active', index === suggestionIndex));
  } else if (event.key === 'Escape' && open) {
    event.preventDefault();
    hideSuggestions();
  } else if (event.key === 'Enter' && !event.ctrlKey && !event.metaKey) {
    event.preventDefault();
    if (event.repeat) return;
    if (open && suggestionIndex >= 0) items[suggestionIndex].click();
    else { hideSuggestions(); submitGuess(); }
  }
}

// ------------------------------------------------------------ games & challenges

function make(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== '') node.textContent = text;
  return node;
}

function needFolder() {
  if (folder && game.tracks.length) return false;
  switchTab('play');
  $('welcome-status').textContent = 'Choose a music folder with songs first, then pick your game.';
  return true;
}

function startGameMode(mode) {
  if (needFolder()) return;
  if (challenge) finishChallenge('left');
  lastRun = null;
  renderSummary();
  if (game.setMode(mode)) { prefs.mode = game.mode; savePrefs(); }
  switchTab('play');
  startNewRound(`${GAME_MODES[game.mode].title}: new round started.`);
}

function startChallenge(mode) {
  if (needFolder() || !CHALLENGES[mode]) return;
  if (challenge) finishChallenge('left');
  clearTimeout(advanceTimer);
  lastRun = null;
  renderSummary();
  challenge = new ChallengeRun(mode);
  switchTab('play');
  startNewRound(`${challenge.rules.name} started. ${challenge.rules.blurb}`);
  if (challenge.rules.seconds) {
    const run = challenge;
    clockTimer = setInterval(() => {
      if (challenge !== run) return;
      if (run.timeUp()) finishChallenge('time'); else renderChallengeHud();
    }, 250);
    playSegment('snippet'); // runs inside the card click, so the browser allows sound
  }
}

function challengeRoundFinished(result) {
  if (!challenge) return;
  const reason = challenge.roundFinished(result.success === true, result.points || 0);
  if (reason) { finishChallenge(reason); return; }
  renderChallengeHud();
  if (challenge.mode === 'time_attack') {
    const run = challenge;
    advanceTimer = setTimeout(() => {
      if (challenge !== run || !game.gameOver) return; // player already moved on
      startNewRound();
      playSegment('snippet');
    }, result.success ? 1600 : 1200);
  }
}

function finishChallenge(reason) {
  if (!challenge) return;
  clearInterval(clockTimer);
  clearTimeout(advanceTimer);
  const ended = challenge;
  challenge = null;
  let newBest = false;
  if (ended.played > 0 || reason !== 'left') {
    newBest = saveChallengeBest(bests, ended.mode, ended.score, ended.solved);
    if (!save(BESTS_KEY, bests)) showFeedback('Your browser would not let GRAIL\'D save this run.');
  }
  if (reason !== 'left') {
    lastRun = { mode: ended.mode, reason, newBest, score: ended.score, solved: ended.solved, played: ended.played, points: ended.points };
    if (reason === 'time') { player.stop(); resetPlayButton(); }
  }
  renderGame();
  renderSummary();
  renderChallengeCards();
}

function renderChallengeHud() {
  const hud = $('challenge-hud');
  hud.classList.toggle('hidden', !challenge);
  if (!challenge) return;
  const rules = challenge.rules;
  $('challenge-name').textContent = rules.name;
  const meter = $('challenge-meter');
  meter.replaceChildren();
  meter.dataset.urgent = 'false';
  if (challenge.mode === 'three_lives') {
    for (let index = 0; index < rules.lives; index += 1) {
      meter.append(make('span', index < challenge.lives ? 'life is-on' : 'life', index < challenge.lives ? '♥' : '♡'));
    }
    meter.setAttribute('aria-label', `${challenge.lives} of ${rules.lives} lives left`);
  } else if (challenge.mode === 'time_attack') {
    const left = challenge.secondsLeft();
    meter.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
    meter.dataset.urgent = String(left <= 10);
    meter.setAttribute('aria-label', `${left} seconds left`);
  } else if (challenge.mode === 'sprint') {
    meter.textContent = `Song ${Math.min(challenge.played + 1, rules.songs)} / ${rules.songs}`;
  } else {
    meter.textContent = challenge.solved ? `${challenge.solved} in a row` : 'No mistakes allowed';
  }
  $('challenge-score').textContent = challengeUnitText(challenge.mode, challenge.score);
  const best = bests[challenge.mode];
  $('challenge-best').textContent = best ? `Best ${challengeUnitText(challenge.mode, best.best_score)}` : 'First run';
}

function renderSummary() {
  const box = $('challenge-summary');
  box.replaceChildren();
  box.classList.toggle('hidden', !lastRun);
  if (!lastRun) return;
  const run = lastRun;
  const head = make('div', 'summary-head');
  head.append(make('span', 'kicker kicker-c', `${CHALLENGES[run.mode].name} - run over`));
  if (run.newBest) head.append(make('span', 'best-badge', 'New best'));
  const stats = make('div', 'summary-stats');
  for (const [label, value] of [['Songs guessed', `${run.solved} / ${run.played}`], ['Points earned', run.points.toLocaleString()],
    ['Your best', bests[run.mode] ? challengeUnitText(run.mode, bests[run.mode].best_score) : '-']]) {
    const stat = make('div', 'stat');
    stat.append(make('p', 'stat-label', label), make('p', 'stat-value tabular', value));
    stats.append(stat);
  }
  const actions = make('div', 'summary-actions');
  const again = make('button', 'btn btn-primary', 'Play again');
  again.type = 'button';
  again.addEventListener('click', () => startChallenge(run.mode));
  const games = make('button', 'btn btn-secondary', 'All games');
  games.type = 'button';
  games.addEventListener('click', () => { lastRun = null; renderSummary(); switchTab('games'); });
  actions.append(again, games);
  box.append(head, make('p', 'summary-score tabular', challengeUnitText(run.mode, run.score)),
    make('p', 'small', CHALLENGE_END_REASONS[run.reason] || ''), stats, actions);
  box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function renderChallengeCards() {
  $('challenge-cards').replaceChildren(...Object.entries(CHALLENGES).map(([mode, rules]) => {
    const card = make('button', 'card challenge-card');
    card.type = 'button';
    card.dataset.tone = rules.tone;
    const best = bests[mode];
    const icon = make('span', 'challenge-icon', rules.icon);
    icon.setAttribute('aria-hidden', 'true');
    card.append(icon, make('h4', '', rules.name), make('p', '', rules.short),
      make('span', `challenge-best${best ? ' has-best' : ''}`, best ? `Best ${challengeUnitText(mode, best.best_score)}` : 'No runs yet'));
    card.addEventListener('click', () => startChallenge(mode));
    return card;
  }));
}

function buildWaves() {
  document.querySelectorAll('.wave').forEach(wave => {
    const middle = wave.dataset.wave === 'middle';
    wave.replaceChildren(...Array.from({ length: 54 }, (_, index) => {
      const bar = document.createElement('i');
      bar.style.height = `${22 + Math.abs(Math.sin(index * 0.9) * Math.cos(index * 0.37)) * 78}%`;
      if (middle ? index >= 25 && index < 34 : index < 9) bar.className = 'on';
      return bar;
    }));
  });
}

async function canaryShuffle() {
  const button = $('canary-shuffle');
  const out = $('canary-shuffle-result');
  button.disabled = true;
  out.textContent = 'Picking a song...';
  try {
    const song = await canary.randomSong();
    const facts = [song.era && `Era: ${song.era}`, song.category].filter(Boolean).join(' · ');
    const link = make('a', 'link-btn is-p', 'Listen on Canary ↗');
    link.href = song.pageUrl; link.target = '_blank'; link.rel = 'noopener noreferrer';
    out.replaceChildren(make('strong', '', song.title), facts ? ` (${facts}) ` : ' ', link);
  } catch (error) {
    out.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

// ------------------------------------------------------------ folders

function useFolder(result) {
  if (!result) return;
  if (challenge) finishChallenge('left');
  folder = result;
  game.setTracks(result.tracks);
  player.stop();
  resetPlayButton();
  resetCover();
  roundLog = [];
  const restored = game.restore(load(ROUND_KEY, null));
  if (!restored) game.nextRound();
  persist();
  renderGame();
  renderFolderSettings();
  switchTab('play');
  if (!result.tracks.length) {
    $('welcome-status').textContent = `No audio files were found in "${result.name}". Choose a folder that contains songs.`;
    return;
  }
  $('welcome-status').textContent = '';
  showFeedback(restored
    ? `Loaded ${result.tracks.length.toLocaleString()} songs. Resumed your unfinished round.`
    : `Loaded ${result.tracks.length.toLocaleString()} songs. Press PLAY to hear the first snippet.`, true);
}

async function chooseFolder() {
  $('welcome-status').textContent = '';
  if (library.canRememberFolder) {
    try {
      const result = await library.pickWithDirectoryPicker();
      if (result) { remembered = null; $('reopen-folder').classList.add('hidden'); useFolder(result); }
      return;
    } catch (error) {
      if (error.message !== 'unsupported') { $('welcome-status').textContent = `Could not open that folder: ${error.message}`; return; }
    }
  }
  $('folder-input').value = '';
  $('folder-input').click();
}

async function reopenRemembered() {
  if (!remembered) return;
  try {
    useFolder(await library.openRemembered(remembered.handle));
    $('reopen-folder').classList.add('hidden');
  } catch (error) {
    $('welcome-status').textContent = `${error.message || 'Could not reopen that folder.'} Choose it again instead.`;
  }
}

async function forgetFolder() {
  await library.forgetFolder();
  if (challenge) finishChallenge('left');
  remembered = null;
  folder = null;
  player.stop();
  resetPlayButton();
  game.setTracks([]);
  game.current = null;
  $('reopen-folder').classList.add('hidden');
  renderGame();
  renderFolderSettings();
}

// ------------------------------------------------------------ wiring

function wire() {
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
  document.querySelectorAll('[data-action="choose-folder"]').forEach(button => button.addEventListener('click', chooseFolder));
  $('folder-input').addEventListener('change', event => useFolder(library.tracksFromFileList(event.target.files)));
  $('reopen-folder').addEventListener('click', reopenRemembered);
  $('play-btn').addEventListener('click', () => playSegment('snippet'));
  $('submit-btn').addEventListener('click', submitGuess);
  $('skip-btn').addEventListener('click', skipAttempt);
  $('reroll-btn').addEventListener('click', reroll);
  $('next-round-btn').addEventListener('click', () => startNewRound());
  $('guess-input').addEventListener('input', handleTyping);
  $('guess-input').addEventListener('keydown', handleGuessKey);
  $('guess-input').addEventListener('blur', () => setTimeout(hideSuggestions, 120));
  $('mode-select').addEventListener('change', event => {
    if (game.setMode(event.target.value)) { prefs.mode = game.mode; savePrefs(); startNewRound('New round started.'); }
  });
  $('difficulty-select').addEventListener('change', event => {
    if (game.setDifficulty(event.target.value)) { prefs.difficulty = game.difficulty; savePrefs(); startNewRound('New round started.'); }
  });
  $('volume-control').value = String(prefs.volume);
  $('volume-value').textContent = `${prefs.volume}%`;
  $('volume-control').addEventListener('input', event => {
    prefs.volume = Number(event.target.value);
    $('volume-value').textContent = `${prefs.volume}%`;
    player.setVolume(prefs.volume / 100);
    savePrefs();
  });
  $('canary-toggle').checked = prefs.canary;
  $('canary-toggle').addEventListener('change', event => { prefs.canary = event.target.checked; savePrefs(); });
  $('forget-folder').addEventListener('click', forgetFolder);
  $('reset-stats').addEventListener('click', () => {
    if (!window.confirm('Reset all stats and achievements saved in this browser? This cannot be undone.')) return;
    game.stats = sanitizeStats(null);
    game.session = { score: 0, correct: 0, wrong: 0, rounds: 0 };
    persist();
    renderStats();
    renderGame();
  });
  document.addEventListener('keydown', event => {
    if (!(event.ctrlKey || event.metaKey) || $('game').classList.contains('hidden')) return;
    if (event.code === 'Space') { event.preventDefault(); if (!$('play-btn').disabled) playSegment('snippet'); }
    else if (event.key === 'Enter') {
      event.preventDefault();
      if (game.gameOver) startNewRound(); else if (!$('skip-btn').disabled) skipAttempt();
    }
  });
  document.querySelectorAll('[data-mode]').forEach(card => card.addEventListener('click', () => startGameMode(card.dataset.mode)));
  $('challenge-quit').addEventListener('click', () => finishChallenge('quit'));
  $('canary-shuffle').addEventListener('click', canaryShuffle);
  renderChallengeCards();
  buildWaves();
  $('snippet-eq').replaceChildren(...Array.from({ length: 18 }, () => document.createElement('i')));
}

async function start() {
  wire();
  switchTab('play');
  renderGame();
  remembered = await library.rememberedFolder();
  if (remembered) {
    if (!remembered.needsClick) {
      try { useFolder(await library.openRemembered(remembered.handle)); return; } catch { /* fall through to the button */ }
    }
    $('reopen-name').textContent = `"${remembered.name}"`;
    $('reopen-folder').classList.remove('hidden');
  }
  renderFolderSettings();
}

start();
