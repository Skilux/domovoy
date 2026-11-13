# Hackathon

- **Source:** https://app.notion.com/p/41396f068f898055bbf4d370b51d72b9?pvs=204
- **Notion page ID:** 41396f068f898055bbf4d370b51d72b9
- **Last edited in Notion:** 2026-11-09T18:50:28.818Z
- **Exported:** 2026-11-13, from Danila's Notion via the Notion integration

---

# BytHlídač — Hackathon Project Brief

<callout icon="🏠" color="blue_bg">
<b>Main idea:</b> BytHlídač is a personal flat-hunting intelligence assistant for Prague. A user describes their ideal home once; the system searches property listings, filters out obvious mismatches, investigates promising flats, explains the trade-offs, and prepares the next action—without requiring the user to spend hours refreshing portals and comparing listings.

<b>Product promise:</b> “Tell us what home you need. We watch the market, find the promising flats, explain why they fit, and help you act while the listing is still available.”
</callout>

<b>Event:</b> AI Agents for the Rest of Us — AI Tinkerers Prague, Friday <date start="2026-11-13" end="2026-11-13" start-time="09:00" end-time="20:30" time-zone="Europe/Prague" />. Official build time: 11:30–18:00 (6.5 hours). Team size: 2–4. Live demos begin at 18:00; pre-recorded videos are not permitted. [Event page](https://lu.ma/6rgvg844).

<b>Document status:</b> Working project brief as of 9 Nov 2026. This document intentionally distinguishes <b>confirmed choices</b>, <b>recommended hackathon scope</b>, and <b>open questions</b>. It is not a claim that the system has already been built.

## 1. Problem, target user, and product story

<b>The pain:</b> Searching for a rental flat in Prague is a repetitive, time-sensitive workflow. People repeatedly check multiple portals, discover duplicates, compare advertised rent with true monthly costs, work out whether a location fits their life, translate Czech descriptions, and rush to respond. A simple new-listing notification does not answer whether the flat is worth contacting.

<b>The job to be done:</b> “When a flat matching my real constraints becomes available, tell me quickly if it is worth my attention, show your reasoning, and help me contact the landlord.”

<b>Primary market:</b> Prague rental apartments. Buying is a potential future extension, not the hackathon focus.

<b>Target human:</b> A real person actively searching for a Prague flat. The exact demo user and their actual constraints are <b>not yet confirmed</b>. We should choose a real person and explain their concrete story rather than inventing a persona.

<b>Suggested hackathon positioning:</b> <i>Fast discovery with meaningful intelligence.</i> Speed and autonomy are the primary pain; neighborhood insights, hidden costs, and agent investigation make this more useful than an ordinary alert.

## 2. Product experience — two modes, one engine

### Mode A — Find now

The user says: “Find me a 2+kk in Prague 6 under 30,000 Kč.”

The system creates or uses a search profile, immediately shows relevant cached matches if available, triggers a targeted provider refresh, applies rules, enriches top candidates, and returns ranked results with a clear next step.

### Mode B — Monitor over time

The user says: “Keep watching for the next three months and alert me about good matches.”

The same profile and pipeline run on a schedule. The system retains known listings and history, recognizes new or changed records, and avoids alerting repeatedly about the same flat. The user can pause or edit monitoring.

<b>Shared behavior:</b> Search once and monitor continuously should not be separate implementations. Different triggers, same acquisition, normalization, decision, and result contracts.

### Onboarding requirements

- <b>Hard constraints:</b> Rent vs buy, city/districts, maximum total monthly budget, disposition (e.g., 2+kk), minimum area, move-in timing, essential requirements (pets, elevator, furnished, etc.).
- <b>Soft preferences:</b> Quiet area, commute to saved destinations, good transit, greenery, cafés, parking, sunlight, floor, amenities.
- <b>Priority / urgency:</b> ASAP vs flexible; one-time search vs monitoring; notification frequency.
- <b>Transparency:</b> Distinguish advertised base rent from utilities and service fees. Missing information is marked unknown, not guessed.
- <b>Output:</b> Reusable search profile that can be edited and re-evaluated against stored listings.

## 3. Hackathon MVP — what we actually need by 18:00

The recommended goal is <b>one honest, working vertical slice</b>, not a fully productionized platform.

| Priority | Capability | Observable result |
| --- | --- | --- |
| Must | Simple onboarding | User can set budget, location, type, and priorities without editing code |
| Must | One real source of listings | Fetch a bounded set of real Prague listings (Apify Actor or other accessible source) |
| Must | Normalize / deduplicate / store | Same listing does not appear as several independent discoveries |
| Must | Hard rules + ranking | Clearly wrong listings are rejected; others receive explainable results |
| Must | Agent investigation of top match | Agent inspects evidence, flags uncertainties, and gives a grounded verdict |
| Must | Useful next action | Czech inquiry draft is ready to copy; <b>human sends</b> |
| Must | Lightweight results interface | Show listings, images where available, score reasons, and listing links |
| Must | Monitoring proof | Save search; demonstrate a second scheduled or manually triggered scan and persisted state |
| Nice to have | Simple map / geo dossier | Nearby transit/amenities for the top listing |
| Nice to have | Price and fee breakdown | Base rent, fees, deposit, agency costs, unknowns |
| Stretch | Second source, alerts, MCP tool | Only after golden path is reliable |

<b>Explicitly not required for the hackathon:</b> Multi-user SaaS, broad city portability, full 3D sunlight modeling, comprehensive crime/environment scores, multi-agent coordination, reliable autonomous landlord contact, full calendar integration, real phone calls, and production-level deployment.

<b>MVP acceptance test:</b> A person can enter criteria → obtain real listing data → see automatic filtering → watch an agent investigate a real candidate → receive a grounded recommendation and a Czech inquiry draft → run monitoring again without losing state.

## 4. Core differentiator — deterministic intelligence before agentic reasoning

<callout icon="🧠" color="gray_bg">
<b>Design principle:</b> The always-on system must remain useful without a connected full agent. Scripts and deterministic decisions do the routine work. Cheap structured model calls resolve bounded ambiguity. An agent is used selectively for investigation, explanation, and next-action preparation.
</callout>

<b>Logical flow:</b>

1. <b>Acquire:</b> Scraper / API adapter gathers listings (scheduled or on demand).
2. <b>Normalize:</b> Convert portal-specific fields into canonical records; preserve raw evidence, source URL, and timestamps.
3. <b>Deduplicate and detect changes:</b> Identify the same listing across runs, record price and status changes.
4. <b>Filter and enrich:</b> Apply explicit criteria; gather relevant information such as transit, amenities, and known fees.
5. <b>Decide:</b> Use deterministic rules and a lightweight ranking model; use a small LLM call only when extraction/classification is ambiguous.
6. <b>Escalate:</b> Send only strong matches, contradictions, or uncertainties for agent review.
7. <b>Deliver:</b> Show shortlist, evidence, explanations, Czech draft, and monitoring status in the UI.

<b>Evaluation states:</b> PASS (verified match), REJECT (verified hard-constraint violation), NEEDS\_DATA (unknown required attribute), REVIEW (conflicting evidence). Do not silently reject unknowns or invent a precise score from weak evidence.

<b>Agent escalation examples:</b> Listing price excludes unclear fees; unusual rent/area combination; conflicting floor or elevator information; two otherwise strong flats with different commuting or lifestyle trade-offs. Agent reasoning must cite the listing/source evidence available to the system.

<b>Human-in-the-loop boundary:</b> The agent may research, prioritize, draft, and notify. The human approves/sends messages and books or pays. The system should never treat scraped listing text as trusted instructions.

## 5. Demo narrative — aim for 90 seconds of working product

<b>Illustrative user request (not a real confirmed profile):</b> “Find a quiet 2+kk in Prague 6, up to 30,000 Kč total, with convenient public transport. Start monitoring too.”

1. <b>Opening:</b> Show the human problem in one sentence: hours of repetitive flat hunting and the risk of missing a promising listing.
2. <b>Onboarding:</b> Enter four or five criteria in a user-friendly screen.
3. <b>Live acquisition:</b> Trigger a small, capped real-provider run; expose source and retrieval timestamp.
4. <b>Filter:</b> Display the number of listings collected, duplicates removed, hard rejects, and candidates remaining.
5. <b>Agent moment:</b> Select one candidate; agent checks what the listing does and does not establish, explains the trade-offs, and issues a recommendation.
6. <b>Action:</b> Show a Czech inquiry draft and listing source link; user can copy and send it.
7. <b>Always-on proof:</b> Show saved monitoring profile, last run, and a subsequent scan / persisted findings.
8. <b>Technical close:</b> Explain deterministic pipeline → selective agent reasoning; briefly show observability if implemented.

<b>Live demo safeguard:</b> Seeded/cached backup data is acceptable as an explicitly labeled fallback; never present it as a fresh live scrape. Avoid demo steps that require a new signup, untested keys, uncontrolled phone calls, or long browser navigation.

## 6. Product UI — enough for a nontechnical user

- <b>Onboarding:</b> Plain-language form for hard requirements, preferences, urgency, and alerts.
- <b>Results:</b> List/grid of flats with photos, location, rent, disposition, source, match status, and clear reasons.
- <b>Detail / dossier:</b> Price breakdown, known and unknown facts, simple geo context, agent verdict, evidence, and Czech draft.
- <b>Monitoring:</b> Saved profile, frequency, last successful run, results discovered, and pause/resume.
- <b>Map:</b> Valuable if straightforward, but a rich map must not delay the working core.

The interface should show an <b>artifact of the agent's work</b> (a scored listing and actionable draft), not only a chat transcript.

## 7. Long-term product vision — separate from the hackathon MVP

<b>Confirmed conceptual direction from design discussions:</b> A <b>hybrid, single-user, always-on flat-intelligence instance</b> with both an independent web interface and an agent-facing capability pack (API/MCP). One primary agent and one intelligence installation; many search profiles and progressively more data sources. It can answer ad-hoc requests and monitor for months.

<b>Selected deployment direction:</b> VPS so collection continues when the user's laptop and browser are off. This is the intended product deployment, <b>not necessarily a prerequisite for the Friday demo</b>.

<b>Proposed (not yet locked) implementation:</b>

| Layer | Candidate technology / responsibility |
| --- | --- |
| Acquisition | Apify Actor first, alternative provider adapters later |
| Processing | Python jobs: normalize, deduplicate, enrich, evaluate |
| Persistent state | SQLite initially, local VPS volume, backups; raw snapshots retained |
| Scheduling | Cron or small scheduler that enqueues durable jobs |
| Worker | One controlled execution worker with retries and provider limits |
| Backend | FastAPI and a shared service layer |
| Agent interface | Remote MCP or typed API tools; external agent can connect on demand |
| Dashboard | Thin web UI using the same backend |
| Observability | Structured logs, job history, provider errors; PostHog where useful |

<b>Important architecture boundaries:</b>

- The <b>backend/database</b>, not an agent session, owns listings, search profiles, facts, evaluations, run history, and investigation results.
- Scheduler only <b>enqueues</b> due jobs; worker <b>executes</b> them. Scheduled monitoring and ad-hoc requests use one pipeline.
- The agent is an <b>optional consumer/producer of investigation tasks</b>. If disconnected, collection continues and tasks remain pending.
- Each listing fact should retain origin, timestamp, and degree of certainty. Evaluation is profile-specific; facts are reusable.
- An external MCP request that starts a slow search should return a <b>job identifier</b> and expose status/results later, rather than hang until scraping completes.
- Do not introduce Redis, Kafka, Kubernetes, or a vector DB without a concrete need.

<b>Still unresolved:</b> Whether unattended LLM/agent investigation must execute on the VPS while the primary external agent is offline; whether notifications should send a preliminarily scored lead or wait for deeper review.

## 8. Reusable intelligence / data model

Suggested entities for a minimal persistent implementation:

| Entity | Owns |
| --- | --- |
| Search profile | Hard constraints, preferences, schedule, active state |
| Source listing | Provider ID, URL, raw payload, fetch timestamp |
| Canonical listing | Deduplicated normalized property information |
| Listing facts | Price, layout, floor, fees, location; evidence and uncertainty |
| Evaluation | Per-profile decision, score breakdown, reasons, rule/model version |
| Search run / job | Trigger, status, attempts, source coverage, errors |
| Agent task | Pending investigation, agent findings, completion state |
| Events | Discovered, changed price, shortlisted, alerted, rejected |
| User workflow state | Saved / contacted / viewing arranged / rejected |

<b>Do not conflate:</b> A source listing with a real apartment; a factual observation with a preference score; a missing field with a negative result.

## 9. Geographic intelligence — phase by usefulness

<b>Hackathon, if time remains:</b> Transit proximity / access and basic amenities around the top candidate. A small, reliable dossier is more convincing than a huge set of inconsistent map layers.

<b>Follow-up data products:</b> Noise maps; vegetation and surface temperature; flood zones; 3D building models; commute via PID; public facilities, parking, recycling, and microclimate via Golemio; demographic context; official rental-price benchmarks.

<b>Playful differentiation for later:</b> Pub Density Index, Cappuccino Accessibility, Leg Day Index (elevation walking from transit), and Trash Convenience Score. Label these as derived indices rather than official measurements.

<b>Potential data sources:</b> [Prague Geoportal](https://geoportalpraha.cz/en/data-and-services/open-data), [Golemio API](https://api.golemio.cz/docs/public-openapi/), [PID open data](https://pid.cz/en/opendata/), [OpenStreetMap/Overpass](https://overpass-turbo.eu/). Availability, spatial precision, licensing, and freshness must be checked before implementation.

## 10. Sponsors and judging fit

| Sponsor | Meaningful possible role |
| --- | --- |
| Apify | Scrape a real set of Czech apartment listings; show Actor output and timestamp |
| Featherless | Structured extraction and/or a named model for agent investigation; show rationale/cost |
| PostHog | Trace agent/model decisions, latency, cost, and relevant user events |
| PangeAI | Geospatial intelligence is thematic inspiration; do not claim an integration without an actual API |
| Tensor Ventures | Look for concrete user value, technical credibility, and an extensible idea |
| [prg.ai](http://prg.ai) / Dny AI | Prague relevance, accessible nontechnical experience, honest limitations |

<b>Published judging criteria:</b> (1) real problem for a real person and personal insight, (2) working live agent and what was learned during the hack, (3) whether nontechnical people would use it.

<b>Demo framing:</b> Show a visible before/after (manual search vs actionable shortlist), real data, a selective agent decision, and a concrete next action. Sponsor usage should be authentic, not decorative. The PostHog Mac mini special-prize criteria were not specified in the provided event rules.

## 11. Build-day execution plan

| Time (Nov 13) | Focus |
| --- | --- |
| 09:00–10:00 | Team/user validation; inspect demo constraints and tools |
| 10:00–11:15 | Hear official rules; attend Apify / Featherless / PostHog workshops; confirm access and allowed prior work |
| 11:15–11:30 | Finalize team, ownership, exact demo case, and scoped golden path |
| 11:30–12:30 | Real listing → normalized data → basic output (ugly but working) |
| 12:30–15:00 | Hard filters, shortlist, agent investigation, Czech draft |
| 15:00–16:30 | Minimal interface, saved monitoring, observability, fallback |
| 16:30–17:30 | Freeze features, rehearse live demo, fix blockers |
| 17:30–18:00 | Final reliability check and demo setup |
| 18:00 | Present working agent live |

<b>Proposed division for two engineers:</b> one owns provider acquisition, normalized data, and jobs; one owns agent behavior, user-facing experience, and demo. Exact responsibilities and teammate attendance are not yet confirmed.

<b>Prebuilding caveat:</b> The supplied event description does <b>not</b> spell out whether existing project code can be submitted or exactly what reusable templates are allowed. Ask at the 10:00 rules session; be transparent about prebuilt scaffolds and cached data.

## 12. Acceptance criteria & operational risks

<b>Hackathon acceptance:</b>

- [ ] Search profile can be created without editing code
- [ ] At least one real listing provider returns usable results
- [ ] Correct filtering for hard budget/layout constraints
- [ ] Listings are persisted, and re-running does not create obvious duplicates
- [ ] At least one candidate is genuinely investigated by an agent
- [ ] Recommendation distinguishes supported evidence from unknowns
- [ ] Czech inquiry is ready for human review / copy
- [ ] Saved monitoring profile and second scan can be demonstrated
- [ ] Core demo can complete live; labeled fallback works if needed

<b>Key risks and mitigations:</b>

- <b>Scraper blocked / rate limited:</b> Cap results, test early, cache snapshots, clearly label fallback.
- <b>Missing or approximate addresses:</b> Do not claim precise sunlight/noise/building-level conclusions without precise coordinates.
- <b>Agent invents fields:</b> Require structured evidence and explicit UNKNOWN values.
- <b>Too many capabilities:</b> One provider and one complete scenario before extra integrations.
- <b>VPS/network outage:</b> Have a local or cached demo path; persistence and backups for later productization.
- <b>Unauthorized actions:</b> No autonomous landlord messaging, bookings, or payments in the MVP.
- <b>Time pressure:</b> Freeze features early, rehearse the whole user journey several times.

## 13. Decisions and open questions

### Confirmed decisions

- <b>Hybrid platform direction:</b> A user-facing application plus agent-accessible capabilities.
- <b>Single-user first:</b> One instance and one primary agent, not a multi-tenant SaaS.
- <b>VPS long-term runtime:</b> Always-on collection independent of the local laptop.
- <b>Two search modes:</b> Targeted instant search and scheduled monitoring, backed by the same intelligence store.
- <b>Processing philosophy:</b> Scripts/deterministic steps first, small decision models where appropriate, agent reasoning for selected escalations.
- <b>Prague rental focus</b> for the hackathon. Buying remains optional later.

### Recommended, not yet accepted

- <b>Core hackathon pain:</b> Finding promising new flats quickly, with enough analysis to make the alert actionable.
- <b>MVP scope:</b> One provider, onboarding, filtering, persisted monitoring, one agent investigation, and a human-reviewed inquiry draft.
- <b>Tech stack:</b> Python / FastAPI / SQLite / lightweight worker; optional MCP and PostHog instrumentation.
- <b>Two-person implementation split</b> and a short, live result-first demo.

### Questions to resolve before coding

1. <b>Who is the actual end user?</b> Their real district, budget, layout, commute and urgency; what is the authentic pain story?
2. <b>Primary value:</b> Do we prioritize <b>speed to new listings</b> or <b>quality of analysis</b> in the demo? Proposed: speed first, intelligence as proof.
3. <b>Real listing source:</b> Which Apify Actor or legally accessible portal reliably delivers useful Prague listings with adequate terms, latency, and cost?
4. <b>Agent runtime:</b> Is a bounded hosted model call enough for demo-day agent investigation, or must a separate agent runtime demonstrate tool use?
5. <b>Offline autonomy:</b> Should VPS perform deeper investigations without the primary agent, or only queue them?
6. <b>Nontechnical interface:</b> Results page only, or a map as essential to the demo?
7. <b>Monitoring proof:</b> How will we visibly show a second run detecting one new/changed listing in the allotted time?
8. <b>Communication:</b> Dashboard only, email alert, or something else? Voice and phone are not yet committed.
9. <b>Team and event constraints:</b> Confirm teammate(s), registrations, API credits, and prebuilt-code rule at kickoff.

## 14. DOMOVOY — new hackathon demo flow (working draft, 9 Nov 2026)

<callout icon="🏡" color="blue_bg">
<b>Working name:</b> DOMOVOY (not finalized; earlier name: BytHlídač).

<b>One-line pitch:</b> DOMOVOY coordinates your flat hunt—from finding suitable listings to arranging a viewing—so you spend your time choosing a home, not refreshing portals and chasing messages.
</callout>

### Problem statement — pitch draft

“I need to rent a flat, but I don't have time to keep refreshing Sreality, iDNES Reality, and other difficult-to-use property sites. Finding the same apartment across portals, figuring out its real costs, and coordinating with agents and my calendar is painful.”

“That’s why we built <b>DOMOVOY</b>: an agent-assisted property-hunting coordinator that finds matching flats, prepares an actionable shortlist, and helps take approved options all the way to a viewing.”

<b>Positioning note:</b> “Makes sure you get the best deal” is too strong to demonstrate or guarantee. Prefer <b>“helps you find and act on the best matches”</b> with an explainable price and fit comparison.

### The proposed end-to-end journey

1. <b>Set up criteria.</b> Example: rental 2+kk in Vinohrady, maximum 30,000 Kč <b>total monthly</b>, elevator required, standard <b>nájem</b> only (no <b>podnájem</b> / sublease). Distinguish hard filters from preferences and define what the budget covers.
2. <b>Find and deduplicate flats.</b> A team-built Apify Actor (or actors) gathers listings from <b>three portals</b> if the integrations are working; the pipeline normalizes fields, retains source URLs/photos and detects duplicate records. The agent can trigger a run but doesn't need to manually perform deterministic scraping. <b>Three-source coverage is a demo target, not yet a verified guarantee.</b>
3. <b>Calculate affordability and move-in cash.</b> For each flat, show recurring rent + services/utilities where known, and <b>upfront cash needed</b>: first rent payment + deposit (<b>kauce</b>) + agency commission if any + any other stated one-time fees. Show a breakdown, not only one invented total; flag unknown items and possible returnable deposit.
4. <b>Export findings to Notion.</b> A Notion database becomes the review workspace: each property has a listing link, photos if usable, area, rent, move-in cost, hard-filter status, source, reason to consider it, open questions, and current workflow status.
5. <b>User decides.</b> In Notion, choose <b>Yes / No / Need more information</b>. Yes = request to move forward; No = dismissed with optional reason; Need more information = agent investigation. The change must trigger follow-up via a verified Notion integration (webhook or safe polling).
6. <b>Coordinate outreach after Yes.</b> Agent reads available calendar windows, proposes a few reasonable viewing times and drafts a Czech email to the realtor/landlord. <b>Human reviews and approves sending.</b> Direct realtor phone calls are an optional stretch feature—not necessary for the core demo.
7. <b>Process the realtor reply.</b> Detect a response in a connected mailbox; distinguish <b>confirmed</b>, <b>alternative time proposed</b>, <b>declined</b>, and <b>needs clarification</b>. Only create a confirmed calendar viewing when time, date, recipient/property, and approval are unambiguous. Include property link, contact, address if available, questions, and visit checklist. If no reply, keep the lead in <b>Awaiting reply</b> rather than claiming a booking.
8. <b>Capture the viewing outcome.</b> After the visit, record <b>Liked / Rejected / Considering</b>, notes, concerns, next action, and any follow-up tasks in Notion. Reuse explicit feedback when ranking future candidates; don't silently rewrite the user's hard constraints.

### Important design distinction: what runs where?

| Action | Primarily responsible |
| --- | --- |
| Fetch and deduplicate across portals | Apify + deterministic pipeline |
| Compute price and cash-to-move estimates | Deterministic rules, with missing fields flagged |
| Extract ambiguous listing details / explain trade-offs | Bounded model calls or agent |
| Populate/update Notion | Backend integration |
| React to Yes/No status and queue action | Backend trigger / monitoring loop |
| Check available viewing times | Calendar integration |
| Draft outreach / interpret realtor reply | Agent with email and calendar tools |
| Approve send / confirm consequential actions | Human |
| Track pipeline / feedback | Notion as current demo workspace |

<b>This is a meaningful refinement of the earlier “dashboard first” idea:</b> For the hackathon, <b>Notion is the primary review and pipeline UI</b>; a bespoke map/dashboard remains an optional future layer. We shouldn't build both in six hours.

### What I would ADD (high impact)

- <b>Explainability for every card:</b> “Why did this match?” + “What is uncertain?” with links to original evidence.
- <b>A clear, visible status pipeline:</b> New → Ready for review → Yes / No / Need info → Draft approval → Contacted → Awaiting reply → Viewing confirmed → Viewed → Outcome.
- <b>Separate monthly affordability from move-in cash:</b> Important in Czech rentals; deposit is cash needed up front, not normal monthly expense.
- <b>A human approval checkpoint:</b> A Notion Yes is approval to prepare outreach, <b>not automatically permission to send mail or call</b> unless explicitly configured.
- <b>Reply handling and no-reply state:</b> What if the realtor doesn't respond, offers another time, or says it is gone?
- <b>A viewing checklist and follow-up questions:</b> Elevator, legal lease type, exact fees, deposit, condition, noisy surroundings, pets, move-in date as appropriate to the listing.
- <b>Observability in the demo:</b> Show source timestamps, pipeline counts, agent action trace / decision reasons, and, if connected, PostHog model traces.

### What I would REMOVE or defer for Friday

- <b>No live phone calls to realtors</b> in the must-have path. Permission, telephony, call flow and demo reliability make this too risky.
- <b>Don't require a real realtor to answer during the demo.</b> Use a <b>clearly labeled test mailbox / scripted test reply</b> to demonstrate reply processing; never pretend it was a real response.
- <b>Don't require all three scraping portals before the product works.</b> One reliable source with real data beats three flaky ones; add more only after the full path is complete.
- <b>Skip building a separate custom dashboard</b> if Notion already handles triage, statuses and notes.
- <b>Do not claim automatic booking</b> when the system has only proposed time slots or drafted an email.
- <b>Don't prioritize a full geospatial dossier, voice, or sophisticated scoring</b> over the core user-to-viewing workflow.

### Realistic live-demo cut (core vs. staged extension)

<b>Must work live by 18:00:</b>

1. Enter the Vinohrady / 2+kk / ≤30k / elevator / no-podnájem filter.
2. Run at least one real Apify-powered acquisition; show normalization, deduplication and price/cash calculations.
3. Create or update short-listed properties in a Notion database with evidence and clear status.
4. Flip a listing to <b>Yes</b>; backend detects the change, agent reads calendar availability and creates a <b>send-ready Czech inquiry draft</b>.
5. Show an approval gate and that the listing's workflow status updates correctly.

<b>Stretch, only if core is stable:</b> Send an approved test inquiry, process a labeled synthetic/test reply, create a test calendar viewing with source links and questions, then enter a sample post-viewing outcome in Notion.

<b>Presentation guidance:</b> A live demo can show an external integration working with test data. Clearly label every simulated step and every cached result. The audience should understand exactly which pieces are live and which are examples.

### Open choices to settle

1. <b>Product name:</b> DOMOVOY vs BytHlídač; keep DOMOVOY as working name until explicitly locked.
2. <b>Source readiness:</b> Does the team-built Apify Actor actually return correct structured results for all three portals?
3. <b>Notion data model:</b> New Notion database under this Hackathon page or an existing database? Which properties will trigger the next step?
4. <b>Approval semantics:</b> Does Yes mean “please prepare outreach” or “you may send the prepared inquiry automatically”?
5. <b>Email/calendar demo:</b> Which test mailbox and calendar are safe to use without involving a real realtor?
6. <b>Success definition:</b> Is the winning demo <b>review → approved draft</b>, or must it <b>create a confirmed test viewing</b> end to end?
7. <b>User story:</b> Who is the real flat hunter, and which inconvenience have they personally experienced?

## 15. Original page notes (preserved below)

The notes that were already on this Notion page follow unchanged. Some items (voice, calendar booking, Notion DB) are <b>possibilities</b>, not confirmed hackathon commitments.

---

focus on rent / optional buy

1. scrapping data
   1. Apify or custom scrapper
2. notion db
3. emails / calendar booking / phone?
4. notes / checklist / feedback back to agent

<p />

- Voice agent
- Email agent

<p />

Features:

1. Onboarding
2. Show on map + images

<p />

<page url="https://app.notion.com/p/41396f068f8981b5baebf30a056e95cd">
DOMOVOY — Hackathon Proposal & Demo Flow
</page>
