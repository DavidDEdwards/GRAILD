// Run in a browser: open http://localhost:8000/tests/ while serving web/.
// Or with Node 22+, if installed:  node web/tests/game-core.test.js
import { test, assert, report } from './harness.js';
import {
  ACHIEVEMENTS, DIFFICULTIES, Game, emptyStats, isAudioFile, normalizeSongTitle,
  pointsFor, randomStart, sanitizeStats, trackTitle,
} from '../js/game-core.js';

const tracks = ['Lucid Dreams.mp3', 'Rental (Session).flac', 'Bandit.m4a'].map(name => ({ key: name, name, title: trackTitle(name) }));

function newGame(options = {}) {
  let i = 0;
  const game = new Game({ random: () => [0, 0.5, 0.99][i++ % 3], ...options });
  game.setTracks(tracks);
  game.nextRound();
  return game;
}

test('title matching ignores case, spacing, underscores and version endings', () => {
  assert.equal(normalizeSongTitle('  Lucid_Dreams  '), 'lucid dreams');
  assert.equal(normalizeSongTitle('Rental (Session)'), 'rental');
  assert.equal(normalizeSongTitle('Rental [v2] (Demo)'), 'rental');
  assert.equal(normalizeSongTitle('Rental - Alt Version'), 'rental');
  assert.notEqual(normalizeSongTitle('Rental'), normalizeSongTitle('Rentals'));
});

test('audio files are recognised by extension or MIME type', () => {
  assert.ok(isAudioFile('song.MP3'));
  assert.ok(isAudioFile('song.unknown', 'audio/x-thing'));
  assert.ok(!isAudioFile('cover.jpg', 'image/jpeg'));
  assert.ok(!isAudioFile('._song.mp3'));
  assert.equal(trackTitle('a.b.mp3'), 'a.b');
});

test('points drop by 10 per attempt', () => {
  assert.equal(pointsFor(DIFFICULTIES.Easy, 0), 60);
  assert.equal(pointsFor(DIFFICULTIES.Hard, 2), 10);
});

test('a first-try correct guess scores, streaks and unlocks achievements', () => {
  const game = newGame({ difficulty: 'Hard' });
  const result = game.guess(game.current.title.toUpperCase());
  assert.equal(result.success, true);
  assert.equal(result.points, 30);
  const s = game.stats;
  assert.deepEqual([s.total_correct, s.total_points, s.current_streak, s.best_streak, s.songs_played], [1, 30, 1, 1, 1]);
  assert.deepEqual(s.counters, { first_try: 1, hard: 1 });
  assert.equal(Object.keys(s.grails).length, 1);
  const unlocked = result.newlyUnlocked.map(item => item.id).sort();
  assert.deepEqual(unlocked, ['correct_1', 'first_try_1', 'grails_1', 'hard_1']);
  assert.equal(game.guess('anything').ignored, true, 'no guesses after the round ends');
});

test('wrong guesses reveal more, and running out loses the round and the streak', () => {
  const game = newGame({ difficulty: 'Hard', stats: { ...emptyStats(), current_streak: 4, best_streak: 4 } });
  assert.equal(game.guess('nope').gameOver, false);
  assert.equal(game.attempt, 1);
  assert.equal(game.skip().gameOver, false);
  const last = game.guess('still wrong');
  assert.equal(last.gameOver, true);
  assert.equal(game.stats.current_streak, 0);
  assert.equal(game.stats.best_streak, 4);
  assert.equal(game.stats.total_wrong, 2);
  assert.equal(game.stats.songs_played, 1);
});

test('reroll changes song without touching stats', () => {
  const game = newGame();
  const before = game.current.key;
  game.skip();
  const result = game.reroll();
  assert.equal(result.changed, true);
  assert.notEqual(game.current.key, before);
  assert.equal(game.attempt, 0);
  assert.equal(game.stats.songs_played, 0);
});

test('random drop start leaves room for the longest preview and stays fixed for the round', () => {
  assert.equal(randomStart(100, 16, () => 1), 84);
  assert.equal(randomStart(5, 16, () => 0.7), 0);
  const game = newGame({ mode: 'random' });
  const first = game.snippetStart(200);
  assert.equal(game.snippetStart(200), first);
  assert.ok(first <= 200 - 16);
});

test('an unfinished round can be restored, a finished one cannot', () => {
  const game = newGame();
  game.skip();
  const saved = JSON.parse(JSON.stringify(game.snapshot()));
  const other = new Game();
  other.setTracks(tracks);
  assert.equal(other.restore(saved), true);
  assert.equal(other.current.key, game.current.key);
  assert.equal(other.attempt, 1);
  assert.equal(other.restore({ ...saved, gameOver: true }), false);
  assert.equal(other.restore({ ...saved, key: 'missing.mp3' }), false);
});

test('saved stats are cleaned up and the catalog matches the desktop app minus sign-in trophies', () => {
  const stats = sanitizeStats({ total_points: '50', best_streak: -3, counters: { hard: 2 }, grails: { a: {} } });
  assert.equal(stats.total_points, 50);
  assert.equal(stats.best_streak, 0);
  assert.equal(stats.counters.hard, 2);
  assert.equal(ACHIEVEMENTS.length, 48);
  assert.equal(new Set(ACHIEVEMENTS.map(item => item.id)).size, 48);
});

const outcome = report();
if (typeof document !== 'undefined') {
  document.getElementById('output').textContent = outcome.text;
  document.title = outcome.failed ? 'Tests FAILED' : 'Tests passed';
} else {
  console.log(outcome.text);
  if (outcome.failed) globalThis.process.exitCode = 1;
}
