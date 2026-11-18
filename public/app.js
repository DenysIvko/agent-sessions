import { identityColors } from './colors.mjs';
import './tutorial.mjs';
import { SOURCE_META, STATUS_META, dashboardSessions, projectGroup, sessionStatus, statusCounts, visibleSessions, formatDuration, runDuration } from './sessions.mjs';

const $ = selector => document.querySelector(selector);
const refreshInterval = 3000;
let data = { sessions: [] };
let statusFilter = 'all';
let projectFilter = '';
let sourceFilter = '';
let favoritesOnly = false;
let requestInFlight = false;
let nextRefresh = Date.now();
let toastTimer;
const archiving = new Set();
const savingFavorites = new Set();

function currentSessions() {
  return dashboardSessions(data, favoritesOnly);
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('csd-icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(svg.namespaceURI, 'use');
  use.setAttribute('href', `#icon-${name}`);
  svg.append(use);
  return svg;
}

function setColors(node, color, bg) {
  node.style.setProperty('--c', color);
  node.style.setProperty('--bg', bg);
}

function renderSources() {
  for (const [key, meta] of [['', { label: 'All sources', icon: 'code', color: '#E8EAEE', bg: 'rgb(232 234 238 / 10%)' }], ...Object.entries(SOURCE_META)]) {
    let button = $(`#sources [data-source="${key}"]`);
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.className = 'csd-chip';
      button.dataset.source = key;
      button.title = key ? `Filter sessions from ${meta.label}` : 'Show sessions from every source';
      setColors(button, meta.color, meta.bg);
      const count = document.createElement('span');
      count.className = 'csd-chip-count';
      button.append(icon(meta.icon), document.createTextNode(meta.label), count);
      $('#sources').append(button);
    }
    const count = key ? currentSessions().filter(s => s.source === key).length : currentSessions().length;
    button.querySelector('.csd-chip-count').textContent = count;
    button.classList.toggle('is-active', sourceFilter === key);
    button.setAttribute('aria-pressed', String(sourceFilter === key));
  }
}

function renderOverview(counts) {
  for (const [key, meta] of Object.entries(STATUS_META)) {
    let tile = $(`#tiles [data-filter="${key}"]`);
    if (!tile) {
      tile = $('#tile-template').content.firstElementChild.cloneNode(true);
      tile.dataset.filter = key;
      tile.title = `Filter by ${meta.label.toLowerCase()}; click again to clear`;
      setColors(tile, meta.color, meta.bg);
      tile.querySelector('.csd-tile-icon').append(icon(meta.icon));
      tile.querySelector('.csd-tile-label').textContent = meta.label;
      $('#tiles').append(tile);
    }
    tile.hidden = ['failed', 'inactive'].includes(key) && !counts[key] && statusFilter !== key;
    tile.querySelector('.csd-tile-num').textContent = counts[key];
    tile.querySelector('.csd-tile-icon').classList.toggle('is-spinning', key === 'running' && counts.running > 0);
    tile.querySelector('.csd-tile-flag').hidden = statusFilter !== key;
    tile.classList.toggle('is-active', statusFilter === key);
    tile.setAttribute('aria-pressed', String(statusFilter === key));
  }
  const segments = ['running', 'completed', 'stopped', 'failed', 'inactive']
    .filter(key => counts[key] || !['failed', 'inactive'].includes(key));
  const labels = [];
  $('#distribution').replaceChildren();
  $('#legend').replaceChildren();
  for (const key of segments) {
    const { label, color } = STATUS_META[key];
    const pct = currentSessions().length ? counts[key] / currentSessions().length * 100 : 0;
    const text = `${label} ${Math.round(pct)}%`;
    labels.push(text);
    if (pct) {
      const segment = document.createElement('div');
      segment.className = 'csd-dist-seg';
      segment.style.width = `${pct}%`;
      segment.style.backgroundColor = color;
      $('#distribution').append(segment);
    }
    const item = document.createElement('span');
    const swatch = document.createElement('i');
    swatch.className = 'csd-swatch';
    swatch.style.backgroundColor = color;
    item.append(swatch, document.createTextNode(text));
    $('#legend').append(item);
  }
  $('#distribution').setAttribute('aria-label', labels.join(', '));
}

function syncProjects() {
  const projects = new Map();
  for (const session of currentSessions()) {
    const group = projectGroup(session);
    const project = projects.get(group.id) || { name: group.name, count: 0 };
    project.count++;
    projects.set(group.id, project);
  }
  if (!projects.has(projectFilter)) projectFilter = '';
  const entries = [['', { name: 'All projects', count: currentSessions().length }],
    ...[...projects].sort((a, b) => a[1].name.localeCompare(b[1].name) || a[0].localeCompare(b[0]))];
  const container = $('#projects');
  const signature = JSON.stringify(entries);
  if (container.dataset.signature !== signature) {
    const focused = container.contains(document.activeElement) ? document.activeElement.dataset.project : null;
    container.replaceChildren(...entries.map(([id, project]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'csd-chip';
      button.dataset.project = id;
      button.title = id ? `Filter project: ${project.name} (${id})` : 'Show sessions from every project';
      const colors = identityColors('project', id);
      setColors(button, id ? colors.accent : '#E8EAEE', id ? colors.surface : 'rgb(232 234 238 / 10%)');
      const dot = document.createElement('span');
      dot.className = 'csd-chip-dot';
      dot.setAttribute('aria-hidden', 'true');
      const count = document.createElement('span');
      count.className = 'csd-chip-count';
      count.textContent = project.count;
      button.append(dot, document.createTextNode(project.name), count);
      return button;
    }));
    container.dataset.signature = signature;
    if (focused !== null) container.querySelector(`[data-project="${CSS.escape(focused)}"]`)?.focus({ preventScroll: true });
  }
  for (const button of container.children) {
    const active = button.dataset.project === projectFilter;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  }
  return new Set(currentSessions().map(session => session.projectId)).size;
}

function updateCard(node, session, now) {
  const status = sessionStatus(session);
  const meta = STATUS_META[status];
  const source = SOURCE_META[session.source || 'codex'];
  node.dataset.id = session.id;
  node.dataset.source = session.source;
  node.style.setProperty('--source-color', source.color);
  node.style.setProperty('--source-bg', source.bg);
  for (const link of node.querySelectorAll('[data-open]')) link.href = session.url || '#';
  const sourceBadge = node.querySelector('.csd-source');
  setColors(sourceBadge, source.color, source.bg);
  sourceBadge.querySelector('.source-name').textContent = source.label;
  if (sourceBadge.dataset.source !== session.source) {
    sourceBadge.querySelector('.source-icon').replaceChildren(icon(source.icon));
    sourceBadge.dataset.source = session.source;
  }
  const action = session.url ? `Open in ${source.label}` : `Copy ${source.label} resume command`;
  node.querySelector('.open-label').textContent = action;
  node.querySelector('.csd-open').title = session.url && session.source === 'claude' && !session.sessionId?.startsWith('local_')
    ? 'Open this terminal conversation in the Claude Code desktop app' : action;
  const archive = node.querySelector('.csd-archive');
  archive.disabled = archiving.has(session.id);
  archive.querySelector('span').textContent = archiving.has(session.id) ? 'Archiving...' : 'Archive';
  archive.title = session.running || session.agents > 0 ? 'Hide from Agent Sessions while work continues'
    : 'Hide from Agent Sessions; source archive is attempted where supported';
  archive.setAttribute('aria-label', `Archive ${session.title} in Agent Sessions`);
  const favorite = node.querySelector('.csd-favorite');
  favorite.disabled = savingFavorites.has(session.id);
  favorite.setAttribute('aria-pressed', String(Boolean(session.favorite)));
  favorite.title = session.favorite ? 'Remove from favorites' : 'Keep in favorites across days';
  favorite.setAttribute('aria-label', `${session.favorite ? 'Unfavorite' : 'Favorite'} ${session.title}`);
  node.classList.toggle('is-running', session.running);
  node.classList.toggle('is-unread', session.unread);
  node.classList.toggle('is-read', !session.running && session.unread === false);
  const sessionColors = identityColors('session', session.id);
  for (const [name, color] of Object.entries(sessionColors)) node.style.setProperty(`--session-${name}`, color);
  const project = node.querySelector('.csd-project');
  const projectColors = identityColors('project', session.projectId);
  setColors(project, projectColors.accent, projectColors.surface);
  project.style.color = projectColors.ink;
  project.title = `Project: ${session.project}`;
  node.querySelector('.project-name').textContent = session.project;
  node.querySelector('.branch-name').textContent = session.branch || '';
  node.querySelector('.csd-branch').hidden = !session.branch;
  node.querySelector('.csd-branch').title = session.branch || '';
  node.querySelector('.csd-progress').hidden = !session.running;
  setColors(node.querySelector('.csd-status'), meta.color, meta.bg);
  const statusIcon = node.querySelector('.csd-status-icon');
  if (statusIcon.dataset.icon !== meta.icon) {
    statusIcon.replaceChildren(icon(meta.icon));
    statusIcon.dataset.icon = meta.icon;
  }
  statusIcon.classList.toggle('is-spinning', session.running);
  node.querySelector('.csd-status-label').textContent = meta.label;
  const duration = runDuration(session, now);
  node.querySelector('.csd-status-dur').textContent = duration;
  node.querySelector('.csd-status-dur').hidden = !duration;
  node.querySelector('.csd-unread').hidden = !session.unread;
  node.querySelector('.csd-read').hidden = session.running || session.unread !== false;
  node.querySelector('h3').textContent = session.title;
  const displayId = (session.sessionId || session.id).replace(/^local_/, '');
  node.querySelector('.csd-id-swatch').textContent = displayId.slice(-2).toUpperCase();
  const id = node.querySelector('.session-id');
  id.textContent = `#${displayId.slice(0, 8)}...${displayId.slice(-4)}`;
  id.title = session.sessionId || session.id;
  const active = session.running ? 'Active now' : `Active ${formatDuration(now - session.activityAt)} ago`;
  const agents = session.agents ? ` · ${session.agents} agent${session.agents === 1 ? '' : 's'}` : '';
  node.querySelector('.activity').textContent = `${session.kind} · ${active}${agents}`;
  node.querySelector('.csd-card-link').setAttribute('aria-label', `${source.label}. ${session.title}. ${meta.label}${duration ? ` ${duration}` : ''}${session.unread ? ', unread' : ''}. Project ${session.project}. ${action}.`);
  node.title = [source.label, session.title, session.project, session.branch, session.model, action].filter(Boolean).join(' | ');
}

function renderCards(sessions, hasFilters) {
  const container = $('#board');
  const focused = container.contains(document.activeElement) ? document.activeElement.closest('.csd-card')?.dataset.id : null;
  const scroll = container.scrollTop;
  const existing = new Map([...container.querySelectorAll('.csd-card')].map(node => [node.dataset.id, node]));
  const now = data.error ? data.checkedAt : Date.now() / 1000;
  if (!sessions.length) {
    const empty = document.createElement('div');
    empty.className = 'csd-empty';
    const title = document.createElement('p');
    const emptySource = sourceFilter && !currentSessions().some(s => s.source === sourceFilter);
    title.textContent = favoritesOnly ? (hasFilters ? 'No favorites match these filters' : 'No favorites yet') : emptySource
      ? `No ${SOURCE_META[sourceFilter].label} sessions today or in Favorites`
      : hasFilters ? 'No sessions match these filters' : 'No sessions today or saved favorites';
    empty.append(icon(favoritesOnly ? 'star' : 'search'), title, document.createTextNode(favoritesOnly
      ? (hasFilters ? 'Clear your filters to see all favorites.' : 'Star a session to keep it here across days.') : emptySource
      ? `New ${SOURCE_META[sourceFilter].label} activity will appear automatically.` : hasFilters
      ? 'Clear your filters to see today\'s sessions and favorites.' : 'New activity will appear automatically.'));
    container.replaceChildren(empty);
  } else {
    container.querySelector('.csd-empty')?.remove();
    sessions.forEach((session, index) => {
      const node = existing.get(session.id) || $('#session-template').content.firstElementChild.cloneNode(true);
      updateCard(node, session, now);
      if (container.children[index] !== node) container.insertBefore(node, container.children[index] || null);
      existing.delete(session.id);
    });
    for (const node of existing.values()) node.remove();
  }
  container.scrollTop = scroll;
  if (focused && !container.contains(document.activeElement)) container.querySelector(`[data-id="${CSS.escape(focused)}"] [data-open]`)?.focus({ preventScroll: true });
}

function render() {
  const pool = currentSessions();
  const projectCount = syncProjects();
  renderSources();
  const counts = statusCounts(pool);
  renderOverview(counts);
  const filters = { query: $('#search').value, project: projectFilter, kind: $('#kind').value, source: sourceFilter, status: statusFilter };
  const hasFilters = Boolean(filters.query.trim() || filters.project || filters.kind || filters.source || filters.status !== 'all');
  const sessions = visibleSessions(pool, filters);
  $('#clear-filters').hidden = !hasFilters;
  $('#results').textContent = hasFilters ? `Showing ${sessions.length} of ${pool.length} ${favoritesOnly ? 'favorites' : 'sessions'}`
    : favoritesOnly ? `${pool.length} favorite${pool.length === 1 ? '' : 's'} across all days` : `${pool.length} sessions · Today + Favorites`;
  $('#favorites').classList.toggle('is-active', favoritesOnly);
  $('#favorites').setAttribute('aria-pressed', String(favoritesOnly));
  $('#favorite-count').textContent = (data.favoriteSessions || []).length;
  $('#scope-label').textContent = `${data.scope || 'This device'} · ${data.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone} · ${favoritesOnly ? 'Favorites across all days' : 'Today + Favorites'}`;
  $('#board').setAttribute('aria-label', favoritesOnly ? 'Favorite sessions across all days' : "Today's sessions and saved favorites");
  $('#board').classList.toggle('is-favorites', favoritesOnly);
  $('#board').setAttribute('aria-busy', 'false');
  renderCards(sessions, hasFilters);
  if (data.date) {
    const date = new Date(`${data.date}T12:00:00Z`).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', timeZone: data.timezone });
    $('#today').textContent = favoritesOnly ? `Favorites across all days · ${projectCount} project${projectCount === 1 ? '' : 's'} · archived hidden`
      : `Today, ${date} + saved favorites · ${pool.length} sessions across ${projectCount} projects · archived hidden`;
  }
  document.title = `${counts.running ? `(${counts.running} running) ` : ''}Agent Sessions`;
}

function setConnection(message, error = '') {
  $('#error').hidden = !error;
  $('#error').textContent = error;
  $('#connection').textContent = message;
  $('#connection-label').classList.toggle('is-error', Boolean(error));
  $('#refresh-ring').style.stroke = error ? '#FF9F43' : '#3DD68C';
}

function updateCountdown() {
  const remaining = Math.max(0, nextRefresh - Date.now());
  $('#countdown').textContent = requestInFlight ? 'Updating...' : `Refreshing in ${Math.max(1, Math.ceil(remaining / 1000))}s`;
  $('#refresh-ring').style.strokeDashoffset = String(50.27 * (1 - remaining / refreshInterval));
}

async function refresh() {
  if (requestInFlight) return;
  requestInFlight = true;
  nextRefresh = Date.now() + refreshInterval;
  updateCountdown();
  try {
    const response = await fetch('/api/sessions', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error('Could not connect to the local dashboard.');
    data = await response.json();
    render();
    setConnection(data.error ? 'Reconnecting' : 'Live', data.error || '');
    $('#updated').textContent = data.checkedAt ? `Updated ${new Date(data.checkedAt * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: data.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone })}` : 'Waiting for first update';
  } catch {
    setConnection('Reconnecting', 'Dashboard disconnected. Showing the last update. Reconnecting automatically.');
  } finally {
    requestInFlight = false;
    updateCountdown();
  }
}

$('#tiles').addEventListener('click', event => {
  const button = event.target.closest('[data-filter]');
  if (!button) return;
  statusFilter = statusFilter === button.dataset.filter ? 'all' : button.dataset.filter;
  render();
});
$('#sources').addEventListener('click', event => {
  const button = event.target.closest('[data-source]');
  if (!button) return;
  sourceFilter = sourceFilter === button.dataset.source ? '' : button.dataset.source;
  render();
});
$('#favorites').addEventListener('click', () => {
  favoritesOnly = !favoritesOnly;
  render();
});
$('#projects').addEventListener('click', event => {
  const button = event.target.closest('[data-project]');
  if (!button) return;
  projectFilter = projectFilter === button.dataset.project ? '' : button.dataset.project;
  render();
});
$('#clear-filters').addEventListener('click', () => {
  statusFilter = 'all';
  projectFilter = '';
  sourceFilter = '';
  $('#search').value = '';
  $('#kind').value = '';
  render();
  $('#search').focus();
});
$('#action-error button').addEventListener('click', () => { $('#action-error').hidden = true; });
$('#board').addEventListener('click', async event => {
  const card = event.target.closest('.csd-card');
  if (!card) return;
  const session = currentSessions().find(s => s.id === card.dataset.id);
  if (!session) return;
  const toast = $('#toast');
  if (event.target.closest('.csd-favorite')) {
    event.preventDefault();
    if (savingFavorites.has(session.id)) return;
    savingFavorites.add(session.id);
    render();
    try {
      const response = await fetch('/api/favorite', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Dashboard': '1' },
        body: JSON.stringify({ id: session.id, favorite: !session.favorite }), signal: AbortSignal.timeout(5000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save this favorite.');
      const updated = { ...session, favorite: result.favorite };
      data.sessions = data.sessions.map(s => s.id === session.id ? updated : s);
      data.favoriteSessions = (data.favoriteSessions || []).filter(s => s.id !== session.id);
      if (result.favorite) data.favoriteSessions.push(updated);
      toast.textContent = result.favorite ? 'Saved to Favorites. It will stay available across days.' : 'Removed from Favorites.';
      await refresh();
    } catch (error) {
      toast.textContent = error.name === 'TimeoutError' ? 'Favorite was not confirmed. Check the star after the next update.' : error.message;
    } finally {
      savingFavorites.delete(session.id);
      render();
      toast.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
    }
    return;
  }
  if (event.target.closest('.csd-archive')) {
    event.preventDefault();
    if (archiving.has(session.id)) return;
    $('#action-error').hidden = true;
    archiving.add(session.id);
    render();
    try {
      const response = await fetch('/api/archive', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Dashboard': '1' },
        body: JSON.stringify({ id: session.id }), signal: AbortSignal.timeout(30000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not archive this session.');
      toast.textContent = result.message;
      await refresh();
    } catch (error) {
      toast.textContent = error.name === 'TimeoutError' ? 'Local archive was not confirmed. Refresh before retrying.' : error.message;
      $('#action-error span').textContent = `${session.title}: ${toast.textContent}`;
      $('#action-error').hidden = false;
    } finally {
      archiving.delete(session.id);
      render();
      toast.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { toast.hidden = true; }, 12000);
    }
    return;
  }
  if (!event.target.closest('[data-open]')) return;
  if (!session.url) {
    event.preventDefault();
    try {
      await navigator.clipboard.writeText(session.resumeCommand);
      toast.textContent = `Resume command copied. Paste it in your terminal to open ${SOURCE_META[session.source].label}.`;
    } catch {
      window.prompt(`Copy this command to resume in ${SOURCE_META[session.source].label}:`, session.resumeCommand);
      toast.textContent = 'Paste the resume command in your terminal.';
    }
  } else {
    toast.textContent = `Opening "${session.title}" in ${SOURCE_META[session.source || 'codex'].label}...`;
  }
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 2200);
});
$('#board').addEventListener('keydown', event => {
  if (event.key === ' ' && event.target.matches('[role="button"]')) {
    event.preventDefault();
    event.target.click();
  }
});
$('#search').addEventListener('input', render);
$('#kind').addEventListener('change', render);
document.addEventListener('keydown', event => {
  if (event.key === '/' && !$('#tutorial').open && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    event.preventDefault();
    $('#search').focus();
  }
  if (event.key === 'Escape' && document.activeElement === $('#search')) {
    $('#search').value = '';
    render();
    $('#search').blur();
  }
});
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
setInterval(() => { if (Date.now() >= nextRefresh) refresh(); }, 250);
setInterval(updateCountdown, 250);
refresh();
