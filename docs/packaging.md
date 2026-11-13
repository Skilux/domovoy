# Take it and run it

How another person sets DOMOVOY up, what it costs, and how to swap each service. Written 13 Nov 2026. Each claim says whether it was run, read from a pricing page, or estimated.

## Setup

1. Open `https://domovoy-phone.vercel.app/start` (there is a QR on the page) and copy the prompt into Claude Code, or run `claude "$(curl -fsSL https://domovoy-phone.vercel.app/prompt.txt)"`.
2. The agent clones the repo, links `skill/domovoy` into `~/.claude/skills/`, copies `config.example.json` to `config.json` and runs `python3 scripts/doctor.py check --json`.
3. You put each missing key into `~/.config/domovoy/.env` yourself (template: `.env.example`). The agent never reads that file.
4. `python3 scripts/notion.py setup` creates the Notion database. Copy the `data_source_id` it prints into `config.json`.
5. Deploy `phone/` to your own Vercel project with an Upstash Redis store and the env vars listed in `phone/README.md`. Create the voice agent with `node phone/agent/sync-agent.mjs`.
6. Run `apify push` in `apify/` and set `apify.actor_id` in `config.json` to your copy. The Actor reads its Notion and model keys from your Apify secrets, so the shared Actor cannot write to your Notion.
7. Open `<PHONE_URL>/?k=<DOMOVOY_RECEIVER_KEY>` once and click Ready. Connect a calendar tool to the agent.
8. Run the check again. With no FAIL, ask the agent to find a flat.

State on 13 Nov 2026: steps 1 to 4 and the check were run on Danila's machine. Steps 5 and 6 have no script yet and were done by hand for the demo. Nobody outside the team has run the whole flow.

### What `doctor.py check` verifies

Read-only: GET requests only. It prints PASS, FAIL, WARN or SKIP per row, one fix line per problem, and never a key.

| Row | Proves |
| --- | --- |
| `local.*` | Python 3.9+, `config.json` parses and has a profile, the env file is mode 600, the skill is linked |
| `notion.token`, `notion.schema` | The token works and the database has every property in `reference/notion_contract.json` |
| `apify.token`, `apify.actor` | The token works and the Actor is visible to the account |
| `featherless.key` | The key works, when it is in the local env file. The Actor's own copy lives on Apify and is not visible |
| `phone.url`, `phone.secret`, `phone.store` | The phone server answers, accepts the shared secret, and can read its store |
| `elevenlabs.key`, `elevenlabs.agent` | The key may use Agents and the agent id exists, when the key is in the local env file |
| `posthog.keys` | Optional. Never a FAIL |
| `calendar.access` | Always SKIP: only the agent can see its calendar tools |

## Prerequisites

| Need | Detail |
| --- | --- |
| Claude Code | A paid Claude plan or an API key |
| Local tools | git, Python 3.9+ (the skill scripts use the standard library only), Node 18+ for the phone deploy and the agent sync, the Apify CLI for `apify push` |
| Accounts with a free plan | Notion, Apify, ElevenLabs, Vercel, Upstash, PostHog (optional) |
| Paid account | Featherless, 25 USD per month, for fee extraction. Without a key the Actor still runs and leaves fees unknown |
| Calendar | Any calendar tool connected to the agent |

## Cost per 100 cases

Prices are from the public pricing pages, read on 13 Nov 2026. Quantities are estimates: no measured call length, token count or Apify compute is recorded in the repo yet.

### 100 flats researched

| Service | Quantity (estimate) | Unit price (pricing page) | USD |
| --- | --- | --- | --- |
| Apify compute | 0.33 compute units: about 1,200 s at 1 GB | 0.20 USD per compute unit, [apify.com/pricing](https://apify.com/pricing) | 0.07 |
| Apify proxy | 0 GB, the proxy is off in `input_schema.json` | 8 USD per GB | 0.00 |
| Featherless | 100 extraction calls | Flat 25 USD per month, [featherless.ai/pricing](https://featherless.ai/pricing) | 0.00 extra |
| Notion | about 300 requests | No API charge found | 0.00 |
| PostHog | 100 to 200 events | First 1,000,000 per month free, [posthog.com/pricing](https://posthog.com/pricing) | 0.00 |
| **Total** | | | **about 0.07**, plus the Featherless plan |

Assumptions: 105 portal requests at 0.6 s each (one Bezrealitky smoke run took 3.7 s for 6 requests, `apify/research/bezrealitky.md`), 100 extraction calls at 10 s with concurrency 1, 120 s of Notion writes at 3 requests per second. At 4 GB of memory the compute cost is about 0.26 USD. A second run on the same flats costs less, because extraction is cached.

### 100 voice calls

| Service | Quantity (estimate) | Unit price (pricing page) | USD |
| --- | --- | --- | --- |
| ElevenLabs Agents | 200 minutes, 2 minutes per call | 0.08 USD per extra minute, [elevenlabs.io/pricing/agents](https://elevenlabs.io/pricing/agents) | 16.00 |
| ElevenLabs LLM | about 2.5 million input tokens | Billed separately at the model's rate; rate for the configured model not confirmed | about 1.40 |
| Vercel functions | about 23,000 invocations | First 1,000,000 per month free on Hobby | 0.00 |
| Upstash Redis | about 23,000 commands | First 500,000 per month free, [upstash.com/pricing/redis](https://upstash.com/pricing/redis) | 0.00 |
| Notion, PostHog, Calendar | about 800 requests, 1,300 events | Inside the free limits | 0.00 |
| **Total** | | | **about 17** |

A call cannot exceed 300 s (`phone/agent/agent.json`), so 100 calls cost at most 40 USD in minutes.

### Free limits

| Service | Free per month | Enough for |
| --- | --- | --- |
| ElevenLabs | 15 agent minutes | 7 calls of 2 minutes |
| Apify | 5 USD of usage | About 25 compute units |
| PostHog | 1,000,000 events, 100,000 AI events | The whole loop |
| Upstash Redis | 500,000 commands | See the note below |
| Vercel Hobby | 1,000,000 function invocations | Personal, non-commercial use only |

A paired phone page polls `/api/pending` once per second. Left open with no calls, it uses the Upstash free limit in about 139 hours. Close the paired tab when you are not expecting a call.

## Swap a service

| Service | Interface today | To replace it | Effort |
| --- | --- | --- | --- |
| Shortlist (Notion), call command | The functions in the `call.py` docstring, named by `backend.module` in `config.json`. Two fakes in `skill/domovoy/tests/` use it | One Python file with `list_pages` or `list_flats` and `get_flat`, plus `set_status` and `append` | One small module, about 190 lines |
| Shortlist (Notion), other paths | `search.py` requires `notion.data_source_id`; `posthog/shortlist.py` calls Notion directly; the Actor has one sink, `apify/domovoy/notion/sink.py` | Change all three | Real work |
| Listing source | The `Source` protocol in `apify/domovoy/sources/base.py` and `register()` in `sources/__init__.py` | One class with `collect` and `normalize`, and the portal name added to `Portal` and to both `profile.schema.json` files | Real work by size: each existing source is about 500 lines |
| Extraction model | Any OpenAI-compatible endpoint; the model is the `llm.model` input. The Featherless host is a constant, `FEATHERLESS_BASE_URL` in `apify/domovoy/extraction/llm.py` | Another model on Featherless: one input value. Another provider: make that host an input | One value, or a small change |
| Voice provider | The skill uses two routes: `POST /api/call` and `GET /api/result/{property_id}`, with the `call_context` and `submit_call_result` contracts. `tests/fake_phone_server.py` implements them | A real phone provider: a server with those two routes, then set `PHONE_URL`. Another browser agent: replace the ElevenLabs calls in `phone/src/main.js`, `phone/api/signed-url.js` and `phone/agent/` | One value for the skill, real work for the page |
| Calendar | No code. `SKILL.md` tells the agent to read busy times and to create the event that `call.py` prints | Connect another calendar tool and set `calendar.calendar_id` | One config value |
| Analytics | Sending: `capture()` in `posthog/ph.py`. The improve loop in `posthog/loop.py` uses PostHog queries, flags, notebooks and annotations directly | Sending only: one function. The loop: a store module with five functions | Small for sending, real work for the loop |
| Phone store | `phone/lib/store.js` is the only file that knows Upstash Redis | Rewrite its five functions | One small module, 46 lines |

To use the kit for another job, for example booking a dentist, three files hold the domain: the search profile schema (`skill/domovoy/reference/profile.schema.json`), the voice agent prompt (`phone/agent/prompt.md`) and the Notion contract (`skill/domovoy/reference/notion_contract.json`).

## Not built

- A script that creates the Vercel project, the store and the voice agent in one step. `doctor.py` only checks.
- A demo mode with no accounts. The fake backend and the fake phone server exist in `skill/domovoy/tests/`, but nothing starts them for a user.
- Packaging as a Claude Code plugin.
