# Sreality research (WP1, Phase A)

**Status: BLOCKED.** Live verification is paused until the team decides how to handle the site's robots.txt. This file records what is known. Nothing else is verified.

- Date: 13 Nov 2026
- Scope: research only, no source code
- Requests to sreality.cz in this session: one, `GET /robots.txt`. The API details in section 3 are team-reported (docs/prd/actor.md), not verified here.

## 1. Blocker: robots.txt

| Item | Finding |
| --- | --- |
| `robots.txt` (fetched 13 Nov 2026, HTTP 200) | `User-agent: *` followed by `Disallow: /`. Named crawlers have their own groups that allow access (Googlebot, Bingbot, SeznamBot, DuckDuckBot, Applebot and others). Every other client falls under `*`. |
| Our client | Identifies as `DOMOVOY-research/0.1`. It matches no named group, so every path is disallowed for it. |
| `/api/` | Explicitly disallowed for SeznamBot. The Googlebot group has no `/api/` rule, but the `*` rule still applies to us. |
| Czech comment after the `*` group | "neplecha ukončena" (roughly "nuisance ended"). It is a comment, not a directive. We do not read it as permission. |

What this means: the REA browser capture and the API calls in the brief are not run. Any further request to sreality.cz would be automated access that the site's robots.txt disallows for our client.

**Terms of service:** not retrieved. Web search did not return sreality.cz's own terms (podmínky použití). A business directory lists the operator as Seznam.cz, a.s. A secondary Czech legal overview (law.ungovr.org, unverified) says a robots.txt directive can count as a text-and-data-mining opt-out. This needs a legal read, not a conclusion here.

**Official access:** none found. No developer portal, partner programme or data licence came up. Third-party Apify actor listings disagree on whether the JSON endpoint is internal or a public feed. Neither view is authoritative.

## 2. Decision for the team

| Option | What it means | Main cost |
| --- | --- | --- |
| A. Ask Sreality (Seznam) for permission or a data licence before any automated access | No automated access until a written answer | Probably misses the 14:00 checkpoint |
| B. Accept the risk and verify politely | About 10 plain-HTTP requests at ≤1 req/s, no browser, no header spoofing. This still goes against `Disallow: /` for our client, and the public repo would show a scraper built against robots.txt. Needs a recorded decision in docs/decisions.md. | Legal and reputational risk; possible IP block during the demo |
| C. Drop Sreality from the demo | Bezrealitky and iDNES carry the demo; each needs its own robots.txt check first | Sreality carries the 14:00 checkpoint (PRD risk table) |

**Recommendation (not decided):** do not run B without a legal read. Fetch robots.txt for Bezrealitky and iDNES now (one request each; fetching robots.txt is always allowed), then choose between A and C.

## 3. Team-reported API (not verified here)

| Purpose | Request | Status |
| --- | --- | --- |
| Search | `GET https://www.sreality.cz/api/v1/estates/search` with `category_main_cb=1`, `category_type_cb=2`, `category_sub_cb=4,5`, `locality_district_id=5002`, `price_to`, `limit`, `offset` | Team-reported 13 Nov. Not re-verified. |
| Detail | `GET https://www.sreality.cz/api/v1/estates/{hash_id}` | Team-reported. |
| Old API | `/api/cs/v2/` | Team-reported to return 404. |

If the 13 Nov verification used an automated client, it fell under the same robots.txt directive. The team should weigh that before 14:00.

Team-reported detail fields: `price_note`, `ready_date`, `elevator`, `furnished`, `ownership`, GPS, POI distances, broker contact, images. The other `Listing` fields have no known source yet.

## 4. Verification checklist (none done)

| Item from the brief | Status |
| --- | --- |
| Access path (JSON API, embedded state or HTML) | Team says JSON API. Not verified. |
| Region ids for Praha 2, 3 and 10 | Praha 2 = 5002 (team-reported). Praha 3 and 10 not verified. |
| Filter to Vinohrady via locality fields | Not verified. |
| Disposition codes 2+kk and 2+1 | `category_sub_cb` 4 and 5 are assumed from the PRD. Not verified. |
| Detail page URL format | Not verified. |
| Maximum page size | Not verified. |
| Image URL format and resizing | Not verified. |
| Detail fields that can be null | Not verified. |
| Where contact data lives (`user` / `premise`) | Not verified. Describe the structure only; never record real contacts. |
| Field mapping into `Listing` | Not verified against any payload. |
| Rate behaviour | Not observed. |
| Playwright needed? | Undecided. The team's endpoints are plain JSON, so plain HTTP should be enough if they hold. Not confirmed. |

## 5. REA

REA tool schemas were loaded. No capture or analysis of sreality.cz was run. Any REA work on the site waits for the decision in section 2.

## 6. Notes

- The robots.txt copy is stored outside the repo, in the research-evidence folder of the orchestration workspace. Nothing raw is in this repo.
- Cross-lane: WP2 and WP3 should run the same robots.txt check before their first live request. The integrator should confirm this.
- docs/open-items.md has no row for this yet. It needs one (owner: Vladimir and Danila; blocks WP1 live work). That is a shared file, so it goes in its own PR.
