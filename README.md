# DOMOVOY

Your real-estate agent in your pocket. Tell your existing AI agent what home you need; DOMOVOY researches Prague rentals, explains costs and trade-offs, and coordinates an approved viewing conversation.

**Status:** documentation prepared for the 13 Nov 2026 hackathon. This repository currently contains plans and source documents; no runnable implementation or verified integrations yet.

## Planned workflow

1. Apify collects real listings; scripts normalize, deduplicate, filter and calculate known monthly and upfront costs.
2. A Notion shortlist shows evidence, source timestamps and unknowns. The renter marks a property **Interested**, authorizing contact.
3. Claude Code passes property context and approved calendar windows to an ElevenLabs voice agent.
4. A consenting demo realtor answers a live English browser conversation on the same laptop.
5. The agent returns a structured result. Claude updates Notion and creates a clearly labeled test Calendar event only after an explicit agreement within approved constraints.

The intended package is an open-source Agent Skill for Claude Code. The phone page demonstrates live voice over WebRTC; it does not place a telephone call to the listing agent.

## Documentation

- [Docs index](docs/README.md)
- [Current scope and architecture](docs/plan.md)
- [Demo and acceptance gates](docs/demo.md)
- [PostHog improvement loop](docs/posthog.md)
- [Resolved inconsistencies and remaining decisions](docs/decisions.md)
- [Original Notion exports](docs/archive/2026-11-13-notion/README.md)

## Running and submission

Run commands will be added with the implementation. A demo/site URL is still pending. The submission needs this repository and a demo/site link.

Built for AI Agents for the Rest of Us, Prague, 13 Nov 2026. Vladimir owns acquisition and extraction; Danila owns voice and its integration. Implementation evidence and what was built during the event must be recorded before submission.
