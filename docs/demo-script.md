# Demo script: 3 minutes on stage

Second version, 13 Nov 2026, after the first rehearsal at about 15:55. Stage at 18:00, Prague. The demo runs on Vladimir's laptop. Vladimir is the renter with his real search. Danila plays the demo realtor.

**What changed from the first version.** The assistant on screen is ChatGPT (the ChatGPT / Codex desktop app, voice input), not Claude. It runs the same DOMOVOY skill, a folder of scripts, on Vladimir's Mac. The search now runs live on stage into an empty Notion database. Vladimir marks the flat in Notion and asks for the viewing by voice. After the call, ChatGPT runs the katastr check on its own and puts the viewing in the calendar with that summary. PostHog is dropped from the stage: it does not fit next to a live search, a call and the katastr check.

**Promise of the talk:** in 3 minutes you see a real renter ask for flats out loud, approve one real flat, and an AI agent call to book the viewing and check the flat in the land register, live.

**The one sentence the room should remember:** "You say what you want, you click Interested once, and DOMOVOY makes the call you hate making."

## What we may claim

| Claim | State on 13 Nov 2026, before 18:00 | How we say it |
| --- | --- | --- |
| The Actor search runs live on stage | True if pre-warmed. Actor build 0.2.6, three portals in parallel, each flat streams to Notion as soon as it is ready. About 1 min end to end with a warm extraction cache; platform runs measured 24 s for 12 flats | "Apify is collecting these right now." After it ends: "Collected at [time from the `Collected` column], a minute ago." |
| Flats from Sreality, Bezrealitky and iDNES in Notion | True | Say the count ChatGPT reports, not a number from rehearsal |
| Fees read from listing text, unknowns stay unknown | True | Point at one empty cell: "unknown, not zero" |
| Estimated costs are estimates | True. The Italská flat's energy and missing furniture are estimates | "Energy is estimated" when pointing at Total monthly |
| A live voice call booked a viewing | True once, on a synthetic flat, 80 s. [Update with the 15:55 and later rehearsal results] | "Our first real call today took 80 seconds" |
| The call is a browser call | True. No phone network, the real listing agent is never called | Danila says it plainly before the call |
| The realtor is real | False. Danila plays a demo role | Danila says it, as a joke and as a fact |
| Katastr check of the flat | The LV extract is bought before the stage; on stage only the free analysis of that saved file runs | "The extract was bought before the talk; the analysis runs now. It's an informative check, not legal advice." |
| The whole flow on a real flat, ending in a Calendar event with the katastr summary | Not run end to end yet | Shown live only if the rehearsal passes. Beats marked **[only if rehearsed]** |
| PostHog learning loop | Partly built, run on synthetic test data | Not on stage. README only |

## The 180 s script

Screens: **Stage** = `domovoy-phone.vercel.app/stage?full=1` (number keys jump to a state: 0 Title, 1 FIND, 7 Close). **ChatGPT** = the Codex desktop app session with the demo brief. **Notion** = the empty stage database, stage view. **Phone** = the paired phone page. **Calendar** = Google Calendar on the viewing day. **Start** = `domovoy-phone.vercel.app/start` with the QR code.

The demo flat is **the Italská flat**: "2+kk · 61 m² · Vinohrady, Italská" from iDNES, address [Italská, house number TBD]. Rent 27,000 CZK, total monthly 30,935 CZK (energy estimated), move-in cost 143,935 CZK (without commission and one-time fees; with estimated energy and furniture), deposit 54,000 CZK, unfurnished (missing furniture about 59,000 CZK, estimated), lease type unknown. Vladimir's cap is 35,000 CZK a month, so the flat has 4,065 CZK of room.

| Time | Who | Says | Screen | Action |
| --- | --- | --- | --- | --- |
| 0:00-0:12 | Vladimir | "Quick question. Who here rents a flat in Prague? Hands up. Now keep your hand up if it was easy to get it." (pause) "Yes. That's what I thought." | Stage, 0 Title | Raise his own hand, then drop it |
| 0:12-0:22 | Vladimir | "I'm Vladimir, and I'm looking for a flat right now. Three portals. Fees hidden in the text. And realtors only answer the phone when I'm at work." | Stage, 0 Title | None |
| 0:22-0:30 | Danila | "So we built DOMOVOY. A real-estate agent in your pocket. It's a skill your AI assistant runs. Vladimir just talks to it." | Stage, 1 FIND | Press 1. Vladimir switches to ChatGPT |
| 0:30-0:43 | Vladimir | Into ChatGPT, by voice: "Find me apartments to rent in Vinohrady, 2+kk, under thirty-five thousand a month." | ChatGPT | Hold the voice key, speak, send. The transcript appears; ChatGPT starts the search |
| 0:43-0:52 | Vladimir | "ChatGPT is calling our Apify Actor. Three portals at once: Sreality, Bezrealitky, iDNES. Watch Notion." | Notion, empty stage database | Switch to Notion. Pages appear one by one |
| 0:52-1:00 | Vladimir | "There's the first one. Italská, in Vinohrady. A Featherless model read the fees out of the listing text, so this is the real monthly cost: thirty-one thousand, energy estimated. Empty means unknown, not zero." | Notion | Point at the Italská row: Total monthly, then one empty cell (Lease type or Commission) |
| 1:00-1:06 | Vladimir | "Nobody gets a call until I say so. I like this one. Interested: yes." Then into ChatGPT, by voice: "Schedule a viewing for my Interested flat." | Notion, then ChatGPT | Click `Interested?` = Yes on the Italská row. Switch to ChatGPT, record, send |
| 1:06-1:15 | Danila | "Full honesty: I'm the realtor today. Demo role. It's a browser call, no phone network, no real realtor. ChatGPT is reading Vladimir's calendar first." | ChatGPT, then Phone | Switch to the phone tab when it rings |
| 1:15-2:10 | Call | See [the call plan](#the-call-plan-45-to-55-s). ElevenLabs is the voice. | Phone | Danila clicks Accept and answers into the laptop microphone |
| 2:10-2:20 | Vladimir | "ChatGPT doesn't just trust the agent. It checks the time is in my free window and the monthly total is still under my budget. VAT included, so it is." | ChatGPT | Point at the result lines: time, `Viewing booked` |
| 2:20-2:40 | Vladimir | "And now it does what I never do before a viewing. It reads the flat's record in the land register, the katastr: owners, mortgage, easements, pending changes. The extract was bought before the talk; the analysis runs now. It's an informative check, not legal advice. And it writes my questions for the viewing." | ChatGPT, then Notion page | **[only if rehearsed]** ChatGPT runs the katastr lookup and shows its reply (no names in it). Open the Italská page, scrolled to the Katastr check risks and questions. Never put the owners line on the projector |
| 2:40-2:47 | Vladimir | "And here's the viewing in my calendar, with that summary in it." | Calendar | **[only if rehearsed]** Click the event. **Fallback line:** "This is the result from this call. The calendar step ran in our tests, not yet on this flat." Show the result in ChatGPT |
| 2:47-3:00 | Danila | "Hands up again: who wants their next viewing booked like this? (pause) Good. Scan this, install it in your own agent, and the only call you make is: yes. Thank you!" | Start, with the QR code | Switch to the Start tab, zoomed so the QR fills a third of the screen |

**Timing that the rehearsal must prove.** The table assumes the search command returns by about 1:10, so the voice message sent at 1:06 is handled at once. The call takes 45 to 55 s, not the 12 to 20 s of the first rehearsal notes: it has four topics (VAT, unit, owner, time). If the search takes the full minute, ChatGPT holds the second message until the search returns, and the phone rings at about 1:50. Then cut the katastr beat to one sentence ("It also checks the land register; it's on the Notion page.") and go to the calendar. If the rehearsal shows more than 30 s from send to the search's end, send the second voice message in a second ChatGPT thread, open beside the first, so the call does not wait for the search.

**PostHog: dropped from the stage.** It needs about 15 s that the live search and the katastr check now use. The stage page state 6 LEARN stays, unused.

## The call plan, 45 to 55 s

On stage Danila accepts the first time offered. He answers in short sentences. The agent must get two facts the katastr check needs: the unit number and who the landlord is. If the agent does not ask for them by 30 s, Danila volunteers both in one line.

The agent's lines are not scripted. These are what it is expected to say. Danila's lines are the script.

| Time in call | Agent (ElevenLabs) | Danila, demo realtor |
| --- | --- | --- |
| 0-5 s | Rings with the Nokia 3310 ringtone | Clicks Accept. "Hello, this is Daniel." |
| 5-12 s | "Hi Daniel, I'm an AI assistant, no body, just a calendar, calling for Vladimir about the flat in Italská." | "An AI with a calendar? Finally, someone who is never late. Go ahead." |
| 12-22 s | Asks whether the rent includes VAT, or another unknown | "VAT is included. Twenty-seven thousand is the full rent." |
| 22-32 s | Asks for the unit number and the landlord | "It's unit [unit number], top floor. The owner is a private person; the name is on the contract." |
| 32-42 s | Proposes the start of Vladimir's first free window | "Yes, [day] at [start time] works for me." |
| 42-52 s | Repeats the day and time and asks for a clear yes | "Yes, correct. See you there. Bye!" |
| 52-55 s | Says goodbye, saves the result, ends the call | Stays silent until the call screen closes |

If Danila has to volunteer: "And before you ask: it's unit [unit number], and the owner is a private person, the name is on the contract."

Rules for Danila: never say a real person's name, a phone number or a full real address. Say numbers as words. Do not decline any time, because each round costs about 15 s. Do not name any new monthly cost: the flat has only 4,065 CZK of room under the cap, and VAT is included. Any other question: "I don't know, ask me at the viewing." If the agent makes a joke, laugh once and answer the question.

## What Vladimir says and clicks

- **Voice message 1, at 0:30:** "Find me apartments to rent in Vinohrady, 2+kk, under thirty-five thousand a month." ChatGPT turns it into the search profile and runs `search.py run`. The pre-warm run used the same profile, so nothing new has to be decided.
- **Notion click at 1:00:** on the Italská row in the stage view, set `Interested?` to **Yes**. Nothing else. He does not change `Status` by hand.
- **Voice message 2, at 1:02:** "Schedule a viewing for my Interested flat." ChatGPT reads the calendar, runs `call.py run`, then, as the demo brief tells it, runs `katastr.py lookup --cached-lv` on the LV bought in prep with the unit from the call, and creates the calendar event with the summary.

## Light moments

1. The raised hands at 0:00. The room answers the question with their arms down.
2. The agent's own first line, "no body, just a calendar", and Danila's answer "Finally, someone who is never late." It is about the AI, not the realtor.
3. Vladimir: "It does what I never do before a viewing." Everyone in the room knows they never read the land register either.
4. The closing: "the only call you make is: yes."

## Sponsor lines, one each

| Sponsor | Line | Beat |
| --- | --- | --- |
| Apify | "ChatGPT is calling our Apify Actor. Three portals at once." | 0:43 |
| Featherless | "A Featherless model read the fees out of the listing text." | 0:52 |
| Notion | "Watch Notion." and "Nobody gets a call until I say so." | 0:43, 1:00 |
| ElevenLabs | "ElevenLabs is the voice." Danila says it as he clicks Accept | 1:15 |
| PostHog | Not on stage. README only | — |

## Fallbacks

Never pretend a fallback is live. Say what it is and when it happened.

| If | Say | Show |
| --- | --- | --- |
| No flat appears in Notion within 20 s of sending voice message 1 | Vladimir: "Three portals, one Wi-Fi. While it works, here is what it found an hour ago." | The rehearsal database, labelled with its `Collected` time. Mark the Italská row there and go on |
| The search ends without the Italská flat | Vladimir: "Not today's lucky flat. I'll take this one." | Mark the first row with a known `Total monthly` at least 2,000 CZK under the cap. Danila keeps the same lines |
| The phone does not ring within 15 s of the call starting | Danila: "ChatGPT is checking Vladimir's calendar. Even AI needs a second to find a free evening." Wait 10 s more. Then: "Let me show you the call we made today." | The README section "A real call": the transcript of the 80 s call, 13 Nov 2026, synthetic flat |
| The call connects but no audio | Danila: "The agent is talking, the speakers are not. Here is what it says." Keep the call running; the in-call screen shows the live transcript | The phone page in-call screen |
| The call fails and must be repeated | Vladimir: "Live demo. Again." | Reset the Italská flat's `Status` to Shortlisted (the one-line reset in prep), then send voice message 2 again. Until the pending change that stops `Status` from blocking a repeat call is merged, the reset is required |
| The call ends Not booked | Vladimir: "And this is the honest part. No match, so no event. ChatGPT tells me why." | The reason written on the Notion page. Skip the katastr and calendar beats |
| The katastr step fails | Vladimir: "The land register is shy today. This is the check from our rehearsal." | Only if one exists: the rehearsal's Katastr check section, scrolled past the owners line. Otherwise skip to the calendar |
| Notion is slow to load or save | Vladimir: "Notion is thinking." | Retry once, then go on in ChatGPT, which prints the same results |
| The network dies | Danila: "The Wi-Fi did not get a viewing. Here is the recording of the stage page and a real transcript." | The README GIF `docs/img/demo-stage.gif` and the README transcript, from a local copy of the repo. Say: "This is a recording of our stage page, not a live call." Switch to the hotspot for the closing QR |

## Cut-down version, 75 s

| Time | Who | Says | Screen | Action |
| --- | --- | --- | --- | --- |
| 0:00-0:08 | Vladimir | "Who rents in Prague? Keep your hand up if it was easy. (pause) Exactly." | Stage, 0 Title | Raise hand |
| 0:08-0:15 | Vladimir | Into ChatGPT, by voice: "Find me apartments in Vinohrady, 2+kk, under thirty-five thousand." | ChatGPT | Send |
| 0:15-0:25 | Vladimir | "Apify searches three portals live, Featherless reads the hidden fees. I mark one Interested. Nobody is called before that." | Notion | Click `Interested?` = Yes on the Italská row, then voice: "Schedule a viewing." |
| 0:25-0:30 | Danila | "I'm the demo realtor. It's a browser call. ElevenLabs is the voice." | Phone | Accept when it rings |
| 0:30-1:05 | Call | Short call: VAT is included, unit [unit number], accept the first time, "Yes, correct. Bye!" | Phone | Danila folds the unit and owner into one line |
| 1:05-1:15 | Danila | "ChatGPT checks it, checks the land register, books it. Scan to install. The only call you make is: yes." | Start, QR | Switch tab |

## Prep, the 30 minutes before the stage

1. **Pre-warm run**, 30 min before: the same search ("Vinohrady, 2+kk, under 35,000") once, into the rehearsal database, so the Actor's extraction cache is warm and the profile is in `config.json`. Write down its `Collected` time for the network fallback.
2. **Stage database:** a fresh, empty Notion database, and `notion.data_source_id` in `config.json` points at it. Its stage view hides Agency, Contact, Email and Phone; check that at stage zoom.
3. **Demo flat state**, if the Italská page exists before the stage (for example after a dry run into the stage database, then emptied of all other rows): `Status` = Shortlisted, `Interested?` empty, `Viewing date` empty. Otherwise the live search creates it in that state.
4. **LV bought in prep.** Billed katastr steps need Vladimir's yes; give it and buy the Italská flat's LV XML before the stage. Check the saved file's path is in the demo brief. On stage only the free `lookup --cached-lv` runs.
5. **Calendar:** delete every trial "Viewing" event from today's rehearsals. Check ChatGPT can read and write the calendar.
6. **One paired phone tab**, anywhere. Close every other paired tab on both laptops and phones, because any paired tab takes the next call. Never show the address bar of the paired tab: the `?k=` link must not reach the projector.
7. **ChatGPT:** the Codex desktop app open with a session that has the demo brief (search, then call, then katastr lookup with the cached LV, then the calendar event with the summary). Voice input tested once. `doctor.py check` shows 0 fail. The one-line `Status` reset command is in a terminal tab, not typed.
8. `caffeinate -d` running, so the laptop never sleeps. Do not disturb on. Close Slack, mail and every notification source.
9. Laptop on venue power, Wi-Fi checked with one page load, phone **hotspot** on and joined once.
10. Tabs in one browser window, left to right: Stage (`/stage?full=1`, state 0), Notion stage view, Phone (paired), Google Calendar on the viewing day, Start. ChatGPT in its own window. A local copy of the README open offline, scrolled to "A real call".
11. Microphone permission granted on the phone tab and for ChatGPT voice input. Laptop volume at 80%, audio out through the venue HDMI or jack, tested with the ringtone once. Danila stands within 50 cm of the laptop microphone.
12. Zoom: browser at 125% for Notion, 150% on the Start tab so the QR is large. ChatGPT text large enough to read from the back row.

## Open questions for Danila and Vladimir

1. Does the voice agent ask for the unit number and the landlord today? If not, Danila volunteers them (line above), or the `call_context` asks for them; that is Danila's lane.
2. The calendar event "with that summary": SKILL.md says to create the event with exactly the description `call.py` prints. Adding the katastr summary needs a SKILL.md change (shared) or a line in the demo brief that the team agrees to.
3. Repeat calls: the pending change that stops `Status` from blocking a repeat call needs Danila's OK. Until then, which exact command resets the flat to Shortlisted? It is not in the skill yet.
4. Can the Codex desktop app take voice message 2 while `search.py run` is still running, or does it queue it? The answer decides between one thread and two.
5. The house number and unit of the Italská flat are placeholders here. They stay out of the repo; Danila needs the unit number on a card, not in this file.
6. Which screen is the phone? The script assumes one paired tab on Vladimir's laptop, with Danila speaking into its microphone.
7. Who switches tabs during the call: Vladimir, while Danila talks?
8. After the rehearsal: did the calendar event and the katastr step run on the Italská flat? If yes, remove the [only if rehearsed] marks and update the stage page chips.
