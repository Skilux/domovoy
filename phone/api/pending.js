import { allow, authorized } from '../lib/http.js';
import { takePending } from '../lib/store.js';

export default async function handler(req, res) {
  if (!allow(req, res, 'GET')) return;
  if (!authorized(req, res, 'x-domovoy-receiver', 'DOMOVOY_RECEIVER_KEY')) return;
  res.setHeader('Cache-Control', 'no-store');
  const pending = await takePending();
  res.status(200).json({ context: pending?.context ?? null, call_token: pending?.callToken ?? null });
}
