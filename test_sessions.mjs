import assert from 'node:assert/strict';
import test from 'node:test';
import { dashboardSessions, projectGroup, sessionStatus, statusCounts, visibleSessions, runDuration } from './public/sessions.mjs';

const base = { title: 'Build dashboard', project: 'Same name', projectId: 'project-a',
  branch: 'feat/design', kind: 'Chat', model: 'model-a', activityAt: 100, running: false, unread: false };
const sessions = [
  { ...base, id: 'done', status: 'completed' },
  { ...base, id: 'unread', status: 'completed', unread: true, activityAt: 90 },
  { ...base, id: 'running', status: 'inProgress', running: true, unread: true, activityAt: 80 },
  { ...base, id: 'stopped', status: 'interrupted', activityAt: 110 },
  { ...base, id: 'failed', status: 'failed', activityAt: 120 },
  { ...base, id: 'stale', status: 'inProgress', activityAt: 130 },
  { ...base, id: 'scheduled', projectId: 'project-b', status: null, kind: 'Scheduled', activityAt: 140 },
];

test('the default view retains favorites after midnight, without duplicating today or keeping unflagged history', () => {
  const old = { ...base, id: 'yesterday', favorite: true, activityAt: 1 };
  const today = { ...base, id: 'today', favorite: true };
  const ordinary = { ...base, id: 'ordinary' };
  const before = { sessions: [today, ordinary], favoriteSessions: [old, today] };
  assert.deepEqual(new Set(dashboardSessions(before).map(s => s.id)), new Set(['yesterday', 'today', 'ordinary']));
  assert.equal(dashboardSessions(before).length, 3);
  const after = { sessions: [], favoriteSessions: [old, today] };
  assert.deepEqual(dashboardSessions(after).map(s => s.id), ['yesterday', 'today']);
  assert.deepEqual(dashboardSessions(before, true).map(s => s.id), ['yesterday', 'today']);
  assert.deepEqual(dashboardSessions({ sessions: [], favoriteSessions: [today] }).map(s => s.id), ['today']);
});

test('default shows every status, with running first, then unread, then latest activity', () => {
  const order = sessions.map(s => s.id);
  assert.deepEqual(visibleSessions(sessions).map(s => s.id),
    ['running', 'unread', 'scheduled', 'stale', 'failed', 'stopped', 'done']);
  assert.deepEqual(sessions.map(s => s.id), order);
  assert.equal(sessionStatus(sessions.find(s => s.id === 'stale')), 'inactive');
});

test('overview and filters retain overlapping unread state and distinct failures', () => {
  assert.deepEqual(statusCounts(sessions), {
    running: 1, unread: 2, completed: 2, stopped: 1, read: 5, failed: 1, inactive: 2,
  });
  assert.deepEqual(visibleSessions(sessions, { status: 'unread' }).map(s => s.id), ['running', 'unread']);
  assert.deepEqual(visibleSessions(sessions, { status: 'stopped' }).map(s => s.id), ['stopped']);
  assert.deepEqual(visibleSessions(sessions, { status: 'failed' }).map(s => s.id), ['failed']);
  const afterRead = sessions.map(s => ({ ...s, unread: false }));
  assert.equal(visibleSessions(afterRead).length, sessions.length);
  assert.equal(statusCounts(afterRead).unread, 0);
});

test('project filters use IDs even for duplicate names; search covers branch, ID and model', () => {
  assert.deepEqual(visibleSessions(sessions, { project: 'project-b' }).map(s => s.id), ['scheduled']);
  assert.equal(visibleSessions(sessions, { query: ' FEAT/DESIGN ' }).length, 7);
  assert.deepEqual(visibleSessions(sessions, { query: 'SCHEDULED', kind: 'Scheduled' }).map(s => s.id), ['scheduled']);
  assert.equal(visibleSessions(sessions, { query: 'model-a', project: 'project-a', status: 'completed' }).length, 2);
  assert.equal(visibleSessions(sessions, { query: 'missing' }).length, 0);
});

test('projects keep their own identity without product-specific grouping', () => {
  const a = { ...base, project: 'Example API', projectId: 'api' };
  const b = { ...base, project: 'Example Web', projectId: 'web' };
  assert.deepEqual(projectGroup(a), { id: 'api', name: 'Example API' });
  assert.notEqual(projectGroup(a).id, projectGroup(b).id);
});

test('durations use recorded run times and never invent a missing completion time', () => {
  assert.equal(runDuration({ running: true, startedAt: 100 }, 185), 'for 1m');
  assert.equal(runDuration({ status: 'completed', startedAt: 100, endedAt: 3720 }, 9000), 'in 1h 0m');
  assert.equal(runDuration({ status: 'interrupted', startedAt: 100, endedAt: 103 }, 9000), 'after 3s');
  assert.equal(runDuration({ status: 'completed', startedAt: 100, activityAt: 200 }, 9000), '');
  assert.equal(runDuration({ status: 'inProgress', startedAt: 100 }, 9000), '');
  assert.equal(runDuration({ status: 'completed', startedAt: 200, endedAt: 100 }, 9000), '');
});

test('both sources remain visible, filter independently, and unknown read state is not read', () => {
  const mixed = [
    { ...base, id: 'same-id', source: 'codex', status: 'completed' },
    { ...base, id: 'claude:same-id', source: 'claude', status: 'completed', unread: null },
  ];
  assert.equal(visibleSessions(mixed).length, 2);
  assert.equal(visibleSessions(mixed, { source: 'claude' })[0].id, 'claude:same-id');
  assert.equal(visibleSessions(mixed, { source: 'codex', status: 'read' }).length, 1);
  assert.equal(visibleSessions(mixed, { source: 'claude', status: 'read' }).length, 0);
  assert.equal(visibleSessions(mixed, { query: 'Claude Code' }).length, 1);
  assert.equal(statusCounts(mixed).read, 1);
  assert.equal(statusCounts(mixed).unread, 0);
});
