# DOMOVOY PRD

Status: draft, 13 Nov 2026. Nothing here is built yet. This folder is the build spec; [plan.md](../plan.md) holds the shared contracts, [decisions.md](../decisions.md) the decisions, [open-items.md](../open-items.md) what is undecided.

## Goal

By 18:00 on 13 Nov 2026, show one complete job live in three minutes: Vladimir's real flat search produces a shortlist, he approves one flat, an agent holds a live voice conversation about it, and a viewing appears in his calendar.

**User:** Vladimir, a real renter looking for a flat in Prague. **Product:** an open-source Agent Skill for Claude Code, not a new app.

## Lanes

| Lane | Doc | Owner | Priority | Delivers |
| --- | --- | --- | --- | --- |
| Actor | [actor.md](actor.md) | Vladimir | P0 | Real listings from three portals with costs, published as pages in the Notion shortlist |
| Voice | [voice.md](voice.md) | Danila | P0 | Phone page, ElevenLabs agent, call API |
| Skill | [skill.md](skill.md) | Both | P0 | `SKILL.md` that runs the whole flow, calendar, receipt |
| PostHog | [posthog.md](posthog.md) | Danila | P1 | Rejection report, approved criteria change, rerank |

Each lane doc has the same sections: definition of done, diagram, details, decisions, open items.

## How it works

```mermaid
flowchart LR
  Pr[Search profile from Claude] --> A
  subgraph Actor
    A[Apify Actor: Sreality, Bezrealitky, iDNES] --> B[Featherless fee extraction]
    B --> C[Normalize, dedupe, filter, cost math]
  end
  C --> F[(Notion: DOMOVOY shortlist, one page per flat)]
  V((Vladimir)) -- moves flat to Interested --> F
  V -- "call about it" --> S[Claude Code + DOMOVOY skill]
  F --> S
  G[(Vladimir's Google Calendar)] -- free windows --> S
  subgraph Voice
    P[Phone page on Vercel] <--> EL[ElevenLabs agent]
  end
  S -- call_context --> P
  R((Danila as demo realtor)) <-- live voice --> P
  P -- call result --> S
  S -- Viewing booked + summary --> F
  S -- test event --> G
  S -. events .-> PH[(PostHog, P1)]
```

```mermaid
sequenceDiagram
  actor V as Vladimir
  participant N as Notion shortlist
  participant C as Claude Code (skill)
  participant Cal as Google Calendar
  participant S as Phone server (Vercel)
  participant P as Phone page
  participant E as ElevenLabs agent
  actor D as Danila (demo realtor)
  V->>N: Move flat to Interested
  V->>C: "Call about my Interested flat"
  C->>N: Read Interested page
  C->>Cal: Read free windows
  C->>S: POST /api/call (call_context)
  C->>N: Status = Calling
  S-->>P: Pending call
  P->>D: Incoming call + ringtone
  D->>P: Accept
  P->>S: GET /api/signed-url
  P->>E: Start session with dynamic variables
  E-->D: Live conversation
  E->>P: submit_call_result (client tool)
  P->>S: POST /api/result
  C->>S: GET /api/result/{property_id} (poll)
  C->>C: Recheck windows and budget
  C->>Cal: Create test event
  C->>N: Status = Viewing booked, append summary
```

## Interfaces between lanes

| From → To | Interface | Defined in |
| --- | --- | --- |
| Skill → Actor | Search profile as Actor input; Claude polls the Apify run | [actor.md](actor.md) |
| Actor → Notion | Pages keyed by `Property ID`, Actor-owned properties, body written once | [actor.md](actor.md), [plan.md](../plan.md#notion-shortlist) |
| Notion → Skill | `Status`, `Reason` properties; page with `Property ID` | [plan.md](../plan.md#notion-shortlist) |
| Skill → Voice | `POST /api/call` with `call_context` | [voice.md](voice.md), [plan.md](../plan.md#contracts) |
| Voice → Skill | `GET /api/result/{property_id}` returning `submit_call_result` | [voice.md](voice.md), [plan.md](../plan.md#contracts) |
| Skill → PostHog | Events with `property_id` | [posthog.md](posthog.md) |

Change a contract only in `plan.md`, and tell the other lane.

## Definition of done

The product is done when all of this is true on Vladimir's laptop, live:

- [ ] The Notion shortlist shows at least 3 real flats from Sreality, Bezrealitky and iDNES, each with source link, collection time, monthly total, upfront cash and unknowns.
- [ ] Vladimir moves one flat to Interested and tells Claude Code to call; nothing contacts anyone before that.
- [ ] The phone page rings, Danila answers, and the agent holds an unscripted English conversation about that flat.
- [ ] After the call, a test event at the agreed time is in Vladimir's calendar, the flat is in Viewing booked, and the Notion page has the call summary.
- [ ] The full flow fits in 1:30 and has been rehearsed twice in the venue.
- [ ] The repo README has run instructions and what was built today; the repo is public; the Vercel URL works.

P1, only after the above: the PostHog report and rerank in [posthog.md](posthog.md).

## Checkpoints

| Time | Must be true | Cut first if not |
| --- | --- | --- |
| 14:00 | Actor: real flats from at least Sreality in Notion. Voice: page rings and agent talks with a hand-written context. | In-call visuals |
| 16:00 | One full run end to end: Interested → call → Calendar event → Viewing booked. Bezrealitky in Notion. | PostHog, Gmail |
| 17:00 | Code freeze; all three portals in. Dry run in the hall. 60–90 s cut rehearsed. | Any new code |
| 17:30 | Repo checked for secrets, realtor contacts and personal config; repo public, links on the form. | — |
| 18:00 | Demo. | — |

## Out of scope

GitHub Issues or the Projects board as a DOMOVOY surface (the board is only our hackathon task tracker; the shortlist is Notion), Czech, negotiation of alternative times or costs, more than one call, real phone calls, a custom dashboard, always-on monitoring, an agency product, Gmail unless time remains. Actor phase 2: PostHog events from the Actor. The katastr ownership check is a stretch for today, kept out of the scripted demo (#57). Full list in [plan.md](../plan.md#scope-and-ownership).
