export function typeText(el, text, stepMs = 90) {
  let shown = 0;
  el.textContent = '';
  const timer = setInterval(() => {
    shown += 1;
    el.textContent = text.slice(0, shown);
    if (shown >= text.length) clearInterval(timer);
  }, stepMs);
  return () => clearInterval(timer);
}
