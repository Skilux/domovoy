# 🏡 DOMOVOY — Hackathon Proposal & Demo Flow

- **Source:** https://app.notion.com/p/41396f068f8981b5baebf30a056e95cd?pvs=204
- **Notion page ID:** 41396f068f8981b5baebf30a056e95cd
- **Last edited in Notion:** 2026-11-13T09:45:29.480Z
- **Exported:** 2026-11-13, from Danila's Notion via the Notion integration

---

<callout icon="🏡" color="blue_bg">
<b>DOMOVOY — Your real-estate agent in your pocket</b> (working name)

<b>Promise:</b> Tell your existing AI agent what home you need. DOMOVOY researches the market, surfaces promising properties, and handles the coordination to get you closer to a viewing—while you make the important decisions.

<b>Hackathon mission:</b> Prove one complete, memorable workflow for a real renter, not every future real-estate capability.
</callout>

## 1. Problem & target user

<b>The problem:</b> Renting a flat in Prague means repeatedly searching portals, comparing duplicate or incomplete listings, calculating real move-in costs, checking whether an offer fits your constraints, and chasing realtors to arrange viewings. The real pain is the work <i>between</i> finding an apartment and actually seeing it.

<b>Real user for the story:</b> Vladimir, a teammate who is currently looking for an apartment and has real candidates. With his permission, use his genuine criteria and listings; do not invent details about his budget or personal situation before checking with him.

<b>Opening line:</b> “Vladimir is looking for a flat in Prague. Finding a listing is just the beginning. Then he has to figure out whether it fits, chase the realtor, and arrange a viewing. We built DOMOVOY to handle that work.”

<b>Clear boundary:</b> DOMOVOY can recommend, investigate and coordinate, but <b>the user chooses the home</b> and approves external contact. Don't claim it guarantees “the best deal.”

## 2. What we're building

<b>Product form:</b> A reusable, open-source <b>Agent Skill</b>, installed into an existing agent (target: Claude Code). Not a new standalone AI agent or property portal.

<b>Two connected capabilities:</b>

1. <b>Prepare / Research:</b> Acquire available listings using Apify; normalize and deduplicate; evaluate criteria and known costs; publish a shortlist in Notion with links, uncertainty, and context.
2. <b>Act / Coordinate:</b> User selects <b>Interested</b>; DOMOVOY gets context and approved calendar windows, contacts a <b>consenting demo realtor</b>, handles an alternative proposal, and updates Notion/Calendar based on the <i>actual</i> outcome.

<b>Design principle:</b> Python / scripts perform predictable processing; an agent handles open-ended investigation and conversation. The Skill contains the instructions, tool contracts and workflows; connected services do the real work. <b>Always-on cron/VPS monitoring is the longer-term direction</b>, not a prerequisite for the 18:00 demo.

## 3. Golden demo — one approval, one conversation, one result

<b>Suggested demo length:</b> Approximately 2–3 minutes if allowed; also rehearse a 60–90 second version because the organizers have not published exact per-team demo time.

### Prepared before walking onstage

- <b>Vladimir's actual search profile</b> and a small shortlist of real, recent listings already collected and evaluated by DOMOVOY.
- A <b>Notion board</b> showing property photo/link, rent, estimated monthly total, upfront cash, reasons for matching, uncertainties, and status. Show listing <b>source and collection time</b>.
- At least one candidate selected for the call demonstration. The call participant uses a <b>clearly labeled demo realtor role</b>; do not imply a fake call has reached the actual owner or listing agent.
- A tested phone number, consent from the participant, reachable phone, calendar test account, and fallback email exchange.

### Onstage sequence

1. <b>0:00 — Human story.</b> “Here is Vladimir's real flat-hunting shortlist. DOMOVOY prepared it from property portals and his preferences.”
2. <b>0:15 — Show the result, not the plumbing.</b> Open one Notion property, briefly highlight the real monthly cost, upfront cash (first rent + refundable kauce + any agency fee), and an uncertainty worth asking about.
3. <b>0:35 — User decides.</b> Vladimir sets <b>Interested</b> and explicitly approves requesting a viewing. If the workflow doesn't automatically wake on Notion changes, invoke the agent live and be transparent about the trigger.
4. <b>0:50 — Agent takes over.</b> DOMOVOY loads the property and user context, checks available calendar windows, and initiates a <b>live outbound voice call to a consenting participant</b> playing the realtor.
5. <b>1:10 — Unscripted challenge.</b> The participant proposes a different time or reveals an additional monthly cost. The agent must respond using the configured preferences and availability—not a hardcoded script.
6. <b>1:50 — Visible outcome.</b> If the proposal is accepted and within approved constraints, write a <b>test viewing</b> to Calendar and update Notion to <b>Viewing booked (demo)</b>. If the new cost violates a hard budget or confirmation is unclear, show <b>Needs Vladimir's approval</b> instead of falsely claiming a booking.
7. <b>2:20 — Reveal the product.</b> “You can install the same open-source skill into your own agent. We demonstrated renting today; the workflows can be extended to other real-estate tasks.”

<b>Hero moment:</b> The agent adapts to a <i>new condition in a real conversation</i> and produces an appropriate, verifiable action. This is much more compelling than simply showing that it can place a call.

<b>Honesty:</b> Use a real listing as the <b>research example</b>, but a <b>consenting simulated realtor</b> for the calling test. Test Calendar events and test email replies must be marked demo/test. No fake claim of a real viewing secured.

## 4. What must work vs. what is optional

### Essential for Friday, Nov 13

- [ ] DOMOVOY Skill loads in <b>one agent client</b> and performs a defined rental workflow.
- [ ] At least <b>one real Apify-backed listing source</b> returns usable property data, with preserved source links and timestamps.
- [ ] Basic parsing, normalization, deduplication, deterministic hard filters and <b>monthly vs. upfront cost</b> calculation work on real examples.
- [ ] A Notion shortlist is written/read with status <b>Interested / Not interested / Need info</b>, and the agent retrieves the selected property accurately.
- [ ] Calendar availability is read correctly; agent uses it to form viewing proposals.
- [ ] A working <b>approved action path</b> exists: either outbound call (target) or Gmail inquiry and reply (fallback).
- [ ] The resulting Notion state and Calendar event are accurate and visible, without misleading confirmation claims.
- [ ] Entire demo has been rehearsed live; a labeled cached listing snapshot is available if scraping fails.

### Show if working (high-value stretch)

- [ ] Voice agent actually calls, asks questions, handles an alternative time/cost, and writes structured call outcome.
- [ ] PostHog captures at least one useful end-to-end trace: triggered action, LLM/tool steps, latency, cost, success/failure.
- [ ] Two or three portals, with cross-source deduplication.
- [ ] Process a real <b>test-mailbox</b> reply, not just create a draft.
- [ ] A compact questions-for-viewing checklist tied to the property's specific uncertainties.

### Explicitly outside Friday's scope

- Long-running VPS service / full autonomous three-month watcher.
- A custom website/dashboard in addition to Notion.
- New custom MCP orchestration server, multi-agent platform or complex permissions.
- Real outbound calls to unaware realtors, automated financial commitments, or actual property bookings without authorization.
- Universal buying/selling/property management flows, complex geo intelligence, full cadastral verification, and autonomous self-modifying skills.
- A guaranteed “best deal” ranking or precise ownership/legal conclusions from incomplete listings.

## 5. Sponsor fit — demonstrate real usage, not name-dropping

| Sponsor | Role in DOMOVOY | What to visibly show |
| --- | --- | --- |
| <b>Apify</b> — core | Listing acquisition through an Actor and structured dataset | Real dataset records, source portal and collection timestamp; a small live Actor run only if fast |
| <b>Featherless AI</b> — optional but valuable | Open-weight model for bounded extraction, Czech-language classification, or structured call-summary analysis | One real model call with validated structured output; only if API access works |
| <b>PostHog</b> — recommended | AI observability / decision traces, time/cost per investigation and result status | One trace connected to the actual demo workflow; special-prize rules must be confirmed |
| <b>PangeAI</b> — thematic relevance | Geo / location intelligence as a future enrichment concept | Do <b>not</b> claim an integration without verified access; simple OSM/transport fact is enough |
| <b>Tensor Ventures</b> — judge lens | Genuine problem, repeatable product, evidence of value | A clear real-user story and realistic extensibility |
| [<b>prg.ai</b>](http://prg.ai)<b> / Dny AI</b> — ecosystem | Local Czech relevance and usefulness outside the tech community | Prague-specific story, accessible Notion workflow, honest limits |

<b>Not a hackathon sponsor, but needed for the hero call:</b> ElevenLabs voice agent plus a supported outbound telephony provider (e.g., Twilio), if configured and tested. Keep the voice agent's tools narrow: property context, approved availability windows, call-result submission. No general filesystem access, credentials, or arbitrary agent tools.

<b>Sponsor decision rule:</b> Apify is core. PostHog is lightweight differentiation if traces are working. Featherless is worth using for a specific bounded task, not as an artificial second brain. Sponsor integration should never block the golden workflow.

## 6. Connections and demo assets checklist

| Dependency | Required setup / evidence |
| --- | --- |
| <b>Agent host</b> | Claude Code + installed DOMOVOY skill + ability to execute bundled scripts |
| <b>Apify</b> | Account, usable Actor(s), key, small result cap, real property record, cached fallback |
| <b>Notion</b> | Accessible property database/template, agent integration permissions, stable ID and status fields |
| <b>Google Calendar</b> | Test calendar with known availability, read permission, create-event permission, selected timezone |
| <b>Calling path</b> | ElevenLabs agent, actual outbound telephony configuration, callable number, participant's explicit consent, quiet audio setup, tool/webhook to return structured call results |
| <b>Email fallback</b> | Authorized Gmail test mailbox, draft/send ability with approval, a second controlled mailbox for live reply |
| <b>PostHog</b> | Project key and one end-to-end instrumentation path if feasible |
| <b>Featherless</b> | Usable API key/model ID only if the chosen classification task needs it |
| <b>Demo content</b> | Vladimir-approved real criteria/listings; one example with a meaningful trade-off; source URLs; labeled test scenario; alternate proposed time |

<b>Data safety:</b> Do not expose real landlord contact details or private addresses unnecessarily on a projected screen. Treat scraped listing text and call content as <b>untrusted data</b>, never executable instructions. Obtain approval for contact actions. Avoid recording or retaining a demo participant's voice without their informed consent.

## 7. Minimal technical implementation

<b>Skill package:</b> [SKILL.md](http://SKILL.md), rental workflow instructions, property schema/reference, provider instructions, scripts for fetching/normalizing/deduplicating/evaluating/cost math, Notion/Calendar/communication adapters, configuration example, and a few tests.

<b>Single coherent path:</b>

Search profile → Apify dataset → normalized property records → deterministic evaluation/cost facts → Notion shortlist → user-approved selection → agent conversation → structured call result → Notion status + test Calendar event.

<b>Non-negotiable data contract for the voice result:</b> property ID, call target (test participant), property availability, proposed/confirmed date-time with timezone, questions answered, newly discovered costs, outcome (confirmed / declined / alternative / needs approval), and evidence/call reference. Never convert “suggested time” into “confirmed viewing” without explicit agreement.

<b>No new standalone agent backend required.</b> If a webhook or small relay is needed for a voice-tool callback, keep it minimal. The goal is interoperable skills and deterministic actions, not a universal framework.

## 8. Day-of build order — work backwards from the demo

<b>09:00–11:30:</b> Validate the real user story; ask organizers about prebuilt code and exact demo time; verify sponsor access; find a willing demo realtor; assign responsibilities.

<b>11:30–12:30:</b> <b>Test the hardest path first.</b> One known property → outbound test call → alternative suggestion → structured result → test Calendar/Notion update. If telephony fails or requires too much setup, switch to the test-email path immediately.

<b>12:30–14:30:</b> Integrate one real Apify source, normalization, deterministic filters/costs, and Notion property records.

<b>14:30–16:00:</b> Wire the installed skill to the completed golden path; add real approval/decision handling and demo-friendly output. Add one useful PostHog trace if the primary flow is stable.

<b>16:00–16:30:</b> Optional sponsor enrichment / UI polish only; no ambitious new feature.

<b>16:30–18:00:</b> Feature freeze; rehearse a 2–3 minute version and a short version, test audio/network/calendar, prepare clearly labeled fallback and failure handling. Demos start at <b>18:00</b>.

<b>Suggested split if two builders:</b> A = Apify, normalized data, Notion, cost/evidence. B = skill + Calendar + voice/email + end-to-end demo. Integrate through one agreed property schema early; both own verification.

## 9. How we know we've succeeded

<b>Required proof:</b> A real renter's requirements and real portal data produce an explainable shortlist; the renter approves one option; the agent performs a genuine communication workflow; the outcome is reflected accurately in Notion and (if confirmed) the test Calendar.

<b>Bonus proof:</b> The agent handles an <i>unexpected</i> change (proposed time or fees) without violating the user's hard constraints, and PostHog shows what happened.

<b>Judging story:</b> Real person → working AI action → understandable for ordinary people. The skill/repo is the technical reveal, not the opening.

<b>Closing line:</b> “DOMOVOY doesn't pick your home for you. It does the searching and coordination, so you can focus on choosing one.”

## 10. Open decisions before Friday

- [ ] Confirm Vladimir's real search criteria, permission to use his examples, and one suitable listing.
- [ ] Confirm one <b>third person</b> is available at demo time to answer the test phone call.
- [ ] Confirm outbound phone capability and minutes/credits; test it before spending time on presentation polish.
- [ ] Decide exact approval semantics: <b>Interested</b> means “investigate/draft,” while a separate action authorizes <b>contact</b> (recommended).
- [ ] Check official rules on preexisting code/seeded data; disclose preparation honestly.
- [ ] Confirm which first listing source works, and whether Featherless / PostHog credentials are available.
- [ ] Agree on the phone-to-email fallback cut-off during the build.

---

<b>Decision update — 11 Nov 2026:</b> Replaces the earlier draft-first demo with a <b>prepared Notion shortlist + live coordination hero moment</b>. Phone negotiation is the preferred experience, <b>not yet a tested or guaranteed integration</b>. The previous scope remains the fallback and longer-term vision, not a second project.

<b>Decisions locked — 12 Nov 2026 (Danila, after prep call with Vladimir):</b>

- <b>Name: DOMOVOY — locked.</b>
- <b>Voice: ElevenLabs Conversational AI agent, NO Twilio.</b> ElevenLabs sells no phone numbers — a real PSTN outbound call needs Twilio/SIP, which Danila does not have. So the live call is a <b>WebRTC / in-browser live voice conversation</b>: the ElevenLabs agent talks via laptop speakers/mic, the consenting demo realtor answers live in the room (or on a second laptop), unscripted. Agent tools return a structured call result (property, proposed/confirmed time, new costs, outcome) to Claude, which updates Notion + Calendar. Fallback if voice fails: drafted Czech inquiry by email (Vladimir final flow).
- <b>Division: Vladimir = Apify (own actor + LLM price extraction). Danila = voice agent (ElevenLabs).</b> Both plug into one Claude Code agent with the DOMOVOY skill, which launches the whole pipeline.
- <b>Interested = may contact.</b> Marking a flat Interested authorises DOMOVOY to contact the realtor.
- <b>Success = a confirmed test viewing in the Calendar</b> (plus Notion status updated). An approved draft alone is not success.
- <b>Flat criteria: decide later, not blocking.</b> Example brief from Vladimir final flow (2+kk Vinohrady, max 30,000 Kč/mo incl. utilities, elevator, nájem only) is an example, not locked.
- <b>Featherless eval (label \~20 listings): DEFERRED.</b> Do not do it before the hackathon. Decide on the day based on what sponsors give / what access works.
- <b>PostHog + PangeAI: interesting, optional.</b> Use only if time remains after the golden demo works; PostHog for traces, PangeAI for commute/location enrichment (real travel time to work/school, not just distance).

[Hackathon event details](https://lu.ma/6rgvg844) · [Parent project notes](https://app.notion.com/p/41396f068f898055bbf4d370b51d72b9)

## Voice build — locked 12 Nov 2026 (Danila)

- <b>Call language: English</b> (not Czech). Same laptop for the whole demo.
- <b>Phone UI: iPhone-style incoming-call page.</b> A web page (Next.js, deploy on Vercel for testing, run locally for the demo) that looks like a phone call: incoming-call screen with the flat address, Accept / Decline, then in-call screen with timer, waveform and live transcript. Claude Code triggers it; the agent speaks, the demo realtor answers live in the room on the same laptop mic/speakers.
- <b>API key: create a key with ElevenAgents → Write (minimum viable).</b> That is the Conversational AI permission. Do NOT put the key in frontend code. Server route /api/get-signed-url (key in .env, server only) returns a signed URL (valid 15 min); the browser starts the session with that URL + agent\_id. Agent Security tab: allowlist the Vercel domain + [localhost](http://localhost).
- <b>Trigger chain (agreed):</b> Vladimir Apify pipeline → context file (call\_context.json) → Claude Code reads it, prepares the call → opens the phone-UI page → page gets a signed URL → ElevenLabs agent starts with dynamicVariables = the context → agent talks, calls submit\_call\_result → result returns to Claude Code → Claude Code sends the confirmation email (Gmail) and creates the Calendar event (Vladimir connects his calendar). The ElevenLabs agent itself does NOT touch Gmail/Calendar directly.
- <b>Agent tools: submit\_call\_result only (+ built-in end\_call).</b> No live Google Calendar MCP during the call — free windows are passed in as dynamic variables before the call.
- <b>PostHog: optional trace only</b> (conversation start, tool call, outcome), if time remains after the golden demo works.

## Final locked plan — 12 Nov 2026, evening (all decisions)

This is the consolidated plan. Earlier open decisions in §10 are resolved by this section unless marked open below.

- <b>Name: DOMOVOY — locked.</b>
- <b>Product: reusable open-source Agent Skill in Claude Code.</b> Not a standalone agent or portal.
- <b>Flow: Research (Apify) + Act / Coordinate (voice).</b> Vladimir: own Apify actor from scratch + LLM extraction of all prices from listing text (rent, kauce, energy, commission, move-in date, provision, missing-furniture cost) into aggregated structured data. Danila: ElevenLabs voice agent. Both plug into one Claude Code agent, which launches the whole pipeline.
- <b>Voice: ElevenLabs Conversational AI agent, NO Twilio, no real PSTN call.</b> ElevenLabs sells no phone numbers. Live call = WebRTC / in-browser live voice conversation: agent talks via laptop speakers/mic, consenting demo realtor answers live in the room, unscripted, in English.
- <b>Phone UI: iPhone-style incoming-call web page.</b> Next.js page, Vercel for testing, run locally for the demo, same laptop for the whole demo. Incoming-call screen (flat address, Accept / Decline) → in-call screen (timer, waveform, live transcript) → result / receipt frame. Claude Code triggers it.
- <b>Ringtone (fun / interaction): Nokia 3310 classic monophonic ringtone</b> — [https://www.youtube.com/watch?v=pe1ZXh5\_wk4](https://www.youtube.com/watch?v=pe1ZXh5_wk4) — plays on the incoming-call screen. Extract the audio for the page during the build.
- <b>API key: ElevenAgents → Write (minimum viable, Conversational AI permission).</b> Key server-only in .env, never in frontend. Server route /api/get-signed-url returns a 15-min signed URL; browser starts the session with signed URL + agent\_id. Allowlist Vercel domain + [localhost](http://localhost) in the agent Security tab.
- <b>Trigger chain:</b> Apify pipeline → call\_context.json (property\_id, address, url, rent, total\_monthly, upfront, kauce, commission, move\_in\_date, nájem/podnájem, missing\_furniture\_cost, user\_name, budget\_cap, available\_windows, competing\_flat\_price, realtor\_name) → Claude Code reads it → opens phone-UI page → page gets signed URL → ElevenLabs agent starts with dynamicVariables = context → agent talks, calls submit\_call\_result → result returns to Claude Code → Claude Code sends Gmail confirmation + creates Calendar event.
- <b>Agent tools: submit\_call\_result only (+ built-in end\_call).</b> No live Google Calendar MCP during the call; free windows are passed in as dynamic variables. Agent does NOT touch Gmail/Calendar directly.
- <b>Interested = may contact.</b> Success = a confirmed test viewing in the Calendar (+ Notion status updated). An approved draft alone is not success.
- <b>Flat criteria: decide tomorrow, not blocking.</b> Example brief (2+kk Vinohrady, max 30,000 Kč/mo incl. utilities, elevator, nájem only) is an example, not locked.
- <b>Featherless eval (label \~20 listings): DEFERRED.</b> Decide on the day from what sponsors give / what access works.
- <b>PostHog + PangeAI: interesting, optional.</b> Only if time remains after the golden demo works. PostHog = traces of the conversation; PangeAI = real travel time to work/school, not just distance.
- <b>Calendar: Vladimir connects his own calendar.</b> Gmail confirmation from the test mailbox, decided on the day.
- <b>Build order (later, not tonight):</b> phone-page skeleton → ElevenLabs agent setup → Claude Code connection. Agreed 12 Nov evening.

### Still open (small, for tomorrow morning)

- Who plays the demo realtor? (Vladimir is the user who approves; the realtor should be a third person, or roles switch — decide at 9:30.)
- Which exact flat / listing is the demo flat, and what are Vladimir’s real criteria?
- Exact demo length per team — confirm on arrival; rehearse both the 60–90s and the 2–3 min versions.
- Official rules on prebuilt code / seeded data — ask at the 10:00 opening, disclose honestly.
- Which test mailbox for the Gmail confirmation.
- Featherless / PostHog credentials — check on the day.
- Audio setup in the room (mic / speakers / feedback) — test the voice path first, 11:30–12:30, before polishing.
- ElevenLabs agent details to build later: voice choice, exact first message, agent\_id.

## Update — 12 Nov 2026, 23:26 (Danila: closing the open list)

This update supersedes the “Still open” list in the Final locked plan above. Most items are now closed as non-blocking.

- <b>Who plays the demo realtor: does not matter.</b> Decide between Danila and Vladimir on the day.
- <b>Which flats / criteria: does not matter for the build.</b> Vladimir chooses the flats and prepares all the data; the voice part does not depend on which ones.
- <b>Exact demo length: unknown.</b> Clarify on site tomorrow.
- <b>Prebuilt-code rules: none.</b> There is no code now, only this plan — nothing to disclose as prebuilt.
- <b>Gmail mailbox for confirmation: probably not needed now.</b> Leave as a TODO if time remains; decide then.
- <b>PostHog / Featherless credits: OPEN, unknown yet.</b> Decide later, on the day.
- <b>Audio in the hall: non-issue.</b> Figure it out on site; nothing complex expected.
- <b>Agent details: to choose during the build.</b> Voice, persona / personality of the agent, first message — Danila picks these when building the agent.

### How the call works — final staging (Danila, 12 Nov evening)

- <b>The phone page is a standalone HTML page that just sits and waits.</b> It does not do anything until Vladimir’s Claude agent sends a request: “make a call, find out X and Y” (the call\_context for one flat).
- <b>Nobody presses anything to start the call.</b> The incoming call just appears on the page, the Nokia 3310 ringtone plays, someone answers, and it looks like a conversation on an iPhone. Add something visually interesting to the in-call screen if time allows.
- <b>Honest framing to the audience:</b> we have no phone number because we did not want to really call people — we want to show how it works, on the website. The conversation itself is live and unscripted: the agent asks questions, the person answers, the agent says “OK, saved” etc.
- <b>After the conversation ends, the agent sends the data to Claude.</b> Claude saves it and does everything else (Notion update, Calendar event, Gmail confirmation if used).
- <b>Build later (agreed):</b> phone-page skeleton → ElevenLabs agent setup → Claude Code connection. Nothing is built yet tonight.

<page url="https://app.notion.com/p/41796f068f898149b99de7f040ea4280">
Judge / Critic — How DOMOVOY Will Be Judged
</page>

<page url="https://app.notion.com/p/41796f068f8981f7883cf219b543c480">
Lane 3 — PostHog Self-Driving Loop (Mac mini)
</page>

## Repo, links & day-of hub — 13 Nov 2026

Added on the morning of the hackathon. This section is the single entry point: repo, submission rules, subpages, and everything decided on the day. The full proposal and demo flow above still stands; this section only adds what was missing or changed.

### Repo — submission repo

- <b>GitHub: </b>[<b>https://github.com/Skilux/domovoy</b>](https://github.com/Skilux/domovoy)
- Created 13 Nov 2026. Empty as of 10:44 — no README, no code yet. All build work today goes here.
- This is the repo to put on the submission form. The form needs two links: <b>GitHub + a demo or a site</b>.

### Demo + submission rules — confirmed on site, 13 Nov morning

- <b>Demo: 3 minutes, hard stop.</b> This supersedes the “exact demo length: unknown, clarify on site” note in the 23:26 update above. Rehearse the 60–90 s cut as well as the full 3:00.
- <b>Demos 18:00, winners 19:45.</b> Live demo only — no pre-recorded videos.
- <b>Rules: Don’t cheat. Build it all here.</b> Core built during the hack; generic scaffolds / wrappers prepared beforehand are fine — say what was prebuilt if asked.
- Submission form: put the GitHub link + demo / site link on the form.

### Subpages (already linked at the end of this page)

- <mention url="https://app.notion.com/p/41796f068f898149b99de7f040ea4280">Judge / Critic — How DOMOVOY Will Be Judged</mention> — the hill-climb metric: the event’s 3 published criteria as a 25/25/20/15/15 weighted /100 rubric, 7 pass/fail gates, 10 harsh judge questions, checkpoint self-scores.
- <mention url="https://app.notion.com/p/41796f068f8981f7883cf219b543c480">Lane 3 — PostHog Self-Driving Loop (Mac mini)</mention> — the third lane for the Mac mini (decided by the PostHog contact in the room): signals → report → human yes/no → measured change, for renters and for agencies. 60 seconds inside the 3-minute demo, 1:30–2:30.
- Vladimir’s final demo-flow page (his workspace, not shared with Danila’s Notion): <mention url="https://app.notion.com/p/416cfb472cbd808f9676f94720ddfe2e" /> — example brief 2+kk Vinohrady, max 30,000 Kč/mo incl. utilities, elevator, nájem only.
- Event page: [https://aihackclub.com/hackathon/ai-agents-for-the-rest-of-us-an-interdisciplinary-hackathon-by-a-2026-11/](https://aihackclub.com/hackathon/ai-agents-for-the-rest-of-us-an-interdisciplinary-hackathon-by-a-2026-11/) — schedule, prizes, judging criteria. Registration: [lu.ma/6rgvg844](http://lu.ma/6rgvg844).

### Locked plan — one-paragraph recap

DOMOVOY: tell your existing AI agent what home you need. Research (Apify) + Act / Coordinate (voice). Vladimir builds his own Apify actor from scratch (own schema, LLM extraction of rent / kauce / energy / commission with verbatim quotes). Danila does voice via ElevenLabs Conversational AI — live WebRTC conversation in the browser, NO Twilio (ElevenLabs sells no phone numbers), English, one laptop, iPhone-style incoming-call page, Nokia 3310 ringtone, consenting demo realtor answers live in the room. Trigger: pipeline → call\_context.json → Claude Code → phone page → ElevenLabs agent with dynamicVariables → submit\_call\_result → Claude Code sends Gmail confirmation + creates Calendar event on Vladimir’s calendar. Agent does NOT touch Gmail / Calendar directly. Interested = may contact. Success = a confirmed viewing in the Calendar. Honest framing on stage: no phone number, because we did not want to really call people — the conversation itself is live and unscripted.

### Workshop resources — 13 Nov morning (QRs decoded from photos)

- <b>Featherless — \$25 credits:</b> redeem at [https://featherless.ai/join/feather\_request\_pricing/AIT2026?amount\_usd=25](https://featherless.ai/join/feather_request_pricing/AIT2026?amount_usd=25) — code AIT2026. Create an account at [featherless.ai](http://featherless.ai), API key from the dashboard, 40K+ open models, OpenAI-compatible at [https://api.featherless.ai/v1](https://api.featherless.ai/v1). Use: the bounded fee-extraction job.
- <b>Apify Actor dev skill:</b> [https://github.com/apify/agent-skills/tree/main/skills/apify-actor-development](https://github.com/apify/agent-skills/tree/main/skills/apify-actor-development)
- <b>Apify Orchestrator dev skill:</b> [https://github.com/apify/awesome-skills/blob/main/skills/apify-orchestrator-actor-development/SKILL.md](https://github.com/apify/awesome-skills/blob/main/skills/apify-orchestrator-actor-development/SKILL.md)
- <b>PostHog — “Hog takes the wheel”:</b> signals flow in on their own, agent groups them, it digs in or honestly drops it, it drafts the fix, your job is say yes or no. PostHog self-driving docs: [https://posthog.com/docs/self-driving/](https://posthog.com/docs/self-driving/)

### Day-of checkpoints — score it, don’t feel it

| Time | Must be true | Cut first if not |
| --- | --- | --- |
| 11:30 | Build starts. Scope locked: one brief (Vladimir), one shortlist, one call, one receipt. | Extra features: commute, sun side, pub density, map dashboard — V2 |
| \~14:00 | Research pipeline end to end on real listings, shortlist in Notion with source + time. PostHog capture on for core events. | Featherless eval, PostHog dashboards, extra portals |
| \~16:00 | One full live call rehearsed end to end, with a “no / alternative” branch, Calendar receipt appearing. | Voice persona polish, ringtone extras, in-call visuals |
| 17:00–17:45 | Code freeze. Full dry run in hall conditions. 60–90 s cut rehearsed. Fallback ready: if the call fails live, show the last successful call trace + receipt and say so. | Any new code |
| 17:45 | Go / no-go. All gates in the Judge subpage ticked. | — |
| 18:00 | Demo, 3:00 hard stop: 0:00–0:15 problem, 0:15–1:30 live loop, 1:30–2:30 Lane 3 (PostHog), 2:30–3:00 agency close + links. | — |

### Submission checklist

- [ ] Code in [https://github.com/Skilux/domovoy](https://github.com/Skilux/domovoy) (README with what it does, how to run it, what was built today)
- [ ] Demo / site link (phone page / Vercel) — put on the form with the GitHub link
- [ ] Demo rehearsed to 3:00 hard stop, 60–90 s cut ready
- [ ] Judge subpage self-score filled in at 17:45
- [ ] Lane 3: one real PostHog signal + one approved fix shown live
