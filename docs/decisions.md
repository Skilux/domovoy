# Decisions

Three layers. The first table reconciles conflicts between the five supplied exports. The second records decisions Danila made on 13 Nov 2026 before the PRD; they override both the exports and the first table. The third records the Actor PRD decisions Vladimir made on 13 Nov 2026; they override everything above, including the switch from the GitHub board back to Notion. Open questions live in [open-items.md](open-items.md).

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

## Actor PRD decisions, 13 Nov 2026

Made by Vladimir while specifying the Actor lane ([prd/actor.md](prd/actor.md)). They override the pre-PRD rows they name.

| Topic | Decision | Replaces |
| --- | --- | --- |
| Shortlist UI | Notion database **DOMOVOY shortlist**, one page per flat, keyed by `Property ID` | GitHub Issues on a Projects board |
| Workflow state | Notion `Status` select only, same six values; the Actor sets `Shortlisted` on page creation only | Board `Status` field |
| Rejection reason | Notion `Reason` text, typed by Vladimir | Board `Reason` field |
| Shortlist writer | The Apify Actor writes Notion pages directly; it owns only its own properties and writes the page body once | Skill script creates issues from `shortlist.json` |
| Notion setup and auth | `notion.py setup` creates the database from `notion_contract.json`; internal integration "DOMOVOY", `NOTION_TOKEN` in `.env` and as an Apify secret input; the Actor validates the schema and never changes it | `gh` token with `project` scope; board created by hand |
| Call summary | Claude appends it to the Notion page body | Issue comment |
| `call_context` | `issue_number` (int) replaced by `notion_page_id` (string); all other fields unchanged | `issue_number` |
| Pipeline location | Scraping, extraction, normalize, dedup, requirements and cost math all run inside the Actor; the skill keeps `search.py` (start run, poll) and `notion.py` | `pipeline.*` skill script |
| Search criteria | Claude writes search profiles (`filters` + `requirements`, `profile.schema.json`) and stores them in `config.json` as `profiles[]`; `budget_cap` = `requirements.max_total_monthly` | Hard filters and budget cap as flat config values |
| Listing sources | Sreality, Bezrealitky and iDNES are all required by the 17:00 freeze; Bezrealitky before iDNES; 14:00 needs Sreality only | One portal is enough |
| Actor interface | One Actor with a `mode` input (`search`; `katastr_lookup` reserved); Claude starts the run and polls it, no webhook | — |
| Extraction | Featherless with a cache and OpenAI as fallback; no eval, no labeled set | Featherless only |
| Costs | The model extracts, Python computes; energy and missing furniture come from fixed tables and are marked as estimates; `upfront` stays stated costs only, furniture is shown next to it | — |
| Dedup | Heuristic across portals with a stable `property_id` map | — |
| Realtor contacts | Stored only in the private Notion database and the Apify dataset; never in the repo or the cached fallback; hidden in the demo view | Kept out of public GitHub issues |
| Katastr owner check | Phase 2 (`katastr_lookup` mode, WSDP); storing owner names needs compliance sign-off. Superseded by [Katastr check decisions](#katastr-check-decisions-13-nov-2026) | — |
| PostHog from the Actor | Phase 2; the PostHog lane stays P1 | — |
| GitHub Projects board | Team task tracking during the hackathon only; never a DOMOVOY or demo surface | Shortlist UI for DOMOVOY |
| Portal access, all three portals (Sreality, Bezrealitky, iDNES) | 13 Nov 2026, 13:00. Team decision (Vladimir): agent scraping of all three portals is permitted for this hackathon. The organizers allow it, and robots.txt and terms-of-service or content-reuse clauses do not apply for the hackathon. Sreality was first permitted at 12:53 on a verbal OK from a Sreality representative at the hackathon. Still required: at most 3 concurrent requests per portal, a 0.5–1 s delay between requests, and no realtor names, phones or emails in the repo. | The robots.txt Disallow and terms-of-service concerns |

## Call flow decisions, 13 Nov 2026

Made by Danila for the call half of the Skill lane.

| Topic | Decision | Replaces |
| --- | --- | --- |
| Notion switch | Danila accepted the Notion switch and the `notion_page_id` rename, 13 Nov 2026 | Open item 13: review after the merge |
| Calendar access | No calendar script and no Google API setup. Claude reads free windows and creates the test event with whatever calendar access it has; `call.py` takes the windows as input and prints the event to create | Open item 2; `calendar.*` script |
| Shortlist access from `call.py` | Notion only, through one module named in `config.json` (`backend.module`) that lists flats by `Status`, sets `Status` and appends to the page body. `call.py` accepts either naming (`list_pages`, or `list_flats` plus `get_flat`) and adapts to `notion.py`. The modules in `tests/` are local fakes. No GitHub board or issue code anywhere in DOMOVOY | `board.py` over `gh` |
| Call idempotency | The handled `conversation_id` is kept in local `.state/handled.json`; the appended summary also carries a `domovoy-call: <conversation_id>` line. A result seen before changes nothing | Unspecified |
| Receipt order | `call.py` appends the summary and sets `Viewing booked`, then Claude creates the event from the printed `event` | Event first, then status |
| Extra `call_context` fields | `call.py` passes listing fields it does not know through; the phone server accepts them (`phone/lib/context.js` requires only `property_id` and `address`) | Unspecified |

## PostHog lane decisions, 13 Nov 2026

| Topic | Decision | Replaces |
| --- | --- | --- |
| PostHog account | Danila's personal account, free plan only, EU Cloud, project `DOMOVOY` (id 348322). No card, no paid credits | Open item 8, project key |
| Loop on the free plan | Report = PostHog notebook; approval = feature flag `domovoy-criteria-<key>`; memory = decision events plus versions of the stored scout instructions; all through `posthog/loop.py` | Native self-driving scouts and Inbox, which are paid |
| Where an approved change lives | In the feature flag's payload. `search.py` merges approved flags into the profile's `requirements` (issue #43) | Saving the change to the profile in `config.json` |
| Stage timing | `sync` runs before the PostHog minute (after rejections, and in the background at the start of the call command); `report` returns at once when the events are in | A fixed 60 s wait inside the improve command |
| Local event log | None. A report is complete from PostHog or marked incomplete | "A local event log may back up the report" |
| `notion.py` and `call.py` | `scripts/notion.py` (#53) loads through `backend.module` with no change to `call.py`; run on a synthetic Notion test database on 13 Nov 2026 | Open item 14 |

## iDNES source decisions, 13 Nov 2026

Team decision by Vladimir at 13:00, for the iDNES source (WP3). The organizers of this government hackathon, sponsored by the real-estate portals, allow agent scraping of all portals.

| Topic | Decision | Replaces |
| --- | --- | --- |
| robots.txt and portal terms | Do not block the hackathon work. Do not stop on robots.txt or content-reuse clauses; review the terms before any use beyond the hackathon | Stop-and-report on robots.txt or terms (WP3 Phase A brief) |
| iDNES texts and photos | May be used in Notion pages and in scrubbed test fixtures | Open content-reuse question (research note, section 10) |
| `/admin.api/` locality lookup | May be used if it helps Phase B. It is disallowed by robots.txt; the decision above covers it | "Never call `/admin.api/`" (research note) |
| Polite rate | At most 3 requests in flight, 0.5 to 1 s between request starts, one retry on 5xx and network errors, stop on 403 or 429. No proxies, no header or fingerprint spoofing, no stealth, no CAPTCHA solving | — |
| Contacts in the repo | No realtor names, phones or emails in code, fixtures or docs. The repo goes public at 17:30 | — (already a rule in CLAUDE.md) |
| Call trigger | A flat is callable when `Status` = Interested, or when the user's `Interested?` column is Yes and `Status` is still Shortlisted. `call.py` then sets Calling and the final status, so a finished flat is not called again. `Status` stays the only workflow state. Danila, 13 Nov 2026, issue #80 | `Status` = Interested only |

## Call retry decision, 13 Nov 2026

Made by Vladimir at 15:25 for the call-retry ticket. Overrides the Call trigger row above.

| Topic | Decision | Replaces |
| --- | --- | --- |
| Call after a failed call | `Interested?` = Yes makes a flat callable whatever its `Status`, so a retry after a failed demo call goes ahead. `Status` = Interested still makes it callable. A flat stops being callable only when `Interested?` is not Yes and `Status` is not Interested | Call trigger above: the Shortlisted condition, and "a finished flat is not called again" |

## Katastr check decisions, 13 Nov 2026

Made by Vladimir for the katastr check (issue #57, PRs #111 and #113).

| Topic | Decision | Replaces |
| --- | --- | --- |
| Owner names in Notion | Compliance signed off. The Katastr check writes owner and lender names to the flat's Notion page and attaches the LV PDF there. LV files stay in `KATASTR_LV_DIR`, outside any git checkout. Names never go into the repo, commits, cached fallbacks, issues or chat; `katastr.py` prints none | "Storing owner names needs compliance sign-off" (Actor PRD decisions); open item 19 |
| Where the check runs | A skill command, `katastr.py` `locate`, `fetch`, `lookup`, `attach`, documented in `SKILL.md`. Each billed WSDP output (100 CZK per LV extract, XML or PDF) needs its own yes from the user, and the script refuses without `--confirm-billed`. API KN (free) finds the building, units and LVs; it has no owners or encumbrances | `katastr_lookup` Actor mode |
| Easements for a tenant | Someone else's right to live in or use the flat: high. A right of way through the flat, or an easement of unknown kind on it: medium. Utility lines: low, reported only. The building's own LV (land and the house as a whole) is named as not checked unless ordered | — |

## Open items closed, 13 Nov 2026

Moved from [open-items.md](open-items.md) on 13 Nov 2026. Each was settled by merged work, not by a new decision.

| Topic | Decision | Replaces |
| --- | --- | --- |
| Shortlist database | `notion.py setup` was run: the **DOMOVOY shortlist** database exists, and one full Actor run created 22 pages in it ([packaging.md](packaging.md#100-flats-researched)) | Open item 6 |
| Featherless model, threshold, concurrency | Primary model Qwen (`DEFAULT_MODEL` in `apify/domovoy/extraction/llm.py`). An answer with confidence below 0.5 becomes unknown. The plan allows 100 concurrent units, read from the Featherless plan API; the default `llm.concurrency` is in `apify/README.md` | Open item 7 |
| Bezrealitky access | Plain HTTP GET of the page's own server-side JSON (`__NEXT_DATA__` and the `_next/data` route). No GraphQL call and no Playwright. Recorded in `apify/research/bezrealitky.md`; the source is on `main` (PR #61) | Open item 12 |
| Active profile | `active_profile` in `config.json` holds a profile `id`. `call.py` and `doctor.py` read it, and `SKILL.md` tells the agent to set it | Open item 17 |
