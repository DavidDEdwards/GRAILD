// Tiny test helper that works in a browser (open tests/index.html) and in Node
// (node web/tests/game-core.test.mjs), so no install is needed.
export const results = [];

export function test(name, body) {
  try {
    body();
    results.push({ name, ok: true });
  } catch (error) {
    results.push({ name, ok: false, error: error && error.message ? error.message : String(error) });
  }
}

function fail(message, actual, expected) {
  throw new Error(`${message}\n  actual:   ${JSON.stringify(actual)}\n  expected: ${JSON.stringify(expected)}`);
}

export const assert = {
  ok(value, message = 'expected a truthy value') { if (!value) fail(message, value, true); },
  equal(actual, expected, message = 'values differ') { if (actual !== expected) fail(message, actual, expected); },
  notEqual(actual, expected, message = 'values should differ') { if (actual === expected) fail(message, actual, `not ${expected}`); },
  deepEqual(actual, expected, message = 'values differ') {
    if (JSON.stringify(actual) !== JSON.stringify(expected)) fail(message, actual, expected);
  },
};

export function report() {
  const failed = results.filter(result => !result.ok);
  const lines = results.map(result => `${result.ok ? 'PASS' : 'FAIL'}  ${result.name}${result.ok ? '' : `\n      ${result.error}`}`);
  lines.push(`\n${results.length - failed.length} passed, ${failed.length} failed`);
  return { text: lines.join('\n'), failed: failed.length };
}
