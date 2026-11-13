# Demo and acceptance

Three-minute hard stop; also rehearse a 60–90 second cut. Times below are elapsed stage time. Event milestones are Prague time: demos 18:00, winners 19:45 on 13 Nov 2026. The demo runs on Vladimir's laptop; Vladimir is the renter, Danila is the demo realtor.

| Time | Action |
| --- | --- |
| 0:00–0:15 | Vladimir's actual problem; real requirements and listings |
| 0:15–1:45 | Notion shortlist → move one flat to Interested → "call about it" → live browser call → Calendar event and Notion update to Viewing booked |
| 1:45–2:45 | If ready: PostHog report on rejection reasons → Vladimir says yes → visible rerank |
| 2:45–3:00 | "Install the skill in your own agent", one sentence on agencies, repository and demo links |

The spoken script, beat by beat, is [demo-script.md](demo-script.md).

If PostHog is not ready, the core gets its minute. Never rush past the receipt.

## Required gates

- [ ] Skill loads in Claude Code on Vladimir's laptop and executes the workflow.
- [ ] Sreality, Bezrealitky and iDNES work through the Apify Actor; each displayed property has source and collection time. Cached fallback is labeled and holds no realtor contacts.
- [ ] Costs and hard filters retain evidence and unknowns; criteria are Vladimir's, confirmed by him.
- [ ] Interested authorizes contact; no contact occurs before the flat is moved to Interested.
- [ ] Live English WebRTC conversation works with Danila as the labeled demo realtor. No claim of a telephone call or real viewing secured.
- [ ] The happy path is rehearsed: one call ends in Viewing booked, with the test event in Vladimir's calendar and the call summary on the Notion page.
- [ ] Full and short demos rehearsed with venue audio and network; nothing needed from the audience.

If voice fails onstage, show the last successful call's Notion summary and Calendar event, say they are prior results, then go to PostHog if it works. This is a transparent fallback, not a pass for the live gate. No prerecorded video.

## Internal scoring

The judge export proposes weights of 25/25/20/15/15 for real user, working result, nontechnical usability, agent/tool quality and clarity. These are team weights, not official rules. For scores C1–C5 from 0 to 5:

`total / 100 = 5*C1 + 5*C2 + 4*C3 + 3*C4 + 3*C5`

The original table gives C3 a multiplier of 5, which totals 105. Gate failures remain visible regardless of score. The [original rubric](archive/2026-11-13-notion/02-judge-critic-how-domovoy-will-be-judged.md) has the judge questions and checkpoint tables; its Czech-draft and negotiation references are superseded, and its Notion details yield to [plan.md](plan.md#notion-shortlist).

## Before submission (17:30)

- [ ] Root README: what it does, tested install/run instructions, what was built today, reused scaffolds.
- [ ] Vercel phone page URL works.
- [ ] The repo contains no secrets, realtor contacts or personal config; then switch `Skilux/domovoy` to public.
- [ ] Put the GitHub repo link and the Vercel URL on the submission form.
- [ ] Record verification and limitations; do not mark planned integrations as working.
