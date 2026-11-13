# Run it in another city or country

What a person must change to use DOMOVOY outside Prague. This is a guide read from the code on 13 Nov 2026, not a tested path: nobody has run another city.

## Short answer

- **Already city-neutral:** the phone server and call flow (`phone/api/`, `phone/lib/store.js`, `skill/domovoy/scripts/call.py`), the Notion shortlist as a store (`skill/domovoy/scripts/notion.py`), the PostHog loop (`posthog/`), the calendar step, and the stages of the Actor after the sources (dedup, costs, requirement checks, Notion sink). They work on fields, not on a city.
- **Small edits:** timezone, currency labels, the voice prompt, cost assumptions.
- **Real work:** a listing source for the new market. Each of the three existing sources is about 500 lines and reads one Czech portal.

## What is tied to Prague or Czechia today

| Tied to Prague or Czechia | Where it lives | What to change |
| --- | --- | --- |
| The three portals: Sreality, Bezrealitky, iDNES | `apify/domovoy/sources/sreality.py`, `bezrealitky.py`, `idnes.py` | Write a source for your portal: one class with `collect` and `normalize` (the `Source` protocol in `sources/base.py`), registered in `sources/__init__.py`. Add its name to `Portal` in `apify/domovoy/models.py`, to both copies of `profile.schema.json` and to the `Sources` options in `notion_contract.json` |
| City and district lookup inside each source. Sreality accepts only `city` = `Praha` with a known `citypart` (today only Vinohrady, mapped to Praha 2, 3 and 10). Bezrealitky refuses any city but Praha. iDNES has codes for Praha 1 to 10 only | `DISTRICT_IDS` and `CITYPART_DISTRICTS` in `sreality.py`; `PRAHA`, `VINOHRADY` and `REGION_BY_CITYPART` in `bezrealitky.py`; `DISTRICT_CODES`, `CITYPART_DISTRICTS` and `CITY_DISTRICTS` in `idnes.py` | Another Czech city on the same portals: add its district ids and codes to these tables and relax the `Praha` checks. Another country: not needed, your own source maps its own locations. The profile itself is neutral: `locations` is a list of `{city, citypart}` strings |
| Flat layout codes such as `2+kk` | The `Disposition` pattern in `apify/domovoy/models.py` and in `profile.schema.json` (it accepts `1+kk` to `9+kk` and `1+1` to `9+1`) | Replace the pattern with your market's way to name a layout, for example a room count, and map it in your source |
| Metro distance | `metro_m` in `models.py`, filled by Sreality only; Notion column `Metro m` | Fill it from your portal if it gives a distance to transit, or leave it `null` |
| Currency: money is integer CZK | Notion number format `koruna` on eight columns in `skill/domovoy/reference/notion_contract.json`; the text "CZK" in `call.py` (page summary), `phone/src/main.js` (call screen), `phone/agent/prompt.md` and `agent.json`, `posthog/loop.py` (finding text); `czk` keys in the extraction prompt | The numbers are plain integers, so no math changes. Change the Notion format and the "CZK" labels. Keep one currency per database |
| Timezone `Europe/Prague` | `PRAGUE` in `apify/domovoy/models.py`; `TZ` in `phone/src/main.js`, `phone/src/booked.js` and `phone/lib/context.js`; `timezone` in `phone/agent/agent.json`; `calendar.timezone` in `skill/domovoy/config.example.json` | Set your zone in each of the six places. `config.json` is a setting; the other five are constants in code or in the agent config. `skill/domovoy/scripts/demo.py` uses a fixed +01:00 for its synthetic window |
| Czech rental terms in extraction | `SYSTEM_PROMPT` in `apify/domovoy/extraction/prompt.py`: it says "Czech rental listing from Sreality" and teaches the model Czech phrases for rent, services, energy advances, deposit (`kauce`), commission (`provize`), VAT (`DPH`), sublet, furnishing, pets | Rewrite the phrase examples in your listing language and bump `PROMPT_VERSION`. The 14 output keys can stay, so the cost code keeps working |
| Czech lease words as values | `LeaseType` is `najem` or `podnajem` in `models.py`, in `call_context.schema.json` and in `call_context_values` of `notion_contract.json` | Keep them as internal codes for lease and sublet, or rename them in all three places. Renaming is a contract change |
| Cost assumptions | `apify/domovoy/costs/tables.py`: energy advance per m² in CZK, furniture prices in CZK, Czech VAT 21% on commission. The file marks the first two as unsourced assumptions | Replace the three tables with numbers for your market. The formulas in `costs/compute.py` (monthly total, upfront cash) are generic |
| Street matching for dedup | `normalize_street` in `apify/domovoy/dedup/keys.py` strips "ulice", "ul." and "č.p." | Add your language's words for "street" and house number. Distance matching needs no change |
| Voice agent language and persona | `phone/agent/prompt.md` (English only, money in whole CZK), `phone/agent/agent.json` (`language: en`, first message, voice id, example windows) | Translate the prompt and first message, set `language`, pick a voice for that language, then run `node phone/agent/sync-agent.mjs` |
| Date wording on the call screen | `Intl.DateTimeFormat('en-GB', ...)` in `phone/src/main.js`, `phone/src/booked.js`, `phone/lib/context.js` | Change the locale if the call is not in English |
| Notion column names | `skill/domovoy/reference/notion_contract.json`: English names, with one Czech word, `Kauce` | Nothing has to change. To rename a column, change the contract, its copy in `apify/domovoy/schemas/`, and the readers in `notion.py` and `apify/domovoy/notion/sink.py` together |

## Checklist

1. **Pick the portal and write the source.** Copy the shape of `apify/domovoy/sources/bezrealitky.py`, keep fixtures of real pages for tests, and register the source. Check the portal's terms before you collect from it.
2. **Fix the profile.** Set `locations`, the layout codes and `sources` for your market, and update `profile.schema.json` in both places.
3. **Localize extraction and costs.** Rewrite the phrase examples in `extraction/prompt.py`, bump `PROMPT_VERSION`, and replace the tables in `costs/tables.py`. Run the Actor on 20 listings and read the quotes it kept.
4. **Set currency and timezone.** Notion number format, the "CZK" labels, and the six timezone places in the table.
5. **Localize the call.** Prompt, first message, language and voice in `phone/agent/`, sync the agent, and make one test call before a real one.

Then run `python3 skill/domovoy/scripts/doctor.py check`. It checks keys and services only; it does not know which city you search.
