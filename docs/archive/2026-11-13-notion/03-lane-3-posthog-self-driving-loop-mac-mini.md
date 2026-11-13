# 🦔 Lane 3 — PostHog Self-Driving Loop (Mac mini)

- **Source:** https://app.notion.com/p/41796f068f8981f7883cf219b543c480?pvs=204
- **Notion page ID:** 41796f068f8981f7883cf219b543c480
- **Last edited in Notion:** 2026-11-13T09:43:17.166Z
- **Exported:** 2026-11-13, from Danila's Notion via the Notion integration

---

<callout icon="🦔" color="orange_bg">
<b>Lane 3 — PostHog Self-Driving Loop (the Mac mini lane).</b>

Separate prize, separate judge: the PostHog guy in the room decides who gets the Mac mini. This lane does not need to win the overall rubric — it needs to show PostHog used as the brain, not as a logo.

Core idea, in one sentence: DOMOVOY sends every step as a structured signal to PostHog, a scout clusters the signals into one report, proposes one concrete fix, a human says yes or no, and PostHog measures whether the fix worked.

Parent page: DOMOVOY — Hackathon Proposal & Demo Flow. Event: AI Tinkerers Prague, “AI Agents for the Rest of Us”, Fri 13 Nov 2026. Demo: 3 minutes, hard stop. Rules: don’t cheat, build it all here. Submission form needs links: GitHub + demo / site.
</callout>

## 0. What we learned in the workshops (13 Nov morning)

### Featherless — \$25 credits

- Build with any open model. \$25 in credits, on us.
- Redeem: [https://featherless.ai/join/feather\_request\_pricing/AIT2026?amount\_usd=25](https://featherless.ai/join/feather_request_pricing/AIT2026?amount_usd=25) — code AIT2026.
- Create an account at [featherless.ai](http://featherless.ai), get the API key from the dashboard, choose a model from the catalog of 40K+ open models.
- Point the app at [https://api.featherless.ai/v1](https://api.featherless.ai/v1) with the API key — OpenAI-compatible, see the quickstart guide.
- Use for DOMOVOY: the bounded fee-extraction job (extract rent / kauce / energy / commission from listing text, with verbatim quotes + confidence). That confidence score becomes a PostHog signal (see S2).

### Apify — skill links (QRs decoded from the photo)

- Actor dev: [https://github.com/apify/agent-skills/tree/main/skills/apify-actor-development](https://github.com/apify/agent-skills/tree/main/skills/apify-actor-development)
- Orchestrator dev: [https://github.com/apify/awesome-skills/blob/main/skills/apify-orchestrator-actor-development/SKILL.md](https://github.com/apify/awesome-skills/blob/main/skills/apify-orchestrator-actor-development/SKILL.md)
- “Link to the skill” on the slide = the [SKILL.md](http://SKILL.md) above. Vladimir: use these, do not hand-roll the actor scaffold.

### PostHog — “Hog takes the wheel”

Slide: “The usual way vs self-driving” (file hog-takes-the-wheel-9-slides.pdf, slide 5/9):

- Spotting it: you stare at a funnel chart → signals flow in on their own.
- Sorting it: an alert you muted last week → an agent groups them.
- Digging in: a recording, now and then → it digs in, or honestly drops it.
- Fixing it: between the shiny new stuff → it drafts the fix.
- Your job: all of the above → say yes or no.
- “You were building the shiny thing the whole time.”

PostHog’s own self-driving model ([posthog.com/docs/self-driving](http://posthog.com/docs/self-driving), “Code is now Desktop” blog): scouts watch 24/7 and emit signals; signals group into reports; an agent investigates each report; when actionable it opens a pull request for review, when it needs input it surfaces the report in the Inbox; after the change ships PostHog checks whether it worked and feeds the result back. Loop: Collect data → cluster signals → check memory → notify workers → do work → review and ship → evaluate → write back to memory. Signal sources in PostHog: error tracking, session replay (dead clicks, quick backs, long stalls), support tickets, external tools (Zendesk / Linear / GitHub).

Our version is the same loop, with DOMOVOY signals instead of PostHog’s own product signals — and the “PR” is a criteria / prompt / listing change, not code.

## 1. The loop — one loop, two surfaces

```javascript
Capture → Cluster → Check memory → Propose → Human yes/no → Apply → Measure → Write back
   ↑                                                                             |
   └────────────────────────── loop repeats ─────────────────────────────────────┘
```

1. <b>Capture.</b> Every DOMOVOY step emits a PostHog event with structured properties (not a log line). PostHog is the database of structured data. Event schema: <code>listing_id, portal, rent, total_monthly, upfront_cash, extraction_confidence, outcome, distinct_id (renter / agency)</code>.
2. <b>Cluster.</b> A scout (our agent, reading PostHog) groups signals by pattern: same attribute, same portal, same realtor, same failure. One pattern = one report. Noisy single events are dropped honestly.
3. <b>Check memory.</b> Have we seen this before? Did the last fix work? If yes, do not re-propose it.
4. <b>Propose.</b> The agent drafts ONE concrete change with evidence + expected effect. Never a vague “improve search”.
5. <b>Human says yes / no.</b> Renter approves a criteria change; agency approves a listing change. Nothing auto-ships to a realtor or a public listing without a yes. This is the “your job: say yes or no” step.
6. <b>Apply.</b> The change goes live: criteria tightened, prompt / model swapped, ranking re-run, listing draft updated.
7. <b>Measure.</b> PostHog measures the next N signals: did Interested rate / viewing rate / extraction accuracy move? If not, the fix is dropped and that is written back too.
8. <b>Write back.</b> Outcome stored as memory. Loop repeats.

Guardrails: no auto-contact, no auto-price change on a live listing, no auto-send to a realtor. Approval is the product.

## 2. Signals — what we send to PostHog, and what each one improves

### 2a. For a regular person (the renter) — Lane 3a

| # | Signal (PostHog event) | Source | Properties that matter | What it improves |
| --- | --- | --- | --- | --- |
| S1 | <code>listing_rejected</code> (×3, same attribute) | Notion shortlist — Interested / Not interested clicks | <code>reason, attribute (no elevator / commute >25 min / total >30k / upfront too high)</code> | Tighten criteria, re-rank, stop showing similar flats, ask 1 clarifying question |
| S2 | <code>extraction_low_confidence</code> | Apify + Featherless extract() | <code>field, confidence <0.8, verbatim_quote_missing, model</code> | Re-extract with another model, flag listing “uncertain”, improve prompt; feeds the Featherless eval |
| S3 | <code>call_incomplete</code> | ElevenLabs call — tool results | <code>missing_fields (move-in date / furniture), no_answer, dropped</code> | Retry with a different script, change first message, fall back to email inquiry |
| S4 | <code>viewing_bad</code> | Calendar + post-viewing feedback | <code>no_show, flat != listing, noise, dark, small</code> | Downrank that portal / realtor, warn the next user, add a checklist item |
| S5 | <code>listing_stale</code> | Apify pipeline | <code>price_changed, listing_gone, age_hours, collected_at</code> | Refresh faster, show collection time, drop stale listings |
| S6 | <code>user_stalled</code> | Funnel / session replay | <code>step (brief / shortlist / Interested), stall_seconds, dead_click</code> | Simplify the brief to 3 questions, prefill from the last search |
| S7 | <code>cost_surprise</code> | Notion / Calendar | <code>upfront_cash, monthly_total, budget</code> | Surface upfront cash earlier, filter by upfront not just monthly rent |

Example, end to end: Vladimir marks 3 flats Not interested, all 3 have no elevator. Scout report: “3/3 rejections share: no elevator. Proposal: require elevator, re-rank shortlist, expected: fewer dead shortlists.” Vladimir says yes → shortlist re-ranks live. Next signals measure whether Interested rate goes up.

### 2b. For a real-estate agency — Lane 3b

Same PostHog database, grouped by listing / agency (PostHog Group Analytics). Same loop, different “human”.

| # | Signal | Source | What the agent proposes (agency says yes / no) |
| --- | --- | --- | --- |
| A1 | Views but 0 Interested | Portal + DOMOVOY funnel | Reorder photos, rewrite headline, reprice vs comparables from Apify |
| A2 | Drop-off at price / upfront | Funnel: view → shortlist | Suggest a price cut / lower kauce, show comparables |
| A3 | Realtor slow reply | Call / email reply time | Nudge the realtor, auto-draft a follow-up, reassign |
| A4 | Viewing → no offer, same feedback | Post-viewing feedback cluster (“dark”, “noisy”, “small kitchen”) | Fix the listing truthfully, adjust targeting — do not hide it |
| A5 | High Interested / viewing rate | Funnel, best listings | Learn what works (headline / photo order / price band), replicate it |

Honest boundary (already locked): do NOT claim an agency customer was already shown this. Lane 3b is a demo of what an agency <i>would</i> see, using our own run as the data.

## 3. What to build today — in order, with cuts

P0 — must have for the Mac mini demo:

- PostHog capture in DOMOVOY: <code>posthog.capture()</code> for the \~8 core events above, one shared schema, <code>listing_id</code> on everything.
- One scout query: a script / agent that reads PostHog (or the local event log mirrored to PostHog) and outputs ONE grouped report with evidence.
- One yes/no approval: in Notion / CLI / phone page. Approve → apply the change → re-rank live.

P1 — if time remains:

- Show the signal + report inside PostHog itself (Inbox / dashboard) live, not a screenshot. If the wizard (<code>npx @posthog/wizard</code>, <code>wizard self-driving</code>) does not work in the venue, show our report with PostHog event IDs — do not fake the Inbox.
- Agency view: same events grouped by listing, one drafted listing fix.

Cut for today:

- Full PostHog self-driving wizard / auto-PR, session replay integration, surveys. Name them as next steps, do not build them.
- Do not wait for weeks of data. Honest seeding: today’s own run IS the data — every click / call today is a signal — plus the hand-labelled \~20 listings from the Featherless eval as the initial signal set. Do not fake months of usage.

## 4. The 3-minute demo — hard stop

Total 3:00. Do not run over — it is a hard stop.

| Time | What happens | Lane |
| --- | --- | --- |
| 0:00–0:15 | Problem in one sentence: Vladimir, real brief, real pain between finding a flat and getting a viewing. | 1 |
| 0:15–1:30 | Live loop: shortlist in Notion → live ElevenLabs call → confirmed viewing appears in Calendar. | 1 + 2 |
| 1:30–2:30 | Lane 3: PostHog Inbox / report — one real signal from today’s run (e.g. 3 rejections, no elevator → propose tightening criteria; or S2 low-confidence extraction → re-extract). Human says yes on stage, ranking changes live. | 3a |
| 2:30–3:00 | Close: same loop for an agency in one sentence + one drafted listing fix on screen. Links: GitHub + demo/site on the submission form. | 3b |

If the call fails live: do NOT rebuild. Show the last successful call trace + Notion / Calendar receipt, say so, and go straight to Lane 3 — the PostHog report is still live and still proves the loop.

## 5. How this wins the Mac mini (and how it does not hurt the main prize)

- The PostHog judge wants to see: PostHog as the context layer, signals → report → human yes/no → measured change. Show the loop, not the logo.
- Keep Lane 3 to 60 seconds inside the 3-minute demo. If it eats the live call, cut Lane 3, not the call — the overall rubric weights “does it work live” above everything.
- Name one thing learned from the PostHog workshop (“Hog takes the wheel”: signals flow in, agent groups them, your job is say yes or no). That answers judging criterion 2 directly.

## Sources

- PostHog self-driving docs: [https://posthog.com/docs/self-driving/](https://posthog.com/docs/self-driving/) — scouts, signals, reports, Inbox, PR, measure, loop.
- PostHog “Code is now Desktop / self-driving product”: [https://posthog.com/blog/self-driving-product](https://posthog.com/blog/self-driving-product) — Collect → cluster → check memory → notify → do work → review/ship → evaluate → write back.
- PostHog AI wizard: [https://posthog.com/docs/ai-engineering/ai-wizard](https://posthog.com/docs/ai-engineering/ai-wizard) — <code>npx @posthog/wizard</code>, <code>wizard self-driving</code>.
- Featherless redeem (\$25, code AIT2026): [https://featherless.ai/join/feather\_request\_pricing/AIT2026?amount\_usd=25](https://featherless.ai/join/feather_request_pricing/AIT2026?amount_usd=25)
- Apify Actor dev skill: [https://github.com/apify/agent-skills/tree/main/skills/apify-actor-development](https://github.com/apify/agent-skills/tree/main/skills/apify-actor-development)
- Apify Orchestrator dev skill: [https://github.com/apify/awesome-skills/blob/main/skills/apify-orchestrator-actor-development/SKILL.md](https://github.com/apify/awesome-skills/blob/main/skills/apify-orchestrator-actor-development/SKILL.md)
- DOMOVOY parent page + Judge / Critic subpage: <mention url="https://app.notion.com/p/41396f068f8981b5baebf30a056e95cd">DOMOVOY — Hackathon Proposal & Demo Flow</mention> and <mention url="https://app.notion.com/p/41796f068f898149b99de7f040ea4280">Judge / Critic — How DOMOVOY Will Be Judged</mention>

<i>Created 13 Nov 2026, \~10:40, from the morning workshops (photos) + PostHog docs. The Mac mini decider is the PostHog contact in the room — this lane is written for him.</i>
