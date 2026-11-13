const USED_SHARE = 0.6;

function read(conversation, mode) {
  if (!conversation || !mode) return null;
  const out = mode === 'speaking';
  try {
    const data = out ? conversation.getOutputByteFrequencyData() : conversation.getInputByteFrequencyData();
    if (data && data.length && data.some((v) => v > 0)) return { data };
    const volume = out ? conversation.getOutputVolume() : conversation.getInputVolume();
    return volume > 0 ? { volume } : null;
  } catch {
    return null;
  }
}

export function createWave(el, count = 28) {
  const bars = Array.from({ length: count }, () => el.appendChild(document.createElement('i')));
  const heights = new Float32Array(count);
  const half = count / 2;
  let frame = 0;
  let getConversation = null;
  let mode = '';

  function target(level, i, now) {
    const idle = 0.1 + 0.05 * (1 + Math.sin(now / 320 + i * 0.5));
    if (!level) return idle;
    const band = Math.min(half - 1, Math.floor(Math.abs(i - (count - 1) / 2)));
    if (level.data) {
      const size = Math.max(1, Math.floor((level.data.length * USED_SHARE) / half));
      let sum = 0;
      for (let k = band * size; k < (band + 1) * size; k++) sum += level.data[k] || 0;
      return Math.max(idle, Math.min(1, Math.pow(sum / size / 255, 0.8) * 1.4));
    }
    const shape = (1 - band / half) * (0.7 + 0.3 * Math.sin(now / 90 + i * 1.7));
    return Math.max(idle, Math.min(1, level.volume * 4 * shape));
  }

  function draw(now) {
    const level = read(getConversation && getConversation(), mode);
    for (let i = 0; i < count; i++) {
      const goal = target(level, i, now);
      heights[i] += (goal - heights[i]) * (goal > heights[i] ? 0.5 : 0.15);
      bars[i].style.transform = `scaleY(${heights[i].toFixed(3)})`;
    }
    frame = requestAnimationFrame(draw);
  }

  function setMode(next) {
    mode = next === 'speaking' || next === 'listening' ? next : '';
    el.className = `wave ${mode}`.trim();
  }

  return {
    setMode,
    start(source) {
      cancelAnimationFrame(frame);
      getConversation = source;
      setMode('');
      frame = requestAnimationFrame(draw);
    },
    stop() {
      cancelAnimationFrame(frame);
      frame = 0;
      getConversation = null;
      setMode('');
    },
  };
}
