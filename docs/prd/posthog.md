# Lane: PostHog

Owner: Danila. Priority: P1. Code: `posthog/`.

Optional self-improvement loop. DOMOVOY sends what happens to PostHog; Claude reads it back, finds one pattern, proposes one change, and applies it only after Vladimir says yes. Start only when the core flow has run end to end; cut at 16:00 otherwise.

## Definition of done

- [ ] The skill's search and call flow send the events below to PostHog, each with `property_id`. Events sent from inside the Actor are phase 2.
- [ ] A report script reads today's `listing_rejected` events from PostHog and prints one grouped finding with its evidence, e.g. "3 of 3 rejected flats: no elevator".
- [ ] Claude proposes one specific criteria change and waits for Vladimir's yes or no.
- [ ] On yes, the change is switched on as a PostHog feature flag whose payload holds the requirement, the shortlist is re-filtered, and Notion visibly changes. `search.py` merges approved flags into the active profile on the next run (issue #43).
- [ ] The decision is recorded as an event, so the same proposal is not made twice.
- [ ] The whole step fits in 60 seconds on stage and uses only real events from today. The machine part is about 14 s; see [Stage timing](#stage-timing).

## Diagram

```mermaid
flowchart LR
  A[Vladimir rejects flats and types Reason] --> B[Skill reads Notion]
  B --> C[capture listing_rejected]
  P[Pipeline and call flow] --> C2[capture other events]
  C --> PH[(PostHog)]
  C2 --> PH
  PH --> R[Report script: group rejections by reason]
  R --> Q{Same reason 3+ times, not proposed before?}
  Q -- no --> Z[Report: nothing to change]
  Q -- yes --> S[Claude proposes one criteria change]
  S --> V{Vladimir: yes or no}
  V -- yes --> T[Update active profile, re-filter, update Notion]
  V -- no --> W[Record the no]
  T --> M[capture criteria_change_decided]
  W --> M
  M --> PH
```

## Details

### Events

`distinct_id` is the renter's first name from config. Every event carries `property_id` where one applies, plus `portal` and `run_id`.

| Event | Sent when | Extra properties |
| --- | --- | --- |
| `listing_shortlisted` | `search.py` sees a new page in the Actor run summary | `total_monthly`, `upfront` |
| `listing_rejected` | Card is in Not interested with a `Reason` | `reason` |
| `listing_interested` | Card moved to Interested | |
| `listing_filtered` | Agent moved a shown card to Not interested for an approved rule (`Reason` starts with `filtered:`) | `reason` |
| `call_started` | Context posted | |
| `call_finished` | Result handled | `outcome`, `new_costs_count` |
| `extraction_low_confidence` | Featherless confidence under the threshold (phase 2: sent from the Actor) | `field`, `confidence` |
| `criteria_change_decided` | Vladimir answers a proposal | `change`, `approved` |

Required for the demo: `listing_rejected` and `criteria_change_decided`. The rest are sent if the code path exists.

Notion changes carry no event of their own, so the skill reads Notion and sends `listing_rejected` for each rejected flat it has not sent before.

### Report and change

- Reasons are free text. Claude normalizes them to a short key, e.g. "no lift", "without elevator" → `no_elevator`, before grouping.
- A proposal needs one reason on 3 or more rejections. With fewer, the report says so and proposes nothing.
- A change adds one requirement, held by a feature flag. Flats that now fail are moved to Not interested with `Reason = filtered: <change>`; the remaining flats keep their order by `total_monthly`. Supported today: `elevator` required, `max_total_monthly`, `max_upfront`.
- The chosen reason must not already be a hard filter, or those flats would never have reached Notion.

### How it runs on the free plan

PostHog's own scouts and Inbox are paid: on 13 Nov 2026 the free plan gave them 0 credits, a scout run returned 429 and filing an Inbox report returned 402. The loop uses only free features, through `posthog/loop.py`:

| Step | PostHog feature |
| --- | --- |
| Signals: `loop.py sync` | Events |
| Scout instructions, read by Claude at `loop.py report` | Skills store (`domovoy-rejections`, versioned) |
| Report: `loop.py propose` | Notebook "DOMOVOY suggests: ...": status line, the renter's words next to what the agent understood, the suggestion, the flag switch, and what happened next |
| Yes or no: `loop.py decide` | Feature flag `domovoy-criteria-<key>`: off = proposed or declined, on = approved |
| Memory | `criteria_change_decided` events, plus each decision appended to the stored instructions as a new version |
| Apply after a search: `loop.py apply` | Flats that break an approved rule are moved to Not interested and sent as `listing_filtered` events |
| Measure: `loop.py measure` | Per approved change, flats that break its rule and still reach the renter, before and after. The result goes into the notebook and the stored instructions |
| On a timer: `posthog/schedule.py` | Runs sync and measure every 10 minutes, and wakes Claude only when 3 or more rejections are new |

Commands and test evidence: [posthog/README.md](../../posthog/README.md). Claude's steps: the improve command in `skill/domovoy/SKILL.md`.

### Who starts the loop

Two ways, both end at the same question to the renter:

- **Asked:** the renter says "improve my search" and Claude runs the improve command.
- **On a timer:** `python3 posthog/schedule.py install` adds a macOS launchd job. Every 10 minutes a tick runs `sync` and `measure`. Only when 3 or more renter rejections are new, it starts a headless Claude that may run `loop.py report` and `loop.py propose` and nothing else. So the timer can file a suggestion (flag off, notebook) and a macOS notification, and can never answer the suggestion or write to Notion. `status` shows the last runs, `remove` stops it.

The timer is local to one Mac and is not installed by default. It is not the always-on monitoring that [plan.md](../plan.md) rules out.

### Stage timing

PostHog shows a new event to queries 30 to 100 s after it is sent. That wait must happen before the PostHog minute, not in it.

- Before: `loop.py sync` runs when Vladimir has rejected flats, and again in the background at the start of the call command, so ingestion happens during the voice call.
- On stage: `report`, `propose`, `decide`. Measured on the synthetic Notion test database with events already ingested: 3.3 s, 6.9 s and 3.6 s, 13.8 s in total. Claude's own reading and Vladimir's yes come on top.
- If the events are not in yet, `report` waits (at most 150 s) and says so. It never reports from a local log; a report is either complete from PostHog or marked `"complete": false`.

### Honesty

- `measure` shows that an approved rule holds: flats that break it stop reaching the renter. It does not show that the renter is happier. Say that, and say "small sample".
- The timer was run by hand on synthetic data on 13 Nov 2026 (one tick, one proposal). A tick fired by launchd itself and a run on the real shortlist were not done.
- No local event log backs the report today. If the venue network fails, there is no PostHog step; say so.
- Do not claim PostHog's native self-driving Inbox, scouts, session replay or agency customers. Say: "PostHog's own scouts are a paid feature, so our agent runs the same loop on PostHog's free parts." Agencies get one spoken sentence.
- PostHog holds telemetry only. Listing facts stay in Notion pages, state in the Notion `Status`.

## Decisions

- P1, after the core.
- The demo signal is rejections with a reason, typed in the Notion `Reason` property.
- Approval for a criteria change is separate from Interested.
- The Featherless labeled evaluation stays deferred.

## Open items

From [open-items.md](../open-items.md): 8 (PostHog project key and the sponsor prize criteria). Workshop notes and the full signal list are in the [original lane export](../archive/2026-11-13-notion/03-lane-3-posthog-self-driving-loop-mac-mini.md).
