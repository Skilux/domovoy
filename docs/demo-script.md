# Demo script: 3 minutes on stage

First version, 13 Nov 2026, for feedback from Danila and Vladimir. Stage at 18:00, Prague. The demo runs on Vladimir's laptop. Vladimir is the renter with his real search. Danila plays the demo realtor.

**Change to the sequence in [demo.md](demo.md).** demo.md gives PostHog the minute from 1:45 to 2:45. This script gives that time to the live call and the receipt, and keeps PostHog as one 15 s beat that can be cut. It also adds a 15 s opening with raised hands before Vladimir's problem. The decisions in demo.md are unchanged; if the team agrees, update the table there.

**Promise of the talk:** in 3 minutes you see a real renter approve one real flat, and an AI agent call to book the viewing, live.

**The one sentence the room should remember:** "You click Interested once, and DOMOVOY makes the call you hate making."

## What we may claim

| Claim | State on 13 Nov 2026, before 16:00 | How we say it |
| --- | --- | --- |
| 23 real flats from Sreality, Bezrealitky and iDNES in Notion | True | "Collected today at [time from the `Collected` column]" |
| Fees read from listing text, unknowns stay unknown | True | Point at one empty cell: "unknown, not zero" |
| A live voice call booked a viewing | True once, on a synthetic flat, 80 s | "Our first real call today took 80 seconds" |
| The call is a browser call | True. No phone network, the real listing agent is never called | Danila says it plainly before the call |
| The realtor is real | False. Danila plays a demo role | Danila says it, as a joke and as a fact |
| The whole flow on a real flat, ending in a Calendar event | Not run yet | Shown live only if the 16:00 rehearsal passes. Beats marked **[only if rehearsed]** |
| The Actor search runs live on stage | False. It takes about 7 min | The shortlist is pre-filled; we say when it was collected |
| PostHog learning loop | Partly built, run on synthetic test data | Optional beat, labelled as test data on the stage page |

## The 180 s script

Screens: **Stage** = `domovoy-phone.vercel.app/stage?full=1` (number keys jump to a state: 0 Title, 1 FIND, 2 APPROVE, 3 incoming call, 4 in call, 5 BOOK, 6 LEARN, 7 Close). **Claude** = the Claude Code session. **Notion** = the DOMOVOY shortlist, stage view. **Phone** = the paired phone page. **Start** = `domovoy-phone.vercel.app/start` with the QR code.

| Time | Who | Says | Screen | Action |
| --- | --- | --- | --- | --- |
| 0:00-0:12 | Vladimir | "Quick question. Who here rents a flat in Prague? Hands up. Now keep your hand up if it was easy to get it." (pause) "Yes. That's what I thought." | Stage, 0 Title | Raise his own hand, then drop it |
| 0:12-0:27 | Vladimir | "I'm Vladimir, and I'm looking for a flat right now. Three portals. Fees hidden in the text. And realtors only answer the phone when I'm at work." | Stage, 0 Title | None |
| 0:27-0:40 | Danila | "So we built DOMOVOY. A real-estate agent in your pocket. It's a skill for Claude. Four steps: find, approve, call, book." | Stage, 1 FIND | Press 1 |
| 0:40-0:58 | Vladimir | "Apify collected these flats from three portals, today at [time]. A Featherless model read the fees hidden in the text. So Notion shows the real monthly cost and the move-in cost. Empty means unknown, not zero." | Notion, stage view | Switch to Notion. Point at Total monthly, Move-in cost, one empty cell |
| 0:58-1:08 | Vladimir | "Nobody gets a call until I say so. I like this one. Interested: yes." | Notion | Click `Interested?` = Yes on the demo flat |
| 1:08-1:15 | Vladimir | "Now I tell Claude." | Claude | Switch to Claude. The prompt is already typed. Press Enter |
| 1:15-1:25 | Danila | "Full honesty: I'm the realtor today. Demo role. It's a browser call, no phone network, no real realtor. And don't worry: no commission for this demo." | Claude, then Phone | While Claude reads the calendar. Switch to the phone tab when it rings |
| 1:25-2:30 | Call | See [the call plan](#the-call-plan-60-to-75-s). ElevenLabs is the voice. | Phone | Danila clicks Accept and answers into the laptop microphone |
| 2:30-2:45 | Vladimir | "Claude doesn't just trust the agent. It checks the time is in my free window and the monthly total is under my budget. Then it updates Notion and puts the viewing in my calendar." | Claude, then Notion, then Calendar | **[only if rehearsed]** Show `Viewing booked` and the summary in Notion, then the Calendar event. **Fallback line:** "This is the result JSON from this call. The Notion and Calendar step ran in our tests, not yet on a real flat." Show the JSON in Claude |
| 2:45-3:00 | Danila | "Hands up again: who wants their next viewing booked like this? (pause) Good. Scan this, install it in your own Claude, and the only call you make is: yes. Thank you!" | Start, with the QR code | Switch to the Start tab, zoomed so the QR fills a third of the screen |

**Optional PostHog beat, 15 s.** Use it only if the call ended by 2:15. Then the receipt runs 2:15-2:30, this beat 2:30-2:45, and the closing stays at 2:45-3:00. If the call runs longer, skip it without a word. The story is complete without it.

| Time | Who | Says | Screen | Action |
| --- | --- | --- | --- | --- |
| 2:30-2:45 | Vladimir | "And it learns. I rejected three flats with no elevator. PostHog noticed and asked one question: require an elevator? I say yes, and the list filters itself. This part ran on test data." | Stage, 6 LEARN | Press 6 |

## The call plan, 60 to 75 s

Our one real call took 80 s because Danila declined the first time. On stage he accepts the first time offered. He answers in short sentences and volunteers the energy advance if the agent does not ask, so the call has a new cost for Claude to check.

The agent's lines are not scripted. These are what it said in the real call. Danila's lines are the script.

| Time in call | Agent (ElevenLabs) | Danila, demo realtor |
| --- | --- | --- |
| 0-5 s | Rings with the Nokia 3310 ringtone | Clicks Accept. "Hello, this is Daniel." |
| 5-15 s | "Hi Daniel, I'm an AI assistant, no body, just a calendar, calling for Vladimir about the flat at [address]." | "An AI with a calendar? Finally, someone who is never late. Go ahead." |
| 15-30 s | Asks the first unknown, for example the commission | "Commission is twenty thousand crowns. One time." |
| 30-42 s | Asks the next unknown, or moves on | "And energy is an advance of fifteen hundred crowns a month." Any other question: "I don't know, ask me at the viewing." |
| 42-58 s | Proposes the start of Vladimir's first free window | "Yes, [day] at [start time] works for me." |
| 58-70 s | Repeats the day and time and asks for a clear yes | "Yes, correct. See you there. Bye!" |
| 70-75 s | Says goodbye, saves the result, ends the call | Stays silent until the call screen closes |

Rules for Danila: never say a real person's name, a phone number or a real address. Say numbers as words: twenty thousand is 20,000 CZK, fifteen hundred is 1,500 CZK. Do not decline any time, because each round costs about 15 s. If the agent makes a joke, laugh once and answer the question. If the flat's `Total monthly` plus 1,500 CZK is over Vladimir's cap, say "energy is included" instead, or Claude will mark it Not booked.

## What Vladimir types and clicks

- **Prompt, typed in Claude before going on stage, sent at 1:08:** `call about my Interested flat`
- **Earlier in the same session, visible if he scrolls up:** the search request he made today, for example `Find me a 2+kk in Prague under [cap] CZK a month`, with its run summary.
- **Notion click at 0:58:** on the demo flat's row in the stage view, set `Interested?` to **Yes**. Nothing else. He does not change `Status` by hand.

## Light moments

1. The raised hands at 0:00. The room answers the question with their arms down.
2. Danila: "No commission for this demo." It jokes about fees, the product's topic, not about realtors.
3. The agent's own first line, "no body, just a calendar", and Danila's answer "Finally, someone who is never late." It is about the AI, not the realtor.
4. The closing: "the only call you make is: yes."

## Sponsor lines, one each

| Sponsor | Line | Beat |
| --- | --- | --- |
| Apify | "Apify collected these flats from three portals." | 0:40 |
| Featherless | "A Featherless model read the fees hidden in the text." | 0:40 |
| Notion | "Notion shows the real monthly cost." and "Nothing is called until I click here." | 0:40, 0:58 |
| ElevenLabs | "ElevenLabs is the voice." Danila says it as he clicks Accept | 1:25 |
| PostHog | "PostHog noticed and asked one question." | Optional beat |

## Fallbacks

Never pretend a fallback is live. Say what it is and when it happened.

| If | Say | Show |
| --- | --- | --- |
| The phone does not ring within 10 s of Enter | Danila: "Claude is checking Vladimir's calendar. Even AI needs a second to find a free evening." Wait 10 s more. Then: "Let me show you the call we made today." | The README section "A real call": the transcript of the 80 s call, 13 Nov 2026, synthetic flat |
| The call connects but no audio | Danila: "The agent is talking, the speakers are not. Here is what it says." Keep the call running; the in-call screen shows the live transcript | The phone page in-call screen, then the README transcript |
| Notion is slow to load or save | Vladimir: "Notion is thinking. It has 23 flats to think about." | Stage, 1 FIND and 2 APPROVE (labelled sample data), then retry Notion once |
| The network dies | Danila: "The Wi-Fi did not get a viewing. Here is the recording of the stage page and a real transcript." | The README GIF `docs/img/demo-stage.gif` and the README transcript, from a local copy of the repo. Say: "This is a recording of our stage page, not a live call." |
| The call ends Not booked | Vladimir: "And this is the honest part. No match, so no event. Claude tells me why." | The reason Claude wrote on the Notion page |

## Cut-down version, 75 s

| Time | Who | Says | Screen | Action |
| --- | --- | --- | --- | --- |
| 0:00-0:08 | Vladimir | "Who rents in Prague? Keep your hand up if it was easy. (pause) Exactly." | Stage, 0 Title | Raise hand |
| 0:08-0:20 | Vladimir | "DOMOVOY found 23 real flats on three portals with Apify, and read the hidden fees with Featherless. I mark one Interested. Nobody is called before that." | Notion | Click `Interested?` = Yes |
| 0:20-0:25 | Danila | "I'm the demo realtor. It's a browser call. ElevenLabs is the voice." | Claude | Vladimir presses Enter on the ready prompt |
| 0:25-0:65 | Call | Short call: answer, commission, accept the first time, "Yes, correct. Bye!" | Phone | Danila skips the energy line |
| 0:65-0:75 | Danila | "Claude checks it, books it, done. Scan to install. The only call you make is: yes." | Start, QR | Switch tab |

## Prep, the 5 minutes before the stage

1. Vladimir's laptop on venue power, Wi-Fi checked with one page load, phone hotspot ready as a backup.
2. Do not disturb on. Close Slack, mail and every notification source.
3. Tabs in one browser window, left to right: Stage (`/stage?full=1`, state 0), Notion stage view, Phone (paired), Google Calendar on the viewing day, Start. Claude Code in its own window. A local copy of the README open offline, scrolled to "A real call".
4. Exactly one paired phone tab, anywhere. Close every other paired tab on both laptops and phones, because any paired tab takes the next call. Never show the address bar of the paired tab: the `?k=` link must not reach the projector.
5. Demo flat **not** pre-marked: `Status` = Shortlisted, `Interested?` empty, `Viewing date` empty. Its `Total monthly` is known and at least 1,500 CZK under the cap. No test "Viewing (demo)" event left in the calendar.
6. Claude session open, prompt `call about my Interested flat` typed and not sent. `doctor.py check` shows 0 fail.
7. Microphone permission granted on the phone tab. Laptop volume at 80%, audio out through the venue HDMI or jack, tested with the ringtone once. Danila stands within 50 cm of the laptop microphone.
8. Zoom: browser at 125% for Notion and Claude text, 150% on the Start tab so the QR is large. Check the Notion stage view hides Agency, Contact, Email and Phone at that zoom.
9. Stage page `STATUS` labels match what the 16:00 rehearsal proved (Calendar event and Whole flow show PLANNED until they pass).

## Open questions for Danila and Vladimir

1. Which screen is the phone? One paired tab on Vladimir's laptop, with Danila speaking into its microphone, or Danila's own laptop with its audio sent to the room? The script assumes Vladimir's laptop.
2. Vladimir's budget cap and the demo flat: which real flat, and is its `Total monthly` at least 1,500 CZK under the cap so the energy line keeps it booked?
3. Does Danila state the commission as 20,000 CZK, or should it match a real number from the listing?
4. Do we keep the PostHog beat at all? It fits only when the call ends by 2:15, which our one real call (80 s) would not have.
5. Who switches tabs during the call: Vladimir, while Danila talks?
6. After 16:00: did Notion `Viewing booked` and the Calendar event run on a real flat? If yes, remove the [only if rehearsed] fallback line and update the stage page chips.
