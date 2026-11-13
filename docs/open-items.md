# Open items

Things to settle before or during the build. When one is decided, move it to [decisions.md](decisions.md) and update the owning doc.

| # | Item | Owner | Blocks |
| --- | --- | --- | --- |
| 2 | Calendar access: Google Calendar MCP connector or a skill script with the Google API | Danila + Vladimir | `available_windows`, test event |
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
| 13 | Danila reviews the merged switch to Notion and the `call_context` change (`issue_number` → `notion_page_id`); merged by Vladimir's call without prior review | Danila | Voice lane payload, skill call flow |
