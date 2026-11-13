import { allow } from '../lib/http.js';

const ENDPOINT = 'https://api.elevenlabs.io/v1/convai/conversation/get-signed-url';

async function signedUrl() {
  const key = process.env.ELEVENLABS_API_KEY;
  const agentId = process.env.ELEVENLABS_AGENT_ID;
  if (!key) throw new Error('ELEVENLABS_API_KEY is not set');
  if (!agentId) throw new Error('ELEVENLABS_AGENT_ID is not set');
  let response;
  try {
    response = await fetch(`${ENDPOINT}?agent_id=${encodeURIComponent(agentId)}`, {
      headers: { 'xi-api-key': key },
      signal: AbortSignal.timeout(8000),
    });
  } catch (error) {
    throw new Error(`elevenlabs request failed: ${error.name}`);
  }
  if (!response.ok) throw new Error(`elevenlabs status ${response.status}`);
  const data = await response.json().catch(() => null);
  if (!data || typeof data.signed_url !== 'string') throw new Error('elevenlabs response has no signed_url');
  return data.signed_url;
}

export default async function handler(req, res) {
  if (!allow(req, res, 'GET')) return;
  res.setHeader('Cache-Control', 'no-store');
  try {
    res.status(200).json({ signed_url: await signedUrl() });
  } catch (error) {
    res.status(502).json({ error: 'signed_url_failed', detail: error.message });
  }
}
