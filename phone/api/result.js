import { allow, readBody } from '../lib/http.js';
import { setResult } from '../lib/store.js';

const REQUIRED = ['property_id', 'conversation_id'];

export default async function handler(req, res) {
  if (!allow(req, res, 'POST')) return;
  const result = readBody(req);
  const valid = result && typeof result === 'object' && !Array.isArray(result);
  const fields = REQUIRED.filter((key) => !valid || typeof result[key] !== 'string' || !result[key].trim());
  if (fields.length) return res.status(400).json({ error: 'missing_fields', fields });
  res.status(200).json({ ok: true, stored: await setResult(result) });
}
