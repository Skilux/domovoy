# PostHog improvement loop

The 13 Nov workshop notes add a sponsor extension: capture → group signals → check prior outcomes → propose one change → human yes/no → apply → measure → retain outcome. The core viewing workflow takes priority.

## Smallest useful demonstration

1. Capture structured events with listing ID, source, timestamp, run/user identity and relevant evidence.
2. Query today's real events in PostHog and produce one grouped report. A local mirrored-log fallback must be identified as such.
3. Propose one specific criteria or ranking change with evidence and expected effect.
4. Ask the renter to approve it, apply it and rerank visibly. Hard constraints never change silently.
5. Capture subsequent outcomes. If there are not enough outcomes to establish an effect, show measurement pending.

Useful source events: `listing_rejected`, `extraction_low_confidence`, `call_incomplete`, `viewing_bad`, `listing_stale`, `user_stalled`, `cost_surprise`. Implement only events supported by the actual workflow. The archive says approximately eight events but enumerates seven renter event types.

For example, repeated rejections for a newly discovered elevator preference can support proposing it as a hard requirement. Do not use this scenario if elevator is already a hard filter: those listings should have been rejected before the shortlist. One rerank proves application, not improved viewing conversion or extraction accuracy.

## Scope and honesty

- Keep listing facts and operational state in their existing pipeline/Notion stores. PostHog is the telemetry and analysis context.
- Featherless's roughly 20-listing labeled evaluation remains deferred. This demo must work without it; do not claim that dataset exists.
- Use genuine events from today's runs. Clearly label synthetic fixtures; do not imply historical customers or weeks of measurements.
- Criteria-change approval is separate from Interested/contact approval. Neither authorizes public listing edits or price changes.
- Agency signals and draft improvements are future/demo scenarios, not customer validation. Group Analytics, native Inbox, session replay and self-driving automation are optional and unverified.
- A local report with event references is sufficient; do not imply it is native PostHog Inbox automation.
- Sponsor prize criteria and API/SDK details must be checked before implementation. Source workshop links and the full renter/agency signal catalog remain in the [original lane document](archive/2026-11-13-notion/03-lane-3-posthog-self-driving-loop-mac-mini.md).
