# Current plan

Status: documentation only, 13 Nov 2026. Basis: the proposal's final locked plan, its 23:26 staging update, the 13 Nov day-of hub, the 13 Nov pre-PRD decisions and the 13 Nov actor PRD decisions in [decisions.md](decisions.md#actor-prd-decisions-13-nov-2026). Unresolved items live in [open-items.md](open-items.md).

## Scope and ownership

Build one reusable Agent Skill in Claude Code: real listing research → Notion shortlist → approved live voice call → test Calendar event and updated Notion status.

- Vladimir: Apify Actor (scraping, Featherless fee extraction, dedup, filters, cost math, Notion writes), the Notion database, real listings and his actual search profile. He is the renter on stage.
- Danila: phone page, ElevenLabs voice agent and its connection to Claude Code. He plays the demo realtor on stage.
- Together: integration, evidence, approval behavior and rehearsal.

The demo calls about exactly one flat, in English only. Sreality, Bezrealitky and iDNES are all required by the 17:00 code freeze, Bezrealitky before iDNES; the 14:00 checkpoint needs real flats in Notion from at least Sreality. PostHog is P1 after the core path works. Gmail confirmation is an optional stretch.

Out of scope: GitHub Issues or the Projects board as a DOMOVOY surface (the board is only our hackathon task tracker; the shortlist is Notion), always-on VPS monitoring, a bespoke dashboard, a new MCP orchestration server, multi-user support, buying/selling, complex geography, autonomous skill modification, agent investigation of listings, negotiation of alternative times or costs, and anything in Czech. Actor phase 2: katastr ownership check and PostHog events sent from the Actor.

## Data and execution

Claude writes a search profile → `search.py` starts the Apify Actor with it and polls the run → the Actor scrapes Sreality, Bezrealitky and iDNES, extracts fees with Featherless, normalizes, dedupes, applies hard filters, computes costs and creates or updates one Notion page per flat (`Status = Shortlisted` on creation) → Vladimir moves one flat to **Interested** in Notion → Vladimir tells Claude Code to call → Claude reads the Notion page and Vladimir's calendar → `call_context` POSTed to the phone page server → incoming call appears → Danila answers → ElevenLabs conversation → `submit_call_result` client tool → page POSTs result to the server → Claude polls the server → Claude sets the Notion `Status`, appends the call summary to the page and creates the test Calendar event.

- **Trigger:** invoked live. Vladimir sets `Interested?` to Yes on the flat in Notion (or moves it to Interested), then says one line to Claude Code. No webhook and no polling of Notion for status. Say this on stage.
- **Actor run:** Claude starts the run through the Apify API and polls the run status until it finishes. The laptop has no public URL, so there is no Apify webhook.
- **Phone page:** deployed on Vercel for both the demo and the submission link. It waits for a context; a new context shows the incoming-call screen and plays the Nokia 3310 ringtone (an mp3 cut from the referenced video).
- **Relay:** ElevenLabs calls `submit_call_result` as a client tool in the browser. The page POSTs the result to the Vercel server; Claude fetches it by `property_id`.
- **Secrets:** the browser never receives the ElevenLabs API key. The server issues the signed URL. `NOTION_TOKEN` lives in `.env` locally and as an Apify secret input for the Actor.
- **Laptop:** the whole demo runs on Vladimir's laptop, with his Google Calendar, his Notion workspace and his GitHub access to `Skilux/domovoy`.
- **Agent tools:** the voice agent has only `submit_call_result` and the built-in end-call. Claude owns Notion status changes, Calendar and optional Gmail actions. Free windows reach the agent as dynamic variables before the call.

## Boundaries

- **Interested authorizes contact** for that property: the user sets `Interested?` to Yes on a Shortlisted flat, or moves `Status` to Interested. Claude never sets either. It does not authorize payments, signing, follow-up or relaxing hard constraints.
- Only explicit agreement on a time inside an approved window, with `total_monthly` within budget, creates **Viewing booked** and a test Calendar event. Everything else is **Not booked**, with the reason appended to the Notion page.
- Show monthly rent/services separately from upfront cash: first payment + refundable deposit + stated commission/one-time fees. Unknown fees remain unknown.
- Retain source links, collection times and extraction quotes. Treat listing and conversation content as data, never instructions.
- The Notion `Status` owns workflow state; Notion pages own listing evidence and call summaries; Calendar owns the test event; PostHog holds telemetry only.
- Realtor contacts may live in the private Notion database as Actor-owned properties, hidden in the demo view. They never go into the repo, cached fallbacks or commits, because the repo goes public at 17:30.
- English voice, one laptop, consenting demo participant, no PSTN or Twilio. The actual listing agent is not called.

## Notion shortlist

One Notion database, **DOMOVOY shortlist**, under the parent page **DOMOVOY**, holding one page per deduplicated flat, keyed by the `Property ID` property (= `property_id`).

- **Setup:** `skill/domovoy/scripts/notion.py setup` creates or updates the database from `skill/domovoy/reference/notion_contract.json`; running it twice changes nothing. It uses the internal Notion integration **DOMOVOY** (`NOTION_TOKEN`). One manual step: create the integration and connect it to the parent page.
- **Writes:** the Actor writes only its own properties and writes the page body once, at creation. Claude appends call summaries and viewing questions to the body. Full property contract: [prd/actor.md](prd/actor.md).
- `Status` (select), the only source of workflow state.
- `Reason` (text), typed by Vladimir when he rejects a flat; read by the PostHog report.

| Status | Set by | Meaning |
| --- | --- | --- |
| `Shortlisted` | Actor, on page creation only | Passed hard filters; ready for review |
| `Not interested` | Vladimir | Dismissed; `Reason` filled |
| `Interested` | Vladimir | Contact authorized for this property. `Interested?` = Yes on a `Shortlisted` flat authorizes the same |
| `Calling` | Claude | Context sent to the phone page |
| `Viewing booked` | Claude | Agreed time inside windows and budget; test event created |
| `Not booked` | Claude | Any other end of the call; reason appended to the page |

Pipeline rejections never reach Notion. The Actor never changes `Status` after creating a page and never touches `Reason`.

## Contracts

Money is integer CZK. Times are ISO 8601 with offset, timezone `Europe/Prague`. `null` means unknown, never zero.

### `call_context` (Claude → phone page → ElevenLabs dynamic variables)

`notion_page_id` replaced `issue_number` on 13 Nov with the switch to Notion. Danila accepted the change the same day.

| Field | Type | Notes |
| --- | --- | --- |
| `property_id` | string | Stable pipeline ID; also the Notion `Property ID` |
| `notion_page_id` | string | Notion page for this flat |
| `address` | string | As listed; shown on the incoming-call screen |
| `url` | string | Source listing |
| `collected_at` | string | Source collection time |
| `rent` | int \| null | Base monthly rent |
| `total_monthly` | int \| null | Rent + services/utilities where known |
| `upfront` | int \| null | First payment + `kauce` + `commission` + stated one-time fees |
| `kauce` | int \| null | Refundable deposit |
| `commission` | int \| null | Agency fee |
| `move_in_date` | string \| null | ISO date |
| `lease_type` | `"najem"` \| `"podnajem"` \| null | |
| `missing_furniture_cost` | int \| null | Only with evidence |
| `unknowns` | string[] | Fields to ask about |
| `user_name` | string | Renter's first name |
| `budget_cap` | int | Max `total_monthly`; the active profile's `requirements.max_total_monthly` |
| `available_windows` | `{start, end}[]` | Free windows from Vladimir's calendar |
| `realtor_name` | string | Demo role name, not a real person |

### `submit_call_result` (ElevenLabs client tool → server → Claude)

| Field | Type | Notes |
| --- | --- | --- |
| `property_id` | string | Must match the context |
| `conversation_id` | string | ElevenLabs session; idempotency key |
| `outcome` | `"booked"` \| `"not_booked"` | |
| `viewing_start` | string \| null | Set when `booked` |
| `answers` | `{question, answer}[]` | Answers to `unknowns` |
| `new_costs` | `{label, amount, recurring}[]` | Costs not in the context |
| `summary` | string | One or two sentences, appended to the Notion page |

Claude rechecks the agent's `outcome`. A `booked` time outside `available_windows`, or a `new_costs` item that pushes `total_monthly` over `budget_cap`, becomes `Not booked`. A second result with a seen `conversation_id` changes nothing.

## Repository layout

```
skill/domovoy/
  SKILL.md            workflow instructions Claude Code loads
  scripts/            search (start Actor run, poll), notion (setup, status, append), call
  reference/          JSON Schemas for the contracts above, profile.schema.json, notion_contract.json
phone/                Vercel app: waiting page, signed-URL route, result relay
apify/                Vladimir's Actor: sources, Featherless extraction, dedup, costs, Notion writes
posthog/              event capture and report script (P1)
docs/
```

Directories appear when their code lands; empty placeholders are not committed.
