import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import test from 'node:test';
import { identityColors } from './public/colors.mjs';

test('an ID keeps its color after a fresh process and unrelated renders', () => {
  const original = identityColors('session', 'fixed-session-id');
  assert.equal(original.accent, 'hsl(318 66% 74%)');
  for (let i = 0; i < 100; i++) identityColors('session', `another-session-${i}`);
  assert.deepEqual(identityColors('session', 'fixed-session-id'), original);
  const moduleUrl = new URL('./public/colors.mjs', import.meta.url).href;
  const fresh = execFileSync(process.execPath, ['--input-type=module', '-e',
    `import { identityColors } from ${JSON.stringify(moduleUrl)};
     console.log(JSON.stringify(identityColors('session', 'fixed-session-id')));`
  ], { encoding: 'utf8' });
  assert.deepEqual(JSON.parse(fresh), original);
});

test('project labels share a stable identity independently of session colors', () => {
  const project = identityColors('project', 'fixed-project-id');
  assert.equal(project.accent, 'hsl(27 74% 74%)');
  const sessions = ['session-a', 'session-b', 'session-c'];
  const before = new Map(sessions.map(id => [id, identityColors('session', id)]));
  for (const id of sessions.reverse()) {
    assert.deepEqual(identityColors('session', id), before.get(id));
    assert.deepEqual(identityColors('project', 'fixed-project-id'), project);
  }
  assert.notEqual(identityColors('session', 'fixed-project-id').accent, project.accent);
  assert.equal(new Set([...before.values()].map(c => c.accent)).size, sessions.length);
});

function luminance(css) {
  const [hue, saturation, lightness] = css.match(/[\d.]+/g).map(Number);
  const s = saturation / 100, l = lightness / 100;
  const a = s * Math.min(l, 1 - l);
  const linear = [0, 8, 4].map(n => {
    const k = (n + hue / 30) % 12;
    const channel = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

test('project label text remains readable across generated hues', () => {
  for (let i = 0; i < 2000; i++) {
    const { accent, ink, surface } = identityColors('project', `project-${i}`);
    const contrast = (luminance(ink) + 0.05) / (luminance(surface) + 0.05);
    assert.ok(contrast >= 4.5, `${ink} on ${surface}: ${contrast}`);
    assert.ok((luminance(accent) + 0.05) / (luminance(surface) + 0.05) >= 4.5);
  }
});
