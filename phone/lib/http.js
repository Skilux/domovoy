import { timingSafeEqual } from 'node:crypto';

export function allow(req, res, method) {
  if (req.method === method) return true;
  res.setHeader('Allow', method);
  res.status(405).json({ error: 'method_not_allowed' });
  return false;
}

export function authorized(req, res, headerName = 'x-domovoy-secret', envName = 'DOMOVOY_SECRET') {
  const expected = Buffer.from(process.env[envName] || '');
  const header = req.headers[headerName];
  const given = Buffer.from(typeof header === 'string' ? header : '');
  if (expected.length && given.length === expected.length && timingSafeEqual(given, expected)) return true;
  res.status(401).json({ error: 'unauthorized' });
  return false;
}

export function readBody(req) {
  try {
    const body = req.body;
    return typeof body === 'string' ? JSON.parse(body) : body;
  } catch {
    return null;
  }
}
