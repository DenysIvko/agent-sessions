export const SOURCE_META = {
  codex: { label: 'Codex', icon: 'code', color: '#7DD3C2', bg: 'rgb(125 211 194 / 12%)' },
  claude: { label: 'Claude Code', icon: 'claude', color: '#E5A188', bg: 'rgb(229 161 136 / 12%)' },
  antigravity: { label: 'Antigravity', icon: 'code', color: '#A8B4FF', bg: 'rgb(168 180 255 / 12%)' },
};

export const STATUS_META = {
  running: { label: 'Running', color: '#5B9DFF', bg: 'rgb(91 157 255 / 14%)', icon: 'spinner' },
  unread: { label: 'Unread', color: '#C084FC', bg: 'rgb(192 132 252 / 15%)', icon: 'mail' },
  completed: { label: 'Completed', color: '#3DD68C', bg: 'rgb(61 214 140 / 13%)', icon: 'check' },
  stopped: { label: 'Stopped', color: '#FF9F43', bg: 'rgb(255 159 67 / 14%)', icon: 'stop' },
  read: { label: 'Read', color: '#B4BAC5', bg: 'rgb(180 186 197 / 12%)', icon: 'eye' },
  failed: { label: 'Failed', color: '#FF8585', bg: 'rgb(255 133 133 / 14%)', icon: 'alert' },
  inactive: { label: 'Inactive', color: '#B4BAC5', bg: 'rgb(180 186 197 / 12%)', icon: 'pause' },
};

export function sessionStatus(session) {
  return session.running ? 'running'
    : { completed: 'completed', interrupted: 'stopped', failed: 'failed' }[session.status] || 'inactive';
}

export function matchesStatus(session, status) {
  if (status === 'all') return true;
  if (status === 'unread') return session.unread;
  if (status === 'read') return !session.running && session.unread === false;
  return sessionStatus(session) === status;
}

export function statusCounts(sessions) {
  return Object.fromEntries(Object.keys(STATUS_META)
    .map(status => [status, sessions.filter(s => matchesStatus(s, status)).length]));
}

export function dashboardSessions(data, favoritesOnly = false) {
  const favorites = data.favoriteSessions || [];
  if (favoritesOnly) return favorites;
  return [...new Map([...favorites, ...data.sessions].map(session => [session.id, session])).values()];
}

export function projectGroup(session) {
  return { id: session.projectId, name: session.project };
}

export function visibleSessions(sessions, { query = '', project = '', kind = '', source = '', status = 'all' } = {}) {
  const search = query.trim().toLocaleLowerCase();
  const rank = s => s.running ? 0 : s.unread ? 1 : 2;
  return sessions.filter(s => (!project || projectGroup(s).id === project) && (!kind || s.kind === kind)
    && (!source || s.source === source)
    && matchesStatus(s, status)
    && (!search || [s.title, s.project, s.branch, s.id, s.model, SOURCE_META[s.source]?.label].join(' ').toLocaleLowerCase().includes(search)))
    .sort((a, b) => rank(a) - rank(b) || b.activityAt - a.activityAt || a.id.localeCompare(b.id));
}

export function formatDuration(seconds) {
  const sec = Math.max(0, Math.floor(seconds));
  if (sec < 60) return `${sec}s`;
  const minutes = Math.floor(sec / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function runDuration(session, now) {
  const end = session.running ? now : session.endedAt;
  if (session.startedAt == null || end == null || end < session.startedAt) return '';
  const prefix = session.running ? 'for' : session.status === 'completed' ? 'in' : 'after';
  return `${prefix} ${formatDuration(end - session.startedAt)}`;
}
