# DOMOVOY

Your real-estate agent in your pocket. Tell your existing AI agent what home you need; DOMOVOY researches Prague rentals, explains costs and trade-offs, and coordinates an approved viewing conversation.

**Status, 13 Nov 2026:** built during the hackathon. The Actor, the skill scripts, the phone page and the PostHog loop are in this repository; what was run and seen is recorded in each merged pull request. [docs/packaging.md](docs/packaging.md) says which setup steps were run and which were not.

## Workflow

1. An Apify Actor collects real listings from Sreality, Bezrealitky and iDNES; Featherless extracts fees; the Actor normalizes, deduplicates, filters and calculates known monthly and upfront costs.
2. Each shortlisted flat becomes a page in a Notion database, with evidence, source timestamps and unknowns. The renter moves one flat to **Interested**, authorizing contact.
3. Claude Code passes property context and free calendar windows to an ElevenLabs voice agent on the phone page.
4. A consenting demo realtor answers a live English browser conversation on the same laptop.
5. The agent returns a structured result. Claude updates the flat's status and creates a test Calendar event only after agreement on a time inside the approved windows and budget.

The intended package is an open-source Agent Skill for Claude Code. The phone page demonstrates live voice over WebRTC; it does not place a telephone call to the listing agent.

## Documentation

- [Docs index](docs/README.md)
- [Current scope and architecture](docs/plan.md)
- [Demo and acceptance gates](docs/demo.md)
- [Setup, cost and swapping services](docs/packaging.md)
- [PRD and lane specs](docs/prd/README.md)
- [Decisions](docs/decisions.md)
- [Open items](docs/open-items.md)
- [Original Notion exports](docs/archive/2026-11-13-notion/README.md)

## Set up

Paste the prompt from [domovoy-phone.vercel.app/start](https://domovoy-phone.vercel.app/start) into Claude Code, or run:

    claude "$(curl -fsSL https://domovoy-phone.vercel.app/prompt.txt)"

The agent installs the skill and runs `python3 skill/domovoy/scripts/doctor.py check`, which checks every integration without changing anything and prints one fix per missing piece. Setup steps, prerequisites, cost per 100 flats and per 100 calls, and how to swap each service: [docs/packaging.md](docs/packaging.md).

Built for AI Agents for the Rest of Us, Prague, 13 Nov 2026. Vladimir owns acquisition and extraction; Danila owns voice and its integration. Implementation evidence and what was built during the event must be recorded before submission.
