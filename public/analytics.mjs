export function track(event, properties = {}) {
  fetch('/api/analytics', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Dashboard': '1' },
    body: JSON.stringify({ event, properties: { surface: 'web', ...properties } }),
    signal: AbortSignal.timeout(3000), keepalive: true,
  }).catch(() => {});
}

const dialog = document.querySelector('#privacy');
const toggle = document.querySelector('#analytics-enabled');
const status = document.querySelector('#analytics-status');
let saving = false;

export function updateAnalytics(preference) {
  if (!preference || saving) return;
  toggle.checked = preference.enabled;
  toggle.disabled = false;
  status.textContent = preference.demo ? 'Demo mode: no usage events are sent.' : !preference.configured
    ? 'This build is not connected to PostHog. No usage events are sent.'
    : preference.enabled ? 'Anonymous usage events are enabled.' : 'Usage events are off on this device.';
}

document.querySelector('#privacy-open').addEventListener('click', () => dialog.showModal());
document.querySelector('#privacy-close').addEventListener('click', () => dialog.close());
toggle.addEventListener('change', async () => {
  const enabled = toggle.checked;
  saving = true;
  toggle.disabled = true;
  try {
    const response = await fetch('/api/analytics/preferences', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Dashboard': '1' },
      body: JSON.stringify({ enabled }), signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error();
    const preference = await response.json();
    saving = false;
    updateAnalytics(preference);
  } catch {
    toggle.checked = !enabled;
    status.textContent = 'Could not save this preference. Please try again.';
  } finally {
    saving = false;
    toggle.disabled = false;
  }
});
const url = new URL(window.location.href);
if (url.searchParams.has('privacy')) {
  dialog.showModal();
  // The tutorial also reads this parameter to avoid opening a second dialog.
}
