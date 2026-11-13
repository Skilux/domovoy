# QA checklist

Danila and Vladimir walk through this together on Vladimir's laptop, stage by stage, before the 16:00 full run on 13 Nov 2026. Tick a box only after you saw the result yourself. Write every result in the [result log](#result-log).

Gates today, Prague time: 16:00 one full run on Vladimir's laptop, 17:00 code freeze, 17:30 repo public, 18:00 demo. The acceptance gates live in [demo.md](demo.md#required-gates); this file is the walk-through that proves them.

Rules for the walk-through:

- **Call budget.** ElevenLabs gives 15 free agent minutes per month and one live call uses about 2 of them. Make at most three live calls before the stage. Run every negative case offline (stage 4), never as a spoken call.
- Never write, paste or screenshot a key value, and never the paired phone URL with its key.
- Run script commands from `skill/domovoy/` unless the item says otherwise. `<W>` is the windows JSON, for example `'[{"start": "2026-11-16T17:00:00+01:00", "end": "2026-11-16T18:00:00+01:00"}]'`.
- Commands were checked against `main` at `edfe7db` on 13 Nov 2026. Stages 1, 2 (live part), 3, 5 and 6 were not run by the author of this file.

## 0. Setup

| Done | Who | Do | Pass when you see |
| --- | --- | --- | --- |
| - [ ] | Vladimir | `git checkout main && git pull` in the repo checkout | `git log -1` shows the same commit as GitHub `main` |
| - [ ] | Vladimir | `ls -l ~/.claude/skills/domovoy` | A link to `skill/domovoy` in this checkout, not an old copy |
| - [ ] | Vladimir | `cd skill/domovoy && python3 scripts/doctor.py check` | Last lines show `0 fail`. `SKIP` on `featherless.key` and `calendar.access` is normal. `WARN local.skill` is not: fix it |
| - [ ] | Vladimir | `python3 -m unittest discover -s tests` | `OK`. On `main` at `edfe7db`: 187 tests, 1 skipped, about 21 s |
| - [ ] | Vladimir | `python3 scripts/demo.py call` | `"synthetic": true`, `"status": "Viewing booked"`, `"create_event": true`. Do not create this event in a real calendar |
| - [ ] | Vladimir | In Claude Code, ask "list my calendars" | Claude lists Vladimir's Google calendars. `doctor.py` cannot check this |
| - [ ] | Vladimir | Check `config.json`: `active_profile` is his real profile, `call_context.user_name` is his name, `calendar.viewing_weekdays` and hours give at least one free window in the next 7 days | `python3 scripts/call.py check --windows <W>` in stage 2 prints `budget_cap` equal to his real monthly cap |
| - [ ] | Vladimir | Only if Claude Desktop Cowork is the stage tool: ask it to run `python3 scripts/doctor.py check` there. A sandboxed runner may need `DOMOVOY_ENV_FILE`, `DOMOVOY_CONFIG` and `DOMOVOY_STATE_DIR` set to paths it can read and write | The same `0 fail`. If not, the stage tool is Claude Code. Decide now, not at 17:00 |

## 1. FIND (Vladimir)

| Done | Who | Do | Pass when you see |
| --- | --- | --- | --- |
| - [ ] | Vladimir | Open the real **DOMOVOY shortlist** in Notion | Flats from Sreality, Bezrealitky and iDNES. Each has a source link and a collection time |
| - [ ] | Vladimir | Open the demo flat | `Total monthly`, `Move-in cost` and `Move-in note` are filled, and `Total monthly` is under his budget cap. A flat with an unknown `Total monthly` always ends in Not booked ([open item 15](open-items.md)) |
| - [ ] | Both | Find one flat with an unknown `Total monthly` | The cell is empty, never 0, and `Unknowns` names what is missing |
| - [ ] | Vladimir | Switch to the stage view | Agency, Contact, Email, Phone and the empty `Move-in total` column are hidden. No realtor name, phone or email is visible at projector zoom |
| - [ ] | Both | Decide: live search or pre-filled shortlist | Written in the result log. A full Actor run took 7 min 14 s (8 min 24 s in the README run), longer than the 3 minute slot. If live, start it before going on stage with `python3 scripts/search.py run` and say on stage that it was started earlier |
| - [ ] | Vladimir | Only if a live run is shown: `python3 scripts/search.py run` | Exit 0, `summary.notion.errors` is 0, no source in `summary.sources` is `degraded` or `failed` |

## 2. APPROVE

| Done | Who | Do | Pass when you see |
| --- | --- | --- | --- |
| - [ ] | Vladimir | Make sure no flat has `Interested?` = Yes and none has `Status` = Interested or Calling. Then `python3 scripts/call.py check --windows <W>` | Exit 2, `"refused": true`, reason starts "no flat is marked Interested; nobody was contacted" |
| - [ ] | Vladimir | Set `Interested?` = Yes on the demo flat, run the same command | Exit 0 and a `call_context` for exactly that flat: its address, `total_monthly`, `budget_cap`, `unknowns`. `warnings` is empty |
| - [ ] | Both | Read `warnings` in that output | No "total_monthly unknown" and no "over budget_cap". Either one means the call will end in Not booked: pick another flat |
| - [ ] | Vladimir | Set `Interested?` = Yes on a second flat, run it again, then clear the second flat | Exit 2, a refusal that lists both flats and asks for `--page ID`. After clearing: one flat again |

## 3. CALL (Danila answers as the demo realtor)

This is a live call. It counts against the three-call budget.

| Done | Who | Do | Pass when you see |
| --- | --- | --- | --- |
| - [ ] | Danila | Open the paired phone page once: `$PHONE_URL/?k=$DOMOVOY_RECEIVER_KEY`. Click **Ready**. Keep exactly one paired page open anywhere | The page waits for a call. The key is gone from the address bar |
| - [ ] | Danila | Allow the microphone, set the laptop volume | The browser shows the microphone permission as granted |
| - [ ] | Vladimir | In Claude Code: "call about my Interested flat" | Claude reads the calendar, then runs `call.py run --windows ...`. It asks nothing that needs a terminal answer |
| - [ ] | Both | Watch Notion | `Status` of the demo flat changes to **Calling** |
| - [ ] | Danila | Watch the phone page | It rings (Nokia tone) and shows the flat's address. Answer |
| - [ ] | Danila | Listen. Answer the fee question with a one-time fee. Decline the first time, accept the second | The agent says it is an AI. It asks about the unknown fees. It offers only times from the free windows. It repeats the agreed time |
| - [ ] | Both | Do nothing at the end | The call ends by itself and `call.py` prints one JSON object in under 5 minutes |

## 4. BOOK

| Done | Who | Do | Pass when you see |
| --- | --- | --- | --- |
| - [ ] | Both | Open the demo flat in Notion | `Status` = **Viewing booked**, `Viewing date` is the agreed time, and the page body ends with "Call result: Viewing booked", the summary and the answers. No realtor name in the summary |
| - [ ] | Vladimir | Open Google Calendar | One event "Viewing (demo): ..." at the agreed time, shown in Prague time, with the Notion page link. Claude created it only after `"create_event": true` |
| - [ ] | Vladimir | Ask Claude to call again about the same flat | A refusal. The flat is not called twice |
| - [ ] | Either | Offline, no minutes used: `python3 scripts/demo.py call --outcome not_booked` | `"status": "Not booked"`, `"create_event": false`, reason "the call ended without an agreed viewing" |
| - [ ] | Either | Offline: `python3 -m unittest tests.test_e2e_fake -k over_budget -k outside_windows -v` | `OK`. A recurring cost over the cap gives Not booked with the reason "monthly total ... is over the budget cap"; a time outside the windows gives Not booked; neither creates an event |

## 5. LEARN (PostHog, only after stages 0 to 4 pass)

Run these from the repo root. `<C>` is the path of `skill/domovoy/config.json`.

| Done | Who | Do | Pass when you see |
| --- | --- | --- | --- |
| - [ ] | Vladimir | Reject at least 3 flats in Notion with the same typed `Reason`, for example "unfurnished" | `Status` = Not interested and `Reason` filled on each |
| - [ ] | Vladimir | `DOMOVOY_CONFIG=<C> python3 posthog/loop.py sync`, at least 2 minutes before the next step | It ends without an error and without `missing POSTHOG_...` |
| - [ ] | Vladimir | In Claude Code: "improve my search" | A finding, one proposed change and a notebook link, in under 15 s from the question. `"complete": true` in the report |
| - [ ] | Both | Before the yes: read the first line `decide` will print | It names the real **DOMOVOY shortlist**. This is the first write of the loop to the real shortlist. Approve once only |
| - [ ] | Vladimir | Say yes | `moved_to_not_interested` lists only flats that fail the new rule. No flat with an answer in `Interested?` moved. The demo flat did not move |
| - [ ] | Vladimir | Later, after a new search and a new `sync`: `DOMOVOY_CONFIG=<C> python3 posthog/loop.py measure` | A `verdict` line, and the before/after table in the notebook is filled. With no new flat it says so and writes nothing |

## 6. Pages and README

| Done | Who | Do | Pass when you see |
| --- | --- | --- | --- |
| - [ ] | Danila | Scan the QR code in the README with a phone | It opens `https://domovoy-phone.vercel.app/start` |
| - [ ] | Danila | Open `/start` in a private window | The page loads, the install prompt copies, no key in the page or the address bar |
| - [ ] | Both | Open `https://domovoy-phone.vercel.app/stage?full=1` on the projector, press Right arrow through all states | Readable from the back row. Sample data is labelled as sample |
| - [ ] | Danila | Open the GitHub repo page | The mermaid diagram, the GIF and all badges render. No broken image |
| - [ ] | Danila | From `phone/`: the route check in [phone/README.md](../phone/README.md) | `/phone`, `/start`, `/stage` and `/prompt.txt` answer 200, `/` answers 307, and `/api/pending` without the key answers 401 (seen 13 Nov 2026) |

## 7. Before 17:30

| Done | Who | Do | Pass when you see |
| --- | --- | --- | --- |
| - [ ] | Danila | Secret and contact scan of the tree and the git history | 0 hits for key values, the receiver key, realtor names, phones and emails |
| - [ ] | Vladimir | Decide on portal text in `apify/tests/fixtures` (real listing text from three portals) | Keep, scrub or remove, written in [decisions.md](decisions.md) |
| - [ ] | Vladimir | Reset the demo flat: `Status` = Shortlisted, `Interested?` empty, `Viewing date` empty | `call.py check` refuses again, as in stage 2 |
| - [ ] | Vladimir | Delete every test Calendar event | No "Viewing (demo)" event left, so the free windows on stage are the real ones |
| - [ ] | Danila | Close every paired phone page except the stage one | One paired page. Any paired page takes the next call |
| - [ ] | Both | 17:00: code freeze. Then walk the [submission list](demo.md#before-submission-1730) | Every box ticked |
| - [ ] | Danila | 17:30: switch `Skilux/domovoy` to public | The repo link and the Vercel link from the form open in a private window |

## Result log

| Item | Who saw it | Time | Pass or fail | Note |
| --- | --- | --- | --- | --- |
| 0. Setup | | | | |
| 1. FIND | | | | |
| 1. Live search or pre-filled | | | | |
| 2. APPROVE | | | | |
| 3. CALL (live call 1 of 3) | | | | |
| 4. BOOK: Notion receipt | | | | |
| 4. BOOK: Calendar event | | | | |
| 4. BOOK: negative cases, offline | | | | |
| 5. LEARN | | | | |
| 6. Pages and README | | | | |
| 7. Before 17:30 | | | | |
