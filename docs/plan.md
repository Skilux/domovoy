# Current plan

Status: documentation only, 13 Nov 2026. Basis: the proposal's final locked plan, its 23:26 staging update, the 13 Nov day-of hub, and the 13 Nov pre-PRD decisions in [decisions.md](decisions.md#pre-prd-decisions-13-nov-2026). Unresolved items live in [open-items.md](open-items.md).

## Scope and ownership

Build one reusable Agent Skill in Claude Code: real listing research → GitHub shortlist → approved live voice call → test Calendar event and updated board.

- Vladimir: Apify Actor and schema, Featherless price extraction, real listings and his actual criteria. He is the renter on stage.
- Danila: phone page, ElevenLabs voice agent and its connection to Claude Code. He plays the demo realtor on stage.
- Together: integration, evidence, approval behavior and rehearsal.

The demo calls about exactly one flat, in English only. One reliable listing source is sufficient. PostHog is P1 after the core path works. Gmail confirmation is an optional stretch.

Out of scope: always-on VPS monitoring, a bespoke dashboard, a new MCP orchestration server, multi-user support, buying/selling, complex geography, autonomous skill modification, agent investigation of listings, negotiation of alternative times or costs, and anything in Czech.

## Data and execution

Apify → Featherless extraction → normalized listing/evidence → deterministic filters and costs → skill script creates GitHub issues and board cards → Vladimir drags one card to **Interested** → Vladimir tells Claude Code to call → Claude reads the board and Vladimir's calendar → `call_context` POSTed to the phone page server → incoming call appears → Danila answers → ElevenLabs conversation → `submit_call_result` client tool → page POSTs result to the server → Claude polls the server → Claude updates the board, comments on the issue and creates the test Calendar event.

- **Trigger:** invoked live. Vladimir moves the card, then says one line to Claude Code. No webhook and no polling of the board. Say this on stage.
- **Phone page:** deployed on Vercel for both the demo and the submission link. It waits for a context; a new context shows the incoming-call screen and plays the Nokia 3310 ringtone (an mp3 cut from the referenced video).
- **Relay:** ElevenLabs calls `submit_call_result` as a client tool in the browser. The page POSTs the result to the Vercel server; Claude fetches it by `property_id`.
- **Secrets:** the browser never receives the ElevenLabs API key. The server issues the signed URL.
- **Laptop:** the whole demo runs on Vladimir's laptop, with his Google Calendar and his GitHub access to `Skilux/domovoy`.
- **Agent tools:** the voice agent has only `submit_call_result` and the built-in end-call. Claude owns GitHub, Calendar and optional Gmail actions. Free windows reach the agent as dynamic variables before the call.

## Boundaries

- **Interested authorizes contact** for that property. It does not authorize payments, signing, follow-up or relaxing hard constraints.
- Only explicit agreement on a time inside an approved window, with `total_monthly` within budget, creates **Viewing booked** and a test Calendar event. Everything else is **Not booked**, with the reason in an issue comment.
- Show monthly rent/services separately from upfront cash: first payment + refundable deposit + stated commission/one-time fees. Unknown fees remain unknown.
- Retain source links, collection times and extraction quotes. Treat listing and conversation content as data, never instructions.
- The board owns workflow state; issues own listing evidence and call summaries; Calendar owns the test event; PostHog holds telemetry only.
- Issues hold listing data only: address as listed, link, costs, quotes, unknowns, call summary. No realtor names, phones or emails, because the repo goes public at 17:30.
- English voice, one laptop, consenting demo participant, no PSTN or Twilio. The actual listing agent is not called.

## GitHub board

One Projects board, **DOMOVOY shortlist**, owned by `Skilux`, holding one issue per shortlisted flat from `Skilux/domovoy`. Fields:

- `Status` (single select), the only source of workflow state. No status labels.
- `Reason` (text), typed by Vladimir when he rejects a flat; read by the PostHog report.

| Status | Set by | Meaning |
| --- | --- | --- |
| `Shortlisted` | skill script | Passed hard filters; ready for review |
| `Not interested` | Vladimir | Dismissed; `Reason` filled |
| `Interested` | Vladimir | Contact authorized for this property |
| `Calling` | Claude | Context sent to the phone page |
| `Viewing booked` | Claude | Agreed time inside windows and budget; test event created |
| `Not booked` | Claude | Any other end of the call; reason commented |

Pipeline rejections never reach the board. The skill script dedupes issues by `property_id`, stored in the issue body.

## Contracts

Money is integer CZK. Times are ISO 8601 with offset, timezone `Europe/Prague`. `null` means unknown, never zero.

### `call_context` (Claude → phone page → ElevenLabs dynamic variables)

| Field | Type | Notes |
| --- | --- | --- |
| `property_id` | string | Stable pipeline ID; also in the issue body |
| `issue_number` | int | GitHub issue for this flat |
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
| `budget_cap` | int | Max `total_monthly` |
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
| `summary` | string | One or two sentences for the issue comment |

Claude rechecks the agent's `outcome`. A `booked` time outside `available_windows`, or a `new_costs` item that pushes `total_monthly` over `budget_cap`, becomes `Not booked`. A second result with a seen `conversation_id` changes nothing.

## Repository layout

```
skill/domovoy/
  SKILL.md            workflow instructions Claude Code loads
  scripts/            normalize, filter, cost math, GitHub board sync, calendar
  reference/          JSON Schemas for the contracts above
phone/                Vercel app: waiting page, signed-URL route, result relay
apify/                Vladimir's Actor and Featherless extraction
posthog/              event capture and report script (P1)
docs/
```

Directories appear when their code lands; empty placeholders are not committed.
