# Decisions

Two layers. The first table reconciles conflicts between the five supplied exports. The second records decisions Danila made on 13 Nov 2026 before the PRD; they override both the exports and the first table. Open questions live in [open-items.md](open-items.md).

## Reconciled export conflicts

| Conflict | Resolution |
| --- | --- |
| BytHlídač vs DOMOVOY | DOMOVOY; the 12 Nov locked decisions supersede the 9 Nov brief. |
| Standalone dashboard/VPS vs Agent Skill | Skill in Claude Code for the hackathon; the platform is longer-term context. |
| PSTN/Twilio vs browser voice | English WebRTC on one laptop. |
| Interested prepares a draft vs permits contact | Interested authorizes contact. |
| Draft-only success vs viewing | A booked test viewing in Calendar plus the board update is success. Drafts and prior results are fallbacks. |
| Next.js page vs standalone HTML | Waiting page plus the minimum server for secrets and relay, on Vercel. |
| Unknown/2–3-minute timing vs hard stop | Three minutes per the 13 Nov hub. |
| PostHog optional vs Lane 3 P0 | Core first; PostHog is P1. |
| Deferred Featherless eval vs assumed seed dataset | Eval stays deferred; use genuine current-run events. |
| PostHog as database vs listing store | PostHog for events only. |
| Rubric weights vs formula | C3 multiplier is 4: 5/5/4/3/3 totals 100. Weights are internal. |
| Example 2+kk/Vinohrady/30k vs real profile | Example only until Vladimir supplies his brief. |
| "No prebuilt code" vs reuse allowed | Record what was reused; confirm the rules. |
| Live gate vs previous-result fallback | A labeled prior result is degraded evidence and does not pass the live gate. |
| Immediate rerank vs measured improvement | Rerank proves application only. |

## Pre-PRD decisions, 13 Nov 2026

| Topic | Decision | Replaces |
| --- | --- | --- |
| Shortlist UI | GitHub Issues (one per flat) on a Projects board | Notion database |
| Workflow state | Board `Status` field only; no status labels | Notion `Status` |
| Statuses | Shortlisted, Not interested, Interested, Calling, Viewing booked, Not booked | Need info, Alternative proposed, Needs approval, Declined |
| Rejection reason | Board `Reason` text field, typed by Vladimir | Notion reason |
| Trigger | Vladimir moves the card, then tells Claude Code to call | Notion webhook or polling |
| Issue creation | Skill script run by Claude, deduped by `property_id` | Pipeline writes Notion |
| Calls per demo | Exactly one | — |
| Call outcomes | Happy path only: `booked` or `not_booked`; no negotiation | confirmed / alternative / declined / needs approval |
| Language | English only, everywhere; no Czech draft | Czech inquiry draft |
| Phone page hosting | Vercel for demo and submission link | Local for demo, Vercel for testing |
| Result relay | ElevenLabs client tool → page → Vercel server → Claude polls | Undecided |
| Demo laptop | Vladimir's | One unnamed laptop |
| Calendar | Vladimir's own | Same, now on his laptop |
| Demo realtor | Danila | Third person or role switch |
| Repo visibility | Private while building; public at 17:30 after checking issues hold no realtor contacts | Public |
| Extraction model | Featherless | LLM unspecified |
| PostHog | P1 after the core; signal is rejections with a reason | Lane 3 P0 |
| Agency lane | One spoken sentence at the close | Built agency view, 30 s |
| Gmail | Optional, only if time remains | Required, then probably not needed |
| Ringtone | mp3 cut from the referenced Nokia 3310 video | Same |
| Need info / investigation | Removed | Agent investigation on request |
