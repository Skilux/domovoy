const TTL = 3600;
const RESULT_TTL = 86400;
const PENDING = 'domovoy:pending';
const resultKey = (propertyId) => `domovoy:result:${propertyId}`;
const seenKey = (conversationId) => `domovoy:seen:${conversationId}`;
const tokenKey = (token) => `domovoy:calltoken:${token}`;

async function redis(...command) {
  const url = process.env.KV_REST_API_URL;
  const token = process.env.KV_REST_API_TOKEN;
  if (!url || !token) throw new Error('store_not_configured');
  const response = await fetch(url, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(command),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.error) throw new Error(`store_failed_${response.status}`);
  return data.result;
}

const parse = (value) => (value === null || value === undefined ? null : JSON.parse(value));

export async function setPending(context, callToken) {
  await redis('DEL', resultKey(context.property_id));
  await redis('SET', tokenKey(callToken), '1', 'EX', TTL);
  await redis('SET', PENDING, JSON.stringify({ context, callToken }), 'EX', TTL);
}

export async function takePending() {
  return parse(await redis('GETDEL', PENDING));
}

export async function takeCallToken(callToken) {
  return (await redis('GETDEL', tokenKey(callToken))) !== null;
}

export async function setResult(result) {
  const first = await redis('SET', seenKey(result.conversation_id), '1', 'NX', 'EX', RESULT_TTL);
  if (first !== 'OK') return false;
  await redis('SET', resultKey(result.property_id), JSON.stringify(result), 'EX', RESULT_TTL);
  return true;
}

export async function getResult(propertyId) {
  return parse(await redis('GET', resultKey(propertyId)));
}
