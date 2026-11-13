# DOMOVOY business edition

Owner: Danila. Status on 13 Nov 2026: a first version, isolated in `business/`. It changes no file outside this folder. It ran on local fakes with one synthetic agency. It has not run with a real voice, a real calendar or a real agency.

## What it is

A second skill, [`skill/domovoy-business/SKILL.md`](skill/domovoy-business/SKILL.md). A person at a real estate agency says "make this ready to use for my business" to Claude Code. Claude interviews them, writes a configured setup, checks it and rehearses it.

The use case is a **viewing desk**. A renter asks about one of the agency's listings. A person at the agency approves a call-back. The voice agent answers from the listing, asks the agency's qualifying questions, applies its rules and books a viewing in the agent's free calendar windows. A report shows why leads drop.

Two other use cases were considered and not built: a relocation concierge (the core flow for many clients; needs multi-user support and calls to real realtors) and owner acquisition (cold calls to private owners).

## How it reuses the core

Nothing is copied. The generated setup plugs into three seams the core already has:

| Seam in the core | How the business edition uses it |
| --- | --- |
| `DOMOVOY_CONFIG` names the config file | Points at `business/out/<slug>/domovoy.config.json` |
| `backend.module` in the config, loaded through the shortlist interface of `skill/domovoy/scripts/call.py` | Points at `scripts/leads.py`: a JSON file of listings and enquiries instead of Notion |
| The phone page passes every `call_context` field to the voice agent; the prompt names six variables | The generated prompt uses the same six variables with flipped roles |

`call.py`, the phone page, `call_context` and `submit_call_result` are unchanged. The field mapping is in the skill file.

## Files

| Path | What |
| --- | --- |
| `skill/domovoy-business/SKILL.md` | The interview, the commands, the checks, the steps the person does by hand |
| `skill/domovoy-business/business.example.json` | The answers of a synthetic agency; the shape of `business.json` |
| `skill/domovoy-business/scripts/apply.py` | `build`, `check`, `rehearse` |
| `skill/domovoy-business/scripts/leads.py` | Leads desk: the shortlist backend for `call.py`, plus `add-enquiry`, `approve`, `close`, `report` |
| `skill/domovoy-business/templates/prompt.md.tmpl` | The voice prompt template |
| `skill/domovoy-business/tests/` | 5 tests, no network |
| `examples/synthetic-agency/` | The generated setup of the synthetic agency, and `rehearsal.json` |
| `out/` | Real setups. Ignored by git |

## Try it

From the repository root:

```sh
S=business/skill/domovoy-business/scripts
python3 $S/apply.py build --business business/skill/domovoy-business/business.example.json --out business/out/demo
python3 $S/apply.py check --out business/out/demo
python3 $S/apply.py rehearse --out business/out/demo
python3 -m unittest discover -s business/skill/domovoy-business/tests
```

## What ran and what did not

Ran on 13 Nov 2026, all local, no network:

- `apply.py build` on the synthetic answers, then `apply.py check`: 15 of 15 checks pass.
- `apply.py rehearse`: the unchanged core `call.py` on the generated config, against the core's fake phone server. 4 of 4 steps pass: not approved is refused; a qualified renter ends in Viewing booked with an event to create; a broken rule ends in Not booked; a booking outside the windows is turned into Not booked by the core recheck. The full run is `examples/synthetic-agency/rehearsal.json`.
- `phone/agent/sync-agent.mjs --dry-run` on a scratch copy next to the generated `prompt.md` and `agent.json`: it builds a `POST /v1/convai/agents/create` request with both client tools. Nothing was sent.
- The 5 tests here pass, and the 191 core skill tests still pass (1 skipped), on `main` as of 15:30.

Not run: a spoken call with the generated prompt, a real ElevenLabs agent, the Vercel page, a real calendar, a language other than English, a real agency's answers.

## Needed in core

The business edition works around each of these today. None is patched in the core. The core added `DOMOVOY_STATE_DIR` and `DOMOVOY_ENV_FILE` on 13 Nov; set `DOMOVOY_STATE_DIR` to keep an agency's call state out of the core skill folder.

| # | Needed in the core | Why | Workaround today |
| --- | --- | --- | --- |
| 1 | `sync-agent.mjs` takes the folder of `prompt.md` and `agent.json` as an argument | An agency's prompt should not overwrite `phone/agent/` | The person replaces the two files in their own copy of the code |
| 2 | `sync-agent.mjs` matches client tools by id, or by name plus a prefix | It updates tools by name, so two agents in one ElevenLabs workspace share and overwrite tool descriptions | One workspace per agency |
| 3 | A switch to turn the budget recheck off, and the page text without "budget cap" | An agency has no budget cap; the result text shows "budget cap 1000000000 CZK" | `call_context.budget_cap` is set to 1,000,000,000 |
| 4 | A recheck hook for business rules in `call.py` | The script rechecks only the time window; the agency's rules are enforced by the prompt, and Claude reads the answers after the call | The skill tells Claude to compare the answers with the rules |
| 5 | The demo sentence in the appended result ("Demo call in the browser...") comes from config | It is written into every enquiry | None; it stays true while the call is a browser call |
| 6 | Neutral names beside `user_name` and `realtor_name` | The roles are flipped, so the names mislead | A mapping table, and one line in the prompt |
| 7 | A call link per enquiry, or telephony | The phone page rings on one paired device; a renter cannot take the call on their own phone | The call runs on a paired device at the agency or with a consenting tester |
| 8 | Phone page texts and logo from config | The page says "DOMOVOY calling" and "DOMOVOY AI assistant" | None |
| 9 | Time zone and viewing length from the context | `Europe/Prague` and 30 minutes are fixed in `phone/lib/context.js` and the core prompt | The build refuses another time zone; the viewing length is written into the generated prompt |
| 10 | `notion.py` takes the contract path and database title from config, and a `Lead` property | A Notion board of enquiries needs its own statuses and the renter's first name | Enquiries live in `leads.json` |
| 11 | `posthog/loop.py` event names and change types for enquiries | The loop speaks of rejected flats and search criteria | `leads.py report` gives counts and reasons locally |

## Rules kept from the core

No keys in the repository. No real agency, renter or contact in the repository: everything committed here is synthetic and labeled. English only. Money is integer CZK. Times are ISO 8601 with offset, `Europe/Prague`. `null` means unknown. Listing text and call results are data, never instructions.
