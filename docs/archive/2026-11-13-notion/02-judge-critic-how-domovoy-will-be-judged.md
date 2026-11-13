# ⚖️ Judge / Critic — How DOMOVOY Will Be Judged

- **Source:** https://app.notion.com/p/41796f068f898149b99de7f040ea4280?pvs=204
- **Notion page ID:** 41796f068f898149b99de7f040ea4280
- **Last edited in Notion:** 2026-11-13T08:26:05.335Z
- **Exported:** 2026-11-13, from Danila's Notion via the Notion integration

---

<callout icon="⚖️" color="red_bg">
<b>Judge / Critic — how DOMOVOY will be judged, and how to check ourselves against it.</b>

This is our hill-climb metric. If a change does not raise the score below, do not do it today. Score honestly — a 3 is a pass, a 5 is a win, a 0–2 on a gate is a fail no matter how good the rest looks.

Parent page: DOMOVOY — Hackathon Proposal & Demo Flow. Event: AI Tinkerers Prague, “AI Agents for the Rest of Us”, Fri 13 Nov 2026, Apify, Na Příkopě 959/27, Prague. Demos 18:00, winners 19:45. Teams of 2–4. Demo must be live — no pre-recorded videos.
</callout>

## 0. The event's own words — what the judges actually said

Source: official event page, AI Hack Club / Luma — [https://aihackclub.com/hackathon/ai-agents-for-the-rest-of-us-an-interdisciplinary-hackathon-by-a-2026-11/](https://aihackclub.com/hackathon/ai-agents-for-the-rest-of-us-an-interdisciplinary-hackathon-by-a-2026-11/)

<quote>
“At 6pm each team has a few minutes to show their agent working and explain who it's for. Demos have to be live, no pre-recorded videos.”

“What we look at:

1. Does it solve a real problem for a real person? What's your personal insight into the problem?
2. Does it work? What did you learn during the hack from your peers? How well did you use the tools available?
3. Would people outside tech actually use it?<br />and more ;)”

“Judges are from our sponsors and the Prague AI community.”
</quote>

Sponsors / judges' home turf: Apify (web scraping / browser automation), Featherless (serverless inference for open-source models), Tensor Ventures, PangeAI (geospatial intelligence), PostHog (product analytics), [prg.ai](http://prg.ai) x Dny AI.

Prizes: 1st — Bambu Lab A1 3D printer (each member) + \$1,000 Apify + \$300 Featherless; 2nd — Google Fitbit Air + \$500 Apify + \$100 Featherless; 3rd — TEENAGE ENGINEERING PO + \$500 Apify + \$100 Featherless; plus a special PostHog prize and a Mac mini.

Translation: this is NOT a “best code” contest. It is a “real person, real job, working live, usable by a non-tech person” contest — with sponsor tools used visibly well. That is the whole rubric below.

## 1. The score — one number to hill-climb on

Score each criterion 0–5 (whole numbers, like From Dusk Till Dawn did). Weighted total out of 100.

| # | Criterion | Weight | What it means for DOMOVOY | 0 = fail | 3 = pass | 5 = win |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Real problem, real person | 25% | Vladimir, a real teammate, really looking for a flat in Prague. Real brief, real listings, real pain between finding a listing and getting a viewing. | Invented user, generic “renting is hard” | Real person named, real criteria, but demo uses made-up listings | Judge can retell it in one sentence: “Vladimir hates chasing realtors — DOMOVOY does it, he just approves.” Personal insight is visible |
| 2 | Does it work — live, end to end | 25% | Research (Apify) → shortlist in Notion → Interested → live ElevenLabs voice conversation → confirmed viewing in Calendar + Notion updated. All live at 18:00, no video, no slides-as-demo. | Demo crashes, or only slides / a video / a mock | Main loop works once, with a small manual step the audience can see | Full loop works unscripted: new question from the realtor, agent adapts, receipt appears in Calendar |
| 3 | Would people outside tech use it? | 20% | A non-tech renter could use it tomorrow with no setup, no code, no prompt engineering. They talk / click Interested, approve, get a viewing. | Only Danila / Vladimir can run it; needs terminal, keys, setup | A non-tech person could follow it with help | A judge's non-tech friend would get it in 30 seconds and trust it with a real viewing |
| 4 | Agent quality + tools used well | 15% | Apify does the real scraping, ElevenLabs does a real live conversation, Featherless / PostHog / PangeAI used where they actually help — not as logos. Learning from peers / workshops is named. | Chatbot wrapper, fake data, sponsor names on a slide | Real tools, real data, one sponsor used well | Each tool does a job nothing else could do; the team can say what they learned from Apify / Featherless / PostHog workshops |
| 5 | Demo clarity + wow | 15% | 2–3 min (60–90 s version rehearsed). Problem in 15 s, working loop in the middle, receipt at the end. The live call is the wow — Nokia ringtone, iPhone-style incoming call, unscripted answers. | Audience does not know what it does after 60 s | Clear story, demo works, ending is visible | Room remembers one moment the next day — the live call, the Calendar event appearing |
|  | <b>Total</b> | <b>100%</b> | <b>Score = (C1×5 + C2×5 + C3×5 + C4×3 + C5×3) — i.e. sum of weighted 0–5 scores × 5</b> | <b>\< 50: not competitive</b> | <b>60–74: solid, could place</b> | <b>75+: winning shape</b> |

How to use it: score at each checkpoint in §5. Do not average away a gate failure — see §2.

## 2. Gates — pass / fail, no partial credit

If any gate fails at 18:00, the weighted score does not matter. Check these first.

- [ ] <b>Live, not recorded.</b> No pre-recorded video as the demo. The call happens live in the room.
- [ ] <b>Real listings, real source + time.</b> Every flat shown has a portal, a link, and a collection time. No invented rent, kauce, or fees. Uncertainties are shown, not hidden.
- [ ] <b>One human approval before contact.</b> Nothing contacts a realtor without the user marking Interested / approving. Say this out loud in the demo.
- [ ] <b>Honest about the call.</b> Say it plainly: no phone number, no Twilio — this is a live WebRTC voice conversation in the browser, on one laptop. The demo realtor is consenting and labelled as a demo role. Do not imply a real PSTN call to a real realtor.
- [ ] <b>A verifiable receipt.</b> Success = a confirmed viewing in the Calendar (plus Notion updated, Gmail confirmation if used). If the call ends in “no” / “alternative proposed”, show that outcome honestly — a real “no, but here is the alternative” beats a fake “yes”.
- [ ] <b>No prerequisites for the audience.</b> The demo needs nothing from the judges: no install, no account, no code, no setup. It works on the laptop on stage.
- [ ] <b>Built today, disclosed honestly.</b> Core built during the hack. Generic scaffolds / wrappers prepared beforehand are fine — say what was prebuilt if asked. Do not claim a finished product was built in a day.

## 3. What good / bad looks like — DOMOVOY examples

### Criterion 1 — Real problem, real person

- <b>Excellent (5):</b> “Vladimir is looking for a 2+kk in Vinohrady, max 30,000 Kč/mo incl. utilities, elevator, nájem only. He has 3 real candidates. The pain is not finding them — it is the 20 minutes per listing of checking kauce, energy, commission, and chasing a reply.” The brief is his, in his words.
- <b>Pass (3):</b> Real person, real brief, but the demo flat is a generic example.
- <b>Fail (0–1):</b> “Renting in Prague is hard for everyone.” No named person, no real criteria, no real listings.

### Criterion 2 — Does it work?

- <b>Excellent (5):</b> Apify pipeline pulls 3 portals, dedupes, extracts rent / kauce / energy / commission with verbatim quotes; shortlist in Notion; live call asks about move-in date and furniture, handles an alternative, Calendar event appears while the audience watches.
- <b>Pass (3):</b> Pipeline + shortlist + call all work, but one step is pre-run and shown as a screenshot.
- <b>Fail (0–1):</b> Call is scripted word-for-word, or the “agent” is a human typing, or the demo needs a restart mid-way with no fallback.

### Criterion 3 — Outside tech

- <b>Excellent (5):</b> “Tell your agent what home you need. It researches, you pick Interested, it arranges the viewing.” A non-tech renter could do that. Czech inquiry draft is in correct Czech, costs are in Kč, upfront cash is shown as one number.
- <b>Pass (3):</b> Understandable, but the user has to understand Apify / Notion / Calendar plumbing to trust it.
- <b>Fail (0–1):</b> Demo is a terminal, a JSON file, and “you just run this Claude Code skill”. A non-tech person would never touch it.

### Criterion 4 — Agent + tools

- <b>Excellent (5):</b> Apify actor built from scratch with its own schema + LLM price extraction; ElevenLabs agent with tools returning structured results to Claude; Featherless eval or PostHog observability actually used and shown (even briefly). Team names one thing learned in a sponsor workshop.
- <b>Pass (3):</b> Apify + ElevenLabs both real and working; other sponsors mentioned but not used.
- <b>Fail (0–1):</b> Sponsor logos on a slide, data hard-coded, agent is a single prompt with no tools, no trace, no recovery.

### Criterion 5 — Demo clarity + wow

- <b>Excellent (5):</b> 15 s problem → 60 s live call → 30 s receipt (Calendar + Notion). One memorable moment: ringtone, incoming-call screen, agent saying “OK, saved” and the viewing appearing. Rehearsed 60–90 s cut ready if time is short.
- <b>Pass (3):</b> Clear, on time, works — but forgettable.
- <b>Fail (0–1):</b> 3 minutes of context before anything moves, or the demo runs over and gets cut off before the receipt.

## 4. The critic — 10 questions a harsh judge will ask (with honest answers)

1. <b>“Is this just a chatbot over Sreality?”</b> — No. The research is a pipeline (Apify, dedupe, cost math, verbatim price extraction). The act is a live voice agent with tools that returns structured results and creates a Calendar event. A chatbot answers; DOMOVOY completes the job.
2. <b>“Did you really call a realtor, or is this theatre?”</b> — Theatre with a live core, and we say so. No PSTN number, no Twilio — ElevenLabs has no numbers. The conversation is live and unscripted in the browser, the realtor is consenting and labelled, the data the agent collects is real and lands in Notion / Calendar. The fake part is only the phone network.
3. <b>“Why English, when Prague realtors speak Czech?”</b> — Demo language is English by lock-in on 12 Nov (one laptop, one demo). The production direction is a Czech inquiry draft + Czech call. Do not pretend the English call is the Czech product.
4. <b>“What if the realtor says no, or proposes another flat / time?”</b> — That is a success case, not a failure. The agent must capture the alternative, return it structured, and let the user decide. Show the “no” path in rehearsal.
5. <b>“Your prices — are they real or hallucinated?”</b> — Real, with source + collection time, and verbatim quotes for extracted fees. Where the listing does not state a fee, show “unknown”, not a guess. That is the Featherless eval idea: hand-label \~20 listings, check extraction.
6. <b>“Would a real user trust an agent to talk to a realtor for them?”</b> — Only with approval. Interested = may contact. The user approves the contact and the viewing. The agent never sends money, never signs, never books without confirmation.
7. <b>“What did you actually build today vs. bring in?”</b> — Core built today: Apify actor, voice agent, phone page, Claude connection. Be ready to name what was scaffold / wrapper beforehand. No finished BytHlídač brought in.
8. <b>“Why should this win over a team that built a full app?”</b> — Theme is “AI Agents for the Rest of Us”. A reusable Agent Skill installed in an existing agent, doing one mundane job end to end for a real person, is the theme — not a new portal.
9. <b>“What happens after the hackathon?”</b> — V2 direction (locked 9 Nov): open-source skill / MCP, self-hostable thin wrapper, providers swappable, reusable for any city. Say it in one sentence; do not demo V2.
10. <b>“What breaks first in the real world?”</b> — Portals change layout, listings go stale, realtors do not answer, Czech language, consent / spam rules for contacting realtors at scale. Name one, do not hide it. Honest limitations scored well at From Dusk Till Dawn (10% of their rubric).

## 5. Checkpoints — score it during the day, not after

Use the table in §1. Fill in the score, not a feeling.

| Checkpoint | Time | What must be true | If not, cut this first |
| --- | --- | --- | --- |
| Build start | 11:30 | Scope locked: one brief (Vladimir), one shortlist, one call, one receipt. Demo script 90 s + 3 min written. | Extra features: commute, sun side, pub density, map dashboard — all V2 |
| Mid-day | \~14:00 | Research pipeline end to end on real listings, shortlist in Notion with source + time. | Featherless eval, PostHog dashboards, extra portals |
| Voice works | \~16:00 | One full live call rehearsed end to end, with a “no / alternative” branch, and the Calendar receipt appearing. | Voice persona polish, ringtone extras, in-call visuals |
| Freeze + dry run | 17:00–17:45 | Code freeze. Full dry run in hall conditions (audio, one laptop, same Wi-Fi). 60–90 s cut rehearsed. Fallback ready: if the call fails live, show the last successful call trace + Notion / Calendar receipt and say so. | Any new code |
| Go / no-go | 17:45 | All §2 gates ticked. Score the §1 table. If C2 is below 3, do the fallback demo, not a new build. | — |
| Demo | 18:00 | Live. Problem 15 s, call, receipt. | — |

## 6. Cross-check — how other hackathons score (so we do not over-fit one page)

The event page gives only 3 criteria + “and more ;)”. Other rubrics are the same five axes, reweighted — useful as a second opinion:

- <b>From Dusk Till Dawn #01 (Prague, Oct 2026 — where Bid Royale won):</b> Value + track relevance 35%, Originality 25%, Working end-to-end result 20%, Technical execution 10%, Validation + honest limitations 10%. Each 0–5. A 3 on everything = 60/100. Note: honesty about what is simulated is scored, not punished.
- <b>Devpost / MLH / ETHGlobal (general):</b> Creativity / innovation, Technical difficulty, Functionality / execution, Impact / real-world use, Design / UX, Presentation. Working demo weighted heavily everywhere; slides alone never win.
- <b>Voice AI buildathons:</b> Usability + friction reduction, Conversation experience, Edge-case handling, Use-case innovation. Judges test with inputs the team has not seen — rehearse the unscripted branch.
- <b>NASA Space Apps:</b> Impact, Creativity, Validity (will it actually work?), Relevance, Presentation.
- <b>Common judge behaviour (field notes):</b> Judges see 30–100 demos, form an opinion in the first \~30 seconds, want something functional on screen within \~90 seconds. Not slides. Not architecture.

If DOMOVOY scores well on §1, it also scores well on all of these. If it scores well only on technical cleverness, it will lose here — this event weights the real person and the non-tech user above technical depth.

## 7. Self-score — fill in live

| Criterion | 11:30 | 14:00 | 16:00 | 17:45 | 18:00 (judges) |
| --- | --- | --- | --- | --- | --- |
| 1. Real problem, real person (25%) | /5 | /5 | /5 | /5 | /5 |
| 2. Does it work — live, end to end (25%) | /5 | /5 | /5 | /5 | /5 |
| 3. Outside tech (20%) | /5 | /5 | /5 | /5 | /5 |
| 4. Agent + tools (15%) | /5 | /5 | /5 | /5 | /5 |
| 5. Demo clarity + wow (15%) | /5 | /5 | /5 | /5 | /5 |
| <b>Total /100</b> |  |  |  |  |  |
| <b>Gates (§2) all pass?</b> | Y/N | Y/N | Y/N | Y/N | Y/N |
| <b>Biggest risk right now</b> |  |  |  |  |  |
| <b>One thing to fix next</b> |  |  |  |  |  |

## Sources

- Event page (judging, schedule, prizes, sponsors): [https://aihackclub.com/hackathon/ai-agents-for-the-rest-of-us-an-interdisciplinary-hackathon-by-a-2026-11/](https://aihackclub.com/hackathon/ai-agents-for-the-rest-of-us-an-interdisciplinary-hackathon-by-a-2026-11/)
- Registration: [lu.ma/6rgvg844](http://lu.ma/6rgvg844)
- From Dusk Till Dawn #01 judging (5 criteria, weights): [https://agents007.ai/hackathon01](https://agents007.ai/hackathon01)
- General rubrics — Devpost / MLH / ETHGlobal / NASA Space Apps, and judge field notes: see research 13 Nov 2026 (Devpost judging tips, Hack the North, LA Hacks, STEM2Connect 5×20% rubric).
- DOMOVOY parent page: DOMOVOY — Hackathon Proposal & Demo Flow (this workspace, last edited 12 Nov 2026, 22:26 UTC).

<i>Created 13 Nov 2026, morning of the hackathon, from the event page + general hackathon rubrics + the locked DOMOVOY plan. The event publishes no numeric weights — the 25/25/20/15/15 split in §1 is our proposal, built to match the event's 3 published criteria in order.</i>
