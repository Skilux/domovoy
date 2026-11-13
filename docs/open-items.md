# Open items

Things to settle before or during the build. When one is decided, move it to [decisions.md](decisions.md) and update the owning doc.

| # | Item | Owner | Blocks |
| --- | --- | --- | --- |
| 3 | Vladimir's real criteria and permission to show his listings and rejection reasons | Vladimir | Filters, PostHog example |
| 4 | Vladimir confirms the `call_context` fields match his Actor output | Vladimir | Phone page, voice agent |
| 5 | Notion integration **DOMOVOY** + `NOTION_TOKEN` on Vladimir's laptop and as an Apify secret input | Vladimir | Notion writes, skill |
| 6 | Run `notion.py setup` to create the **DOMOVOY shortlist** database | Vladimir | Notion writes, skill |
| 7 | Featherless model choice, confidence threshold and plan concurrency limit | Vladimir | Extraction, Actor run time |
| 8 | PostHog project key and sponsor prize criteria | Danila | P1 lane |
| 9 | ElevenLabs voice, persona, first message, `agent_id`; allowlist the Vercel domain | Danila | Voice agent |
| 10 | Vladimir's separate final demo-flow page: import and reconcile | Vladimir | — |
| 11 | Gmail confirmation: build only if time remains | Danila | — |
| 12 | Bezrealitky access: its GraphQL API returns 403 to plain requests; investigate the page's data loading with REA | Vladimir | Bezrealitky source |
| 14 | `notion.py` must give `call.py` four operations, or names an adapter can map: list flats by `Status` (`id`, `title`, `url`), read one flat as `call_context` listing fields plus page text, set `Status`, append text. Interface is in the `call.py` docstring; until it lands the call flow runs on `tests/gh_test_backend.py`, a labeled test backend | Vladimir | Call command on real Notion pages |
| 15 | A flat with `total_monthly` unknown, or an unknown recurring new cost, ends in Not booked because the budget cannot be confirmed. Confirm, or pick a demo flat with a known total | Vladimir + Danila | Demo flat choice |
| 16 | `call.py` passes extra listing fields through in `call_context`. The phone server and the ElevenLabs variables must ignore fields they do not know, and must accept `notion_page_id` | Danila | Run against the real phone server |
| 17 | How the active profile is marked in `config.json`. `call.py` reads `active_profile` (a profile `id`), or takes the only profile | Vladimir | `budget_cap` |
| 18 | Before the repo goes public: close synthetic test issue #2 in `Skilux/domovoy` and remove GitHub project 1, created as "DOMOVOY shortlist" before the switch to Notion and now only the call test backend | Danila | 17:30 submission |
