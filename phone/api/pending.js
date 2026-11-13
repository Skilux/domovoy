import { allow } from '../lib/http.js';
import { takePending } from '../lib/store.js';

export default async function handler(req, res) {
  if (!allow(req, res, 'GET')) return;
  res.setHeader('Cache-Control', 'no-store');
  res.status(200).json({ context: await takePending() });
}
