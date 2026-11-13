# PostHog improvement loop (P1)

Built only after the core call path is rehearsed; cut at the 16:00 checkpoint otherwise. Loop: capture → group signals → propose one change → human yes/no → apply → rerank.

## Smallest useful demonstration

1. Capture structured events with `property_id`, source, timestamp and evidence. The main one is `listing_rejected` with the `Reason` Vladimir typed on the board.
2. Query today's real events and produce one grouped report, e.g. "3 of 3 rejections: no elevator". A local mirrored-log fallback must be labeled.
3. Propose one criteria change with the evidence and expected effect.
4. Vladimir says yes; Claude applies it and the board reranks visibly. Hard constraints never change silently.
5. Show measurement as pending; one rerank proves the change was applied, not that results improved.

Elevator must not already be a hard filter in Vladimir's criteria, or those flats would never reach the board. Pick the example from his real rejections.

Other events (`extraction_low_confidence` from Featherless, `call_incomplete`, `listing_stale`) are optional. Implement only events the workflow actually emits.

## Scope and honesty

- Listing facts stay in issues; workflow state stays on the board. PostHog holds telemetry only.
- Featherless's labeled evaluation stays deferred; do not claim the dataset exists.
- Use genuine events from today's runs. Label synthetic fixtures.
- Criteria-change approval is separate from Interested.
- Agencies get one spoken sentence at the close; nothing is built for them.
- A local report with event references is enough; do not imply native PostHog Inbox automation.
- Workshop links and the full signal catalog are in the [original lane document](archive/2026-11-13-notion/03-lane-3-posthog-self-driving-loop-mac-mini.md).
