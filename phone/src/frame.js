const FOLD_MS = 620;
const framed = window.parent !== window;
let closeTimer = null;
let foldTimer = null;

if (framed) document.documentElement.classList.add('framed');

function tellParent(open) {
  if (!framed) return;
  try {
    window.parent.postMessage({ type: 'domovoy-phone', open }, location.origin);
  } catch {}
}

export function syncFrame(phone) {
  const screen = phone.dataset.screen;
  const wasOpen = phone.dataset.open === 'yes';
  const open = screen === 'call' || (screen === 'result' && wasOpen);
  if (screen === 'result') phone.dataset.result = open ? 'wide' : 'slab';
  if (open === wasOpen) return;
  clearTimeout(closeTimer);
  clearTimeout(foldTimer);
  phone.classList.add('folding');
  foldTimer = setTimeout(() => phone.classList.remove('folding'), FOLD_MS + 200);
  if (open) {
    phone.dataset.open = 'yes';
    tellParent(true);
  } else {
    delete phone.dataset.open;
    closeTimer = setTimeout(() => tellParent(false), FOLD_MS + 150);
  }
}

export function startClock(el) {
  if (!el) return;
  const tick = () => {
    const now = new Date();
    el.textContent = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    setTimeout(tick, 60000 - (now.getSeconds() * 1000 + now.getMilliseconds()) + 50);
  };
  tick();
}
