# Demo script: 3 minutes on stage

Third version, 13 Nov 2026, from Vladimir's edits in Notion after the first rehearsal. Stage at 18:00, Prague. The demo runs on Vladimir's laptop. Vladimir is the renter with his real search. Danila plays the demo realtor.

The assistant on screen is ChatGPT (the Codex desktop app, voice input). It runs the DOMOVOY skill, a folder of scripts, on Vladimir's Mac. The search runs live into an empty Notion database. After the call, the viewing is in the calendar, and the katastr check of the flat is on its Notion page.

**The one sentence the room should remember:** "You say what you want, you click Interested once, and DOMOVOY makes the call you hate making."

## The 180 s script

Screens: **Stage** = `domovoy-phone.vercel.app/stage?full=1` (number keys jump to a state: 0 Title, 1 FIND, 7 Close; the ACTOR screen has its own key, see the stage page PR). **ChatGPT** = two Codex threads with the demo brief, side by side: thread 1 for the search, thread 2 for the viewing. **Notion** = the empty stage database, stage view. **Phone** = the paired phone page. **Calendar** = Google Calendar on the viewing day. **Start** = `domovoy-phone.vercel.app/start` with the install QR code.

The demo flat is **the Italská flat**: "2+kk · 61 m² · Vinohrady, Italská" from iDNES. Rent 27,000 CZK, total monthly 30,935 CZK (energy estimated). Move-in cost 143,935 CZK = first payment 30,935 + deposit 54,000 + missing furniture 59,000 (estimated); commission and one-time fees are not stated. Unfurnished. Vladimir's cap is 35,000 CZK a month.

| Time | Who | Says | Screen | Action |
| --- | --- | --- | --- | --- |
| 0:00-0:10 | Vladimir | "Quick question. Who here rents a flat in Prague? Hands up. Keep it up if it was easy." (pause) "That's what I thought." | Stage, 0 Title | Raise his own hand, then drop it |
| 0:10-0:22 | Vladimir | "This is Danila, my teammate. I'm Vladimir, and I'm looking for a flat right now. Three portals, fees hidden in the text, and realtors who only pick up when I'm at work." | Stage, 0 Title | None |
| 0:22-0:30 | Danila | "So we built DOMOVOY: a real-estate agent in your pocket. It's a skill your AI assistant runs. Vladimir just talks to it." | Stage, 1 FIND | Press 1. Vladimir switches to ChatGPT thread 1 |
| 0:30-0:38 | Vladimir | Into ChatGPT, by voice: "Find me apartments to rent in Vinohrady, 2+kk, under thirty-five thousand a month." | ChatGPT, thread 1 | Hold the voice key, speak, send |
| 0:38-0:52 | Vladimir | "ChatGPT is running our Apify Actor. We built it today; it's public on the Apify Store, scan the code. It searches Sreality, Bezrealitky and iDNES at once, and a Featherless model reads the fees hidden in the text." | Stage, ACTOR screen with the QR code | Press the ACTOR key. Leave it up while he speaks |
| 0:52-1:04 | Vladimir | "And here they come. Italská, in Vinohrady. It's unfurnished, and the move-in cost shows it: deposit, first month and estimated furniture. About a hundred and forty-four thousand. Empty means unknown, not zero." | Notion, stage database | Switch to Notion. Point at Move-in cost, then one empty cell (Commission) |
| 1:04-1:18 | Vladimir | "I like this one. Interested: yes. This one, no." (click) "Normally I'd now call a realtor and juggle three calendars. Instead, I ask DOMOVOY." Into ChatGPT, by voice: "Schedule a viewing for my Interested flat." | Notion, then ChatGPT thread 2 | `Interested?` = Yes on the Italská row; `Interested?` = No on one other row. Switch to thread 2, record, send |
| 1:18-1:28 | Danila | "Full honesty: I'm the realtor today. It's a browser call, no phone network, and ElevenLabs is the voice." | ChatGPT, then Phone | ChatGPT reads the calendar. Switch to the phone tab when it rings |
| 1:28-2:13 | Call | See the call plan below | Phone | Danila clicks Accept and answers into the laptop microphone |
| 2:13-2:23 | Vladimir | "It checked the time against my calendar and the cost against my budget, and booked it. Here it is in my calendar." | Calendar | **[only if rehearsed]** Click the event. **Fallback line:** "This is the result from this call. The calendar step ran in our tests, not yet on this flat." Show the result in ChatGPT |
| 2:23-2:45 | Vladimir | "Then it does what I never do: it checks the land register, from an extract bought before the talk. The owner is a company and the flat is mortgaged. So my viewing questions: who signs for the company, does the bank agree? And if the landlord isn't the owner, it's a sublet that needs the owner's consent." | Notion, the Italská page | **[only if rehearsed]** Open the Italská page, scrolled to the Katastr check: risk and questions. Keep the land register details toggle closed |
| 2:45-3:00 | Danila | "So: Apify finds the flats, Featherless the hidden fees, ElevenLabs makes the call, the land register gets checked, it all lands in Notion, and PostHog learns from every flat Vladimir rejects. Scan to install it. The only call you make is: yes. Thank you!" | Start, with the QR code | Switch to the Start tab, zoomed so the QR fills a third of the screen |

**Timing the rehearsal must prove.** The search takes about a minute with a warm cache, so it is still running when voice message 2 goes out at 1:15. That is why the viewing goes to thread 2. If thread 2 waits for thread 1 anyway, the phone rings late: then cut the katastr beat to one sentence ("It also checks the land register; it's on the Notion page.") and keep the closing.

## The call plan, 45 s

The agent's lines are not scripted. Danila's lines are. He answers every open question in one line, so the agent has nothing left to ask, and he accepts the first time offered.

| Time in call | Agent (ElevenLabs) | Danila, demo realtor |
| --- | --- | --- |
| 0-5 s | Rings with the Nokia 3310 ringtone | Clicks Accept. "Hello, this is Daniel." |
| 5-12 s | "Hi Daniel, I'm an AI assistant, no body, just a calendar, calling for Vladimir about the flat in Italská." | "An AI with a calendar? Finally, someone who is never late. Go ahead." |
| 12-25 s | Asks the first open question: energy, commission, VAT, fees or lease type | "VAT is included, twenty-seven thousand is the full rent. Energy is about two thousand a month. Commission is one month's rent. No other fees, and it's a regular lease." |
| 25-35 s | Proposes the start of Vladimir's first free window | "Yes, [day] at [start time] works for me." |
| 35-45 s | Repeats the day and time and asks for a clear yes | "Yes, correct. See you there. Bye!" |
| 45-48 s | Says goodbye, saves the result, ends the call | Stays silent until the call screen closes |

Rules for Danila: never say a real person's name, a phone number or a full address. Say numbers as words. Never decline a time; each round costs about 15 s. Any other question: "I don't know, ask me at the viewing."

## Fallbacks

Never pretend a fallback is live. Say what it is and when it happened.

| If | Say | Show |
| --- | --- | --- |
| No flat appears in Notion within 20 s of voice message 1 | Vladimir: "Three portals, one Wi-Fi. While it works, here is what it found half an hour ago." | The rehearsal database, labelled with its `Collected` time. Mark the Italská row there and go on |
| The search ends without the Italská flat | Vladimir: "Not today's lucky flat. I'll take this one." | Mark the first row with a known `Total monthly` at least 2,500 CZK under the cap. Danila keeps the same lines |
| The phone does not ring within 15 s of the call starting | Danila: "ChatGPT is checking Vladimir's calendar. Even AI needs a second to find a free evening." Wait 10 s more. Then: "Let me show you the call we made today." | The README section "A real call": the transcript of the 80 s call, 13 Nov 2026, synthetic flat |
| The call connects but no audio | Danila: "The agent is talking, the speakers are not. Here is what it says." Keep the call running | The phone page in-call screen, with the live transcript |
| The call fails and must be repeated | Vladimir: "Live demo. Again." | Send voice message 2 again. No reset: `Interested?` = Yes is callable whatever the Status (#124) |
| The call ends Not booked | Vladimir: "And this is the honest part. No match, so no event. ChatGPT tells me why." | The reason on the Notion page. Skip the calendar beat; the katastr beat still runs |
| The katastr step fails | Vladimir: "The land register is shy today. This is the check from our rehearsal." | The rehearsal page's Katastr check, details toggle closed. If there is none, skip to the closing |
| Notion is slow to load or save | Vladimir: "Notion is thinking." | Retry once, then go on in ChatGPT, which prints the same results |
| The network dies | Danila: "The Wi-Fi did not get a viewing. Here is a recording of the stage page and a real transcript." | Switch to the hotspot. Meanwhile the README GIF `docs/img/demo-stage.gif` and the README transcript, from a local copy. Say: "This is a recording, not a live call." |

## Prep, the 30 minutes before the stage

1. **Pre-warm run**, 30 min before: the same search ("Vinohrady, 2+kk, under 35,000") once, into the rehearsal database, so the Actor's extraction cache is warm. Write down its `Collected` time for the first fallback. Pick the flat to reject on stage from its results.
2. **Stage database:** a fresh, empty Notion database, and `notion.data_source_id` in `config.json` points at it. Hide Agency, Contact, Email and Phone in the stage view **and on the page** (property visibility: always hide), because the katastr beat opens the Italská page. Check both at stage zoom.
3. **Budget cap** in `config.json` is 35,000, the number Vladimir says. The rehearsal call used 32,000.
4. **LV bought in prep.** The Italská LV extract is bought before the stage, with Vladimir's yes. Its saved path and the flat's unit number go in the demo brief, not in this file; the call no longer asks for the unit. On stage only the free `lookup --cached-lv` runs.
5. **Calendar:** delete every trial "Viewing" event from today's rehearsals. Check ChatGPT can read and write the calendar.
6. **One paired phone tab**, anywhere. Close every other paired tab on both laptops and phones, because any paired tab takes the next call. Never show the address bar of the paired tab: the `?k=` link must not reach the projector.
7. **ChatGPT:** two Codex threads side by side, both with the demo brief (search; call, then the calendar event, then the katastr lookup with the cached LV). Voice input tested once. `doctor.py check` shows 0 fail.
8. **PostHog:** Danila's sync of `Interested?` = No from the stage database to PostHog is running.
9. **Stage page:** the deployed `/stage` has the ACTOR screen; press its key once to check the QR scans.
10. `caffeinate -d` running. Do not disturb on. Close Slack, mail and every notification source.
11. Laptop on venue power, Wi-Fi checked with one page load, phone **hotspot** on and joined once.
12. Tabs in one browser window, left to right: Stage (`/stage?full=1`, state 0), Notion stage view, Phone (paired), Google Calendar on the viewing day, Start. ChatGPT in its own window. A local copy of the README open offline, scrolled to "A real call".
13. Microphone permission granted on the phone tab and for ChatGPT voice input. Laptop volume at 80%, audio out through the venue HDMI or jack, tested with the ringtone once. Danila stands within 50 cm of the laptop microphone.
14. Zoom: browser at 125% for Notion, 150% on the Start tab so the QR is large. ChatGPT text large enough to read from the back row.
