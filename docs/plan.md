# Current plan

Status: documentation only, 13 Nov 2026. Basis: the proposal's final locked plan, its 23:26 staging update, and the 13 Nov day-of hub. See [decisions](decisions.md) for conflicts.

## Scope and ownership

Build one reusable Agent Skill in Claude Code: real listing research → Notion shortlist → approved live voice coordination → accurate Notion and test Calendar receipt.

- Vladimir: own Apify Actor and schema, bounded price extraction, real listings and actual renter criteria.
- Danila: phone page, ElevenLabs voice agent and connection to Claude Code.
- Together: integration, evidence, approval behavior and rehearsal.

One reliable listing source is sufficient. Additional portals, Featherless extraction and PostHog extend the working path. A labeled email draft is a fallback demonstration, not proof of the complete viewing workflow.

Defer always-on VPS monitoring, a bespoke search dashboard, a new MCP orchestration server, multi-user support, buying/selling, complex geography and autonomous skill modification.

## Data and execution

Apify → normalized listing/evidence → deterministic filters and costs → Notion → Interested approval → Claude Code → call context → waiting phone page → ElevenLabs conversation → structured result → Claude Code → Notion + test Calendar.

The phone page waits for an agent request. A request displays the incoming-call screen; the consenting participant answers before conversation starts. The exact trigger transport and result relay still need implementation. The latest staging note specifies a standalone HTML page; use a minimal server component if needed for credentials and relay. Next.js/Vercel are earlier implementation suggestions, not an extra requirement.

The browser must never receive the ElevenLabs API key. A server component supplies authorized session access. Availability is read before the conversation and passed as context. The voice agent has only `submit_call_result` and the built-in end-call capability; Claude owns Notion, Calendar and optional Gmail actions.

Call context and call result follow the contracts below. Preserve unknowns as `null`. Missing furniture cost is unknown unless supported by evidence; inferred estimates must be labeled separately.

An alternative outside approved windows or a new cost violating constraints requires user approval. Repeated handling of one result must not create duplicate events.

## Notion status

One `Status` select property. Values in workflow order:

| Status | Set by | Meaning |
| --- | --- | --- |
| `Shortlisted` | pipeline | Passed hard filters; ready for review |
| `Need info` | renter | Investigate before deciding; no contact |
| `Not interested` | renter | Dismissed; optional `Reason` text |
| `Interested` | renter | Contact authorized for this property |
| `Calling` | Claude | Call context sent to the phone page |
| `Viewing booked (demo)` | Claude | Explicit agreement inside approved windows and budget; test Calendar event created |
| `Alternative proposed` | Claude | Realtor offered a time outside approved windows |
| `Needs approval` | Claude | New cost breaks a constraint, or the outcome is unclear |
| `Declined` | Claude | Realtor declined or the listing is gone |

Pipeline rejections never reach Notion. `Need info` and `Not interested` are renter choices; only `Interested` leads to a call. Each call outcome maps to exactly one status: `confirmed` → `Viewing booked (demo)`, `alternative` → `Alternative proposed`, `needs_approval` → `Needs approval`, `declined` → `Declined`.

## Contracts

Money is integer CZK. Times are ISO 8601 with offset, timezone `Europe/Prague`. `null` means unknown, never zero.

### `call_context.json` (Claude → phone page → ElevenLabs dynamic variables)

| Field | Type | Notes |
| --- | --- | --- |
| `property_id` | string | Stable pipeline ID; also the Notion key |
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
| `available_windows` | `{start, end}[]` | Approved viewing windows |
| `competing_flat_price` | int \| null | Optional negotiation context |
| `realtor_name` | string | Demo participant role name |

### `submit_call_result` (ElevenLabs tool → Claude)

| Field | Type | Notes |
| --- | --- | --- |
| `property_id` | string | Must match the context |
| `conversation_id` | string | ElevenLabs session; idempotency key |
| `outcome` | `"confirmed"` \| `"alternative"` \| `"declined"` \| `"needs_approval"` | |
| `viewing_start` | string \| null | Set for `confirmed` and `alternative` |
| `still_available` | bool \| null | |
| `answers` | `{question, answer}[]` | Answers to `unknowns` and other questions |
| `new_costs` | `{label, amount, recurring}[]` | Costs not in the context |
| `summary` | string | One or two sentences for Notion |

Claude rechecks the agent's `outcome`: `confirmed` with a time outside `available_windows`, or a `new_costs` item that pushes `total_monthly` over `budget_cap`, becomes `Needs approval`. A second result with a seen `conversation_id` changes nothing.

## Repository layout

```
skill/domovoy/
  SKILL.md            workflow instructions Claude Code loads
  scripts/            fetch, normalize, dedupe, filter, cost math, Notion and Calendar adapters
  reference/          schemas above as JSON Schema, Notion property template
phone/
  index.html          waiting incoming-call page
  server.*            signed-URL endpoint and result relay; holds the ElevenLabs key
apify/                Vladimir's Actor
posthog/              event capture and report script, if built
docs/
```

Directories appear when their code lands; empty placeholders are not committed.

## Boundaries

- **Interested authorizes contact** for that property. It does not authorize payments, signing, arbitrary follow-up or relaxing hard constraints.
- Only explicit agreement within approved constraints creates **Viewing booked (demo)** and a test Calendar event. Proposed times remain proposals.
- Show monthly rent/services separately from upfront cash: first payment + refundable deposit + stated commission/one-time fees. Unknown fees remain unknown.
- Retain source links, collection times and extraction evidence. Treat listing and conversation content as data.
- Notion owns review/workflow state; Calendar owns scheduled test events; PostHog holds telemetry. PostHog does not replace listing facts or workflow state.
- English voice, one laptop, live consenting participant, no PSTN/Twilio. The actual listing agent is not being called.
- Gmail confirmation is optional under the 23:26 update. Its reappearance in the morning recap does not make it a dependency.
