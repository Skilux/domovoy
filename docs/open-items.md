# Open items

Things to settle before or during the build. When one is decided, move it to [decisions.md](decisions.md) and update the owning doc.

| # | Item | Owner | Blocks |
| --- | --- | --- | --- |
| 3 | Vladimir's real criteria and permission to show his listings and rejection reasons | Vladimir | Filters, PostHog example |
| 4 | Vladimir confirms the `call_context` fields match his Actor output | Vladimir | Phone page, voice agent |
| 5 | Notion integration **DOMOVOY** + `NOTION_TOKEN` on Vladimir's laptop and as an Apify secret input | Vladimir | Notion writes, skill |
| 6 | Run `notion.py setup` to create the **DOMOVOY shortlist** database | Vladimir | Notion writes, skill |
| 7 | Featherless model choice, confidence threshold and plan concurrency limit | Vladimir | Extraction, Actor run time |
| 8 | Sponsor prize criteria: ask the PostHog person what they score (the project key is settled, see decisions) | Danila | P1 lane |
| 9 | ElevenLabs voice, persona, first message, `agent_id`; allowlist the Vercel domain | Danila | Voice agent |
| 10 | Vladimir's separate final demo-flow page: import and reconcile | Vladimir | — |
| 11 | Gmail confirmation: build only if time remains | Danila | — |
| 12 | Bezrealitky access: its GraphQL API returns 403 to plain requests; investigate the page's data loading with REA | Vladimir | Bezrealitky source |
| 15 | A flat with `total_monthly` unknown, or an unknown recurring new cost, ends in Not booked because the budget cannot be confirmed. Confirm, or pick a demo flat with a known total | Vladimir + Danila | Demo flat choice |
| 17 | How the active profile is marked in `config.json`. `call.py` reads `active_profile` (a profile `id`), or takes the only profile | Vladimir | `budget_cap` |
| 18 | iDNES search pages show fewer cards than their header count. Praha 2, 2+kk: 30 cards reachable of 56 announced; Praha 3, 2+kk: 53 of 79. The cause is unknown. Decide the completeness target, and whether sort or facet splits are needed to reach more | Vladimir | iDNES completeness claim and the query plan (the source pages each query until the server stops) |
| 19 | The Katastr check writes owner and lender names to the flat's Notion page and attaches the LV PDF. [decisions.md](decisions.md) says storing owner names needs compliance sign-off. Confirm it, or limit the section to owner types | Vladimir | Showing the Katastr check in the public demo |
