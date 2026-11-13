import { allow, authorized } from '../../lib/http.js';
import { getResult } from '../../lib/store.js';

export default async function handler(req, res) {
  if (!allow(req, res, 'GET')) return;
  if (!authorized(req, res)) return;
  res.setHeader('Cache-Control', 'no-store');
  const result = await getResult(String(req.query.property_id));
  if (!result) return res.status(404).json({ error: 'not_found' });
  res.status(200).json(result);
}
