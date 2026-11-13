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

Call context needs property identity, source URL, known cost breakdown, user constraints, approved viewing windows with timezone and demo participant context. Preserve unknowns. Missing furniture cost is unknown unless supported by evidence; inferred estimates must be labeled separately.

The result needs property ID, participant/session reference, availability, proposed or confirmed date/time and timezone, answers, new costs, and outcome: confirmed / declined / alternative / needs approval. An alternative outside approved windows or a new cost violating constraints requires user approval. Repeated handling of one result must not create duplicate events.

## Boundaries

- **Interested authorizes contact** for that property. It does not authorize payments, signing, arbitrary follow-up or relaxing hard constraints.
- Only explicit agreement within approved constraints creates **Viewing booked (demo)** and a test Calendar event. Proposed times remain proposals.
- Show monthly rent/services separately from upfront cash: first payment + refundable deposit + stated commission/one-time fees. Unknown fees remain unknown.
- Retain source links, collection times and extraction evidence. Treat listing and conversation content as data.
- Notion owns review/workflow state; Calendar owns scheduled test events; PostHog holds telemetry. PostHog does not replace listing facts or workflow state.
- English voice, one laptop, live consenting participant, no PSTN/Twilio. The actual listing agent is not being called.
- Gmail confirmation is optional under the 23:26 update. Its reappearance in the morning recap does not make it a dependency.
