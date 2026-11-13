const TZ = 'Europe/Prague';
const COLORS = ['#2fd15a', '#ffd23f', '#ff5a5f', '#5aa2ff', '#ffffff', '#c77dff'];
const CONFETTI_MS = 2600;

export function calendarParts(iso) {
  const date = new Date(iso);
  if (!iso || isNaN(date)) return null;
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: TZ,
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type)?.value || '';
  return { month: get('month'), day: get('day'), weekday: get('weekday'), time: `${get('hour')}:${get('minute')}` };
}

export function renderCalendar(el, iso) {
  const parts = calendarParts(iso);
  el.hidden = !parts;
  if (!parts) return false;
  el.querySelector('.cal-month').textContent = parts.month;
  el.querySelector('.cal-day').textContent = parts.day;
  el.querySelector('.cal-sub').textContent = `${parts.weekday}, ${parts.time}`;
  return true;
}

export function confetti(host, count = 60) {
  const box = document.createElement('div');
  box.className = 'confetti';
  for (let i = 0; i < count; i++) {
    const piece = document.createElement('i');
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.background = COLORS[i % COLORS.length];
    piece.style.setProperty('--dx', `${(Math.random() * 8 - 4).toFixed(2)}em`);
    piece.style.setProperty('--turn', `${Math.round(Math.random() * 1080 - 540)}deg`);
    piece.style.animationDuration = `${(1.5 + Math.random()).toFixed(2)}s`;
    piece.style.animationDelay = `${(Math.random() * 0.4).toFixed(2)}s`;
    box.append(piece);
  }
  host.append(box);
  setTimeout(() => box.remove(), CONFETTI_MS);
}

export function smsBeep(ctx) {
  if (!ctx) return;
  try {
    if (ctx.state === 'suspended') ctx.resume();
    const unit = 0.06;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'square';
    osc.frequency.value = 1480;
    gain.gain.value = 0;
    osc.connect(gain);
    gain.connect(ctx.destination);
    let t = ctx.currentTime + 0.05;
    for (const group of [[1, 1, 1], [3, 3, 3], [1, 1, 1]]) {
      for (const length of group) {
        gain.gain.setValueAtTime(0.1, t);
        t += length * unit;
        gain.gain.setValueAtTime(0, t);
        t += unit;
      }
      t += 2 * unit;
    }
    osc.start();
    osc.stop(t);
  } catch {}
}
