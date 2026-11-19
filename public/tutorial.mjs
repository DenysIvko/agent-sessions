import { track } from './analytics.mjs';
const dialog = document.querySelector('#tutorial');
const steps = [...dialog.querySelectorAll('[data-tour-step]')];
const back = document.querySelector('#tutorial-back');
const next = document.querySelector('#tutorial-next');
const help = document.querySelector('#help');
const storageKey = 'agent-sessions-tour-seen';
let step = 0;
let completed = false;

function render(direction) {
  steps.forEach((section, index) => { section.hidden = index !== step; });
  document.querySelector('#tutorial-progress').textContent = `${step + 1} of ${steps.length}`;
  back.disabled = step === 0;
  next.textContent = step === steps.length - 1 ? 'Done' : 'Next';
  steps[step].querySelector('h3').focus();
  track('tutorial_step_viewed', { step: step + 1, direction });
}

function open(entry) {
  step = 0;
  completed = false;
  dialog.showModal();
  track('tutorial_started', { entry });
  render('start');
}

help.addEventListener('click', () => open('help'));
document.querySelector('#tutorial-close').addEventListener('click', () => dialog.close());
back.addEventListener('click', () => { step--; render('back'); });
next.addEventListener('click', () => {
  if (step === steps.length - 1) { completed = true; dialog.close(); }
  else { step++; render('next'); }
});
dialog.addEventListener('close', () => {
  track(completed ? 'tutorial_completed' : 'tutorial_dismissed', completed ? {} : { step: step + 1 });
  try { localStorage.setItem(storageKey, '1'); } catch { /* The guide also works without browser storage. */ }
  help.focus();
});

const url = new URL(window.location.href);
const requested = url.searchParams.has('tutorial');
if (requested) {
  url.searchParams.delete('tutorial');
  history.replaceState(null, '', url);
}
let seen = false;
try { seen = localStorage.getItem(storageKey) === '1'; } catch { /* Storage may be disabled. */ }
if (!url.searchParams.has('privacy') && (requested || !seen)) open(requested ? 'link' : 'first_run');
