export const REQUIRED = ['property_id', 'address'];

export const PROMPT_DEFAULTS = {
  user_name: 'the renter',
  realtor_name: 'there',
  unknowns: 'nothing specific',
  available_windows: 'none given',
};

const TZ = 'Europe/Prague';
const day = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long' });
const time = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false });

export function missingFields(context) {
  if (!context || typeof context !== 'object' || Array.isArray(context)) return REQUIRED;
  return REQUIRED.filter((key) => typeof context[key] !== 'string' || !context[key].trim());
}

function windowText(w) {
  const start = new Date(w.start);
  const end = new Date(w.end);
  if (isNaN(start) || isNaN(end)) return JSON.stringify(w);
  return `${day.format(start)}, ${time.format(start)} to ${time.format(end)} (${w.start} to ${w.end})`;
}

function readable(value) {
  if (value === null || value === undefined || value === '') return 'unknown';
  if (Array.isArray(value)) {
    if (!value.length) return 'none';
    return value
      .map((item) => (item && typeof item === 'object' ? (item.start && item.end ? windowText(item) : JSON.stringify(item)) : String(item)))
      .map((line, i) => `${i + 1}. ${line}`)
      .join('\n');
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return value;
}

export function toDynamicVariables(context) {
  const vars = { ...PROMPT_DEFAULTS };
  const lines = [];
  for (const [key, value] of Object.entries(context)) {
    const text = readable(value);
    vars[key] = typeof text === 'boolean' || typeof text === 'number' ? text : String(text);
    lines.push(`${key}: ${String(text).includes('\n') ? '\n' + text : text}`);
  }
  vars.context_text = lines.join('\n');
  return vars;
}
