# DOMOVOY: Prague flat rentals with the real monthly cost

DOMOVOY searches three Czech rental portals at once, **Sreality, Bezrealitky and iDNES**, merges the same flat listed on several portals into one item, and works out what the flat really costs: rent plus service charges and energy per month, and deposit, commission and first payment to move in. Every number keeps the sentence it came from, and anything the listing does not say is marked unknown, never zero.

It was built in one day at the AI Tinkerers Prague hackathon (13 Nov 2026) as the research step of DOMOVOY, an agent that shortlists flats in Notion and calls the realtor to book a viewing.

## What you get

One dataset item per flat:

- **Costs (integer CZK):** `rent`, `services`, `energy`, `total_monthly`, `kauce` (deposit), `commission`, `one_time_fees`, `first_payment`, `move_in_cost`. Energy and missing furniture come from fixed tables and are flagged in `estimated`.
- **Verdict:** `match` is `strong`, `needs_info` or `rejected` against your requirements, with `match_reasons`, `requirements` and `risk_flags` (for example "cheaper on another portal").
- **Evidence:** `evidence` has one entry per extracted field with the quote from the listing and a confidence; `unknowns` lists what to ask the agency or landlord.
- **The flat:** title, address, layout, area, floor, elevator, furnished, move-in date, lease type, pets, photos and the distance to the nearest metro, tram stop and shop.
- **Every portal it appears on:** `sources[]` with portal, URL, rent, commission, collection time and the contact exactly as the portal publishes it. `cross_source` names the cheapest portal.
- **Change tracking:** `property_id` stays stable across runs and portals; `change` is `new`, `changed` or `unchanged`.

The run summary is in the default key-value store under `OUTPUT`: status and counts per portal, flats by match and change, and extraction and Notion counts.

## Input

The only required field is `profile`. The example input searches 2+kk and 2+1 flats in Vinohrady up to 30,000 CZK and takes 5 listings per portal.

```json
{
  "id": "praha-2kk-30k",
  "version": 1,
  "filters": {
    "offer_type": "rent",
    "property_type": "flat",
    "locations": [{"city": "Praha", "citypart": "Vinohrady"}],
    "dispositions": ["2+kk", "2+1"],
    "max_rent": 30000,
    "min_area_m2": 45,
    "sources": ["sreality", "bezrealitky", "idnes"],
    "max_listings": 5
  },
  "household": {"occupants": 1},
  "requirements": {
    "max_total_monthly": 32000,
    "max_upfront": null,
    "elevator": null,
    "lease_types": ["najem"],
    "move_in_by": null,
    "pets_allowed": null
  }
}
```

- `filters` decide which listings are collected. `max_listings` is per portal.
- `requirements` decide the verdict. `max_total_monthly` is required; `null` means "no requirement".
- `household.occupants` is used for fees charged per person.

### Fee extraction: bring your own key

Fees in Czech listings are free text in the description and price note, so DOMOVOY reads them with an LLM: Qwen3-30B on [Featherless](https://featherless.ai) first, then one try on an OpenAI model as fallback. Results are cached by listing text, so a flat is read once.

**This Actor ships with no API keys.** Pass your own `featherlessApiKey` or `openaiApiKey` (both secret inputs). Without either key the run still works: you get the listings, the rent and the layout, but fees stay unknown and most flats come back as `needs_info`. Model calls are billed by your provider, not by Apify.

### Notion (optional)

With `notion.dataSourceId` and `notionToken`, each flat that is not rejected is written to a Notion database as one page, and the profile state is saved so later runs only report new and changed flats. The database must have the DOMOVOY shortlist schema; the Actor checks it before contacting any portal and never changes it. Without Notion, results go to the dataset only and every run reports every flat as new.

## Limits

- **Locations:** **Prague Vinohrady** only for now. Sreality and iDNES skip any other location with a warning in the log; Bezrealitky searches all of Prague for another Prague citypart and fails for another city.
- **Rentals of flats only** (`offer_type` "rent", `property_type` "flat").
- Portals are read without a proxy, with a delay between requests to each portal. A portal that blocks or changes its pages is reported as `failed` or `degraded` in the summary; the other portals still run.
- Sreality is read through its undocumented web API, which can change without notice.
- `katastr_lookup` mode is reserved and returns `NOT_IMPLEMENTED`.

## Personal data

Listings include the realtor's or owner's name, phone and email as the portal publishes them, in `sources[].contact`. That is personal data under GDPR. Use it only for a legitimate purpose, such as contacting the realtor about that flat, and do not resell or republish it. You are responsible for how you store and use the data you collect, and for following each portal's terms.

## Cost

Pay per usage: you pay only the Apify platform usage of your run, plus your own LLM provider if you pass a key. A 5-listing run without keys takes a few minutes of a small container.
