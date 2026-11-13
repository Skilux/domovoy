import { readFileSync } from 'node:fs';

const API = 'https://api.elevenlabs.io/v1/convai';
const DEFAULT_PHONE_URL = 'https://domovoy-phone.vercel.app';

const flags = new Set(process.argv.slice(2));
const dryRun = flags.has('--dry-run');
const withAllowlist = flags.has('--allowlist');

const read = (name) => readFileSync(new URL(name, import.meta.url), 'utf8');
const { agent, tools } = JSON.parse(read('./agent.json'));
const agentId = (process.env.ELEVENLABS_AGENT_ID || '').trim();

function phoneHost() {
  const raw = (process.env.PHONE_URL || DEFAULT_PHONE_URL).trim();
  return new URL(raw.includes('://') ? raw : `https://${raw}`).host;
}

agent.conversation_config.agent.prompt.prompt = read('./prompt.md').trim();
agent.conversation_config.agent.prompt.tool_ids = tools.map((tool) => `<id of ${tool.name}>`);
agent.platform_settings.auth.allowlist = withAllowlist ? [{ hostname: phoneHost() }] : [];
if (agentId) agent.conversation_config.tts = { speed: agent.conversation_config.tts.speed };

if (dryRun) {
  const request = agentId ? 'PATCH /v1/convai/agents/{agent_id}' : 'POST /v1/convai/agents/create';
  console.log(JSON.stringify({ request, tools: tools.map((tool) => ({ tool_config: tool })), agent }, null, 2));
  process.exit(0);
}

const apiKey = process.env.ELEVENLABS_API_KEY;
if (!apiKey) {
  console.error('ELEVENLABS_API_KEY is not set. Load it first: set -a; . ~/.config/domovoy/.env; set +a');
  process.exit(1);
}

async function call(method, path, body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { 'xi-api-key': apiKey, 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) {
    console.error(`${method} ${path} failed with ${res.status}: ${text}`);
    process.exit(1);
  }
  return text ? JSON.parse(text) : {};
}

async function syncTool(tool) {
  const found = await call('GET', `/tools?search=${encodeURIComponent(tool.name)}&page_size=100`);
  const existing = (found.tools || []).find((t) => t.tool_config?.name === tool.name && t.tool_config?.type === 'client');
  if (existing) {
    await call('PATCH', `/tools/${existing.id}`, { tool_config: tool });
    return existing.id;
  }
  return (await call('POST', '/tools', { tool_config: tool })).id;
}

const toolIds = [];
for (const tool of tools) toolIds.push(await syncTool(tool));
agent.conversation_config.agent.prompt.tool_ids = toolIds;

const saved = agentId
  ? await call('PATCH', `/agents/${agentId}`, agent)
  : await call('POST', '/agents/create', agent);

console.log(saved.agent_id || agentId);
