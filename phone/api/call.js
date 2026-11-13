import { randomUUID } from 'node:crypto';
import { missingFields } from '../lib/context.js';
import { allow, authorized, readBody } from '../lib/http.js';
import { setPending } from '../lib/store.js';

export default async function handler(req, res) {
  if (!allow(req, res, 'POST')) return;
  if (!authorized(req, res)) return;
  const context = readBody(req);
  const fields = missingFields(context);
  if (fields.length) return res.status(400).json({ error: 'missing_fields', fields });
  await setPending(context, randomUUID());
  res.status(200).json({ ok: true, property_id: context.property_id });
}
