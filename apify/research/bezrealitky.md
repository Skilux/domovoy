# Bezrealitky research (WP2, Phase A)

Status: research only, no source code. Observed live on 13 Nov 2026, about 12:40–13:30 CET. Re-check before Phase B. Raw HTML, JSON captures and the request log are kept outside the repo and are not committed.

Scope: rental flats (`offerType` PRONAJEM, `estateType` BYT), nationwide list, Praha as the target area.

## 1. Recommendation

- **Access path: plain HTTP GET of server-rendered pages.** Each page embeds its data as JSON in `<script id="__NEXT_DATA__">` (Next.js `getServerSideProps`, `__N_SSP: true`). Parse that JSON. No JavaScript execution and no GraphQL call is needed.
- **Playwright: not needed** for listings, details or photos. The page's own client-side API calls are for the map and an info banner only (section 9).
- **Open blocker for Phase B: region targeting.** Only the nationwide list is verified on an allowed path. The Praha and Vinohrady filter lives on the search route `/vyhledat`, which robots.txt disallows (sections 4 and 10). The team must decide before Phase B can target Vinohrady without a full nationwide scan.

## 2. Endpoints

| Purpose | Request | Where the data is | Verified |
| --- | --- | --- | --- |
| Listing page N | `GET https://www.bezrealitky.cz/vypis/nabidka-pronajem/byt?page=N` | `props.pageProps.apolloCache.ROOT_QUERY["listAdverts({…})"]`: `list` (refs `Advert:<id>`) and `totalCount`; `props.pageProps.filter` | pages 1 and 2, HTTP 200 |
| Detail | `GET https://www.bezrealitky.cz/nemovitosti-byty-domy/<id>-<slug>` | `props.pageProps.origAdvert` (110 keys); JSON-LD `RealEstateListing` | 3 pages, HTTP 200 |
| Photo | `GET https://api.bezrealitky.cz/media/cache/record_thumb/…jpeg` (also `record_main`) | `Image:<id>` entries in the Apollo cache | 1 request, HTTP 200, image/jpeg |
| Sitemap | `https://www.bezrealitky.cz/sitemap/sitemap.xml` | listed in robots.txt | not fetched |

The listing filter echoes: `limit` 15, `offset` 15×(N−1), `order` TIMEORDER_DESC (newest first), `currency` CZK, `country` ceska-republika, `offerType` [PRONAJEM], `estateType` [BYT], `regionOsmIds` [] (empty means nationwide). Only `page` is needed in the URL.

## 3. Pagination and page size

- Page size is 15. Page 2 returns offset 15 and shares no ids with page 1.
- `totalCount` was 4925 nationwide on 13 Nov 2026, so the last page is 329 (the HTML links `page=329`). The search-UI header showed a different count (2 100) for the map view; use the SSR `totalCount` only for the nationwide scan.
- A larger page size was not tested. The page uses 15.
- Newest-first ordering can shift items between pages while a scan runs. Dedupe by `id`.

## 4. Regions

Region data comes from `regionTree` on each detail page.

| Node | subType | osmId | Notes |
| --- | --- | --- | --- |
| Praha | REGION | 435514 | Bezrealitky region id 486 |
| Praha-Vinohrady | CITY_DISTRICT | 428841 | Vinohrady citypart; `zip` 120 00 observed |
| Praha-Žižkov | CITY_DISTRICT | 428824 | Praha 3 (`zip` 130 00 observed) |

- **Praha 2, Praha 3 and Praha 10 are not nodes.** The granularity is the quarter (Vinohrady, Žižkov, Nové Město, Vršovice and so on). Phase B should use quarter ids. Only Vinohrady and Žižkov ids are observed; Nové Město and Vršovice ids are not.
- **Vinohrady filter:** the id 428841 is known. The URL parameter that applies it on an allowed path is **not verified**. The page's `MarkerList` GraphQL query takes `regionOsmIds` (observed empty), and the search UI applies region filters on `/vyhledat`, which robots.txt disallows. Without a verified filter, Phase B can scan the nationwide list (329 pages) or fetch one detail per flat to read `regionTree`.
- Data quirks: some titles repeat the prefix ("Praha - Praha-Praha-Vinohrady"). `zip` is a string ("130 00") on some adverts and an integer (12000) on others. Normalise it to five digits.

## 5. Disposition codes

| Enum | Label | Basis |
| --- | --- | --- |
| DISP_1_KK | 1+kk | enum matches the label shown in the browser, 2 adverts |
| DISP_1_1 | 1+1 | matches, 2 adverts |
| DISP_2_KK | 2+kk | matches, 4 adverts |
| DISP_2_1 | 2+1 | enum seen in page 2 data; label 2+1 seen in the browser on another advert; inferred from the pattern |
| DISP_3_KK | 3+kk | matches, 2 adverts |
| DISP_3_1 | 3+1 | matches, 2 adverts |
| DISP_4_KK | 4+kk | enum only (page 2) |
| GARSONIERA | studio | enum only (page 2) |
| UNDEFINED | none | not stated; 2 of 15 on page 1; the browser shows no label |

Fallback when the enum is UNDEFINED: parse the JSON-LD `about.name` (for example "Byt 2+kk, 63 m²").

## 6. Field mapping into `Listing`

Source keys: `D` = detail page (`origAdvert` or JSON-LD). `L` = list payload (`Advert` in the Apollo cache). Some fields exist only on details.

| Listing field | Source | Notes and gaps |
| --- | --- | --- |
| portal | constant `bezrealitky` | |
| source_id | `id` (string) | |
| url | `https://www.bezrealitky.cz/nemovitosti-byty-domy/` + `uri` | `uri` is `<id>-<slug>`; the length matches the JSON-LD `url` |
| collected_at | Actor clock | |
| title | JSON-LD `name` (D) | Example pattern: "Pronájem bytu 2+kk • 63 m² • <street> • Praha - Vinohrady • bez RK". The list has alt text only. |
| address | `address({"locale":"CS"})` (L, D) | Street and city, no house number |
| address_detail.street | `street` (D) | |
| address_detail.house_number | not exposed | Withheld (`withHouseNumber:false`) |
| address_detail.citypart | `regionTree` quarter (D) | The list has no region |
| address_detail.district | `regionTree` REGION | "Praha" |
| address_detail.gps | `gps` {lat, lng} (L, D) | Present on 30 of 30 list items observed |
| address_detail.precision | inference | `street`, because the house number is withheld |
| disposition | `disposition` (L, D); fallback JSON-LD `about.name` | Section 5 |
| area_m2 | `surface` (L, D) | Integer m² |
| floor | `etage` (D) | `floor` and `totalFloors` are null in all three details |
| elevator | `lift` (D); list tag "Výtah" (L) | |
| furnished | `equipped` (D): VYBAVENY, NEVYBAVENY | "Partly" is the tag "Částečně vybaveno" (L); its enum was not observed |
| rent | `price` (L, D) | Integer CZK. `originalPrice` equals it unless `isDiscounted`. |
| price_note | `dataJson` (L, D): `priceNote.cs` / `.en` / `.sk` | Null when there is no note. The list payload carries it, so no detail request is needed. |
| description | `description` (D) | Not in the list payload |
| ready_date | `availableFrom` (epoch seconds) converted to a date in Europe/Prague | Midnight Prague in all three details |
| ownership | `ownership` | "UNDEFINED" in all three details: unknown |
| is_owner_listing | none | See section 8. Null for now. |
| contact | JSON-LD `offers.seller`; `messageData` (D) | Section 7 |
| photos | `publicImages` (D: 9; L: 3 via `publicImages({"limit":3})`); `mainImage` | Section 7 |
| poi | list tags such as "MHD 4 minuty pěšky" (walk minutes to public transport) | Metres to metro or shops not observed. `poiData` was "[]" in the detail that had it. |
| kauce (deposit) | `deposit` (D) | 50000 and 71800, each 2× rent. 0 appeared on a short-term listing with a no-deposit note. Treat 0 as unknown unless the note says so. |
| fee | `fee` (D) | 23290 on a flat whose note reads "administrative fee, lower for shorter leases". Probably the platform fee, not a commission. To confirm. |
| charges | `charges`, `utilityCharges`, `serviceCharges` (L, D) | Flat A: utilities 5571, services 0. Flat B: services 4000, utilities 0. The energy vs services split is not stated. |
| commission | no field | Not observed on the three details |
| lease type, short term | `shortTerm` (bool), `roommate` (bool) (D) | Tag "Krátkodobé" shown in the browser. `lease_type` is otherwise unknown. |
| move-in date | `availableFrom` | |
| pets, permanent residence, missing furniture | not in the payload | Unknown |
| Bezrealitky type | `type` (L, D): FLATIO, DOKONALY_NAJEMNIK, UNDEFINED | Programme tags, not ownership |
| first_seen, last_seen | Actor | |

## 7. Contact data and photos

**Contact (structure only, no values recorded here):**
- JSON-LD `offers.seller` has `@type` (Person on all three details) and `name`. No JSON-LD block has telephone, email or contactPoint keys.
- `messageData` in `origAdvert` has `messageType` (LINK, REQUIRE_PREMIUM and MESSAGE observed), `requireLogin` (bool) and `url`.
- Each detail HTML has one `tel:` and one `mailto:` anchor. Their origin is not verified. The listing page has none.
- The seller name is personal data. It goes to Notion only, never to the repo or fixtures.

**Photos:**
- Pattern: `https://api.bezrealitky.cz/media/cache/<filter>/data/images/advert/<n>/<n>/<hash>.jpeg`. Filters: `record_main` (1600×1200 observed) and `record_thumb`.
- One plain GET of a `record_thumb` returned 200, image/jpeg, 21,629 bytes.

## 8. is_owner_listing: not found

The brief asked how the page signals owner or agency. I tested these candidates on three details: 1089140, 686144 and 932647 (932647 is listed as "Developerský projekt").

| Candidate | Observed | Verdict |
| --- | --- | --- |
| Title suffix "• bez RK" | all three | Appears on every sampled listing, including a developer project. It reads as a site-wide title suffix, not an owner marker. |
| JSON-LD `offers.seller` `@type` | Person on all three | Not discriminating |
| `showOwnest` | false on all three | Meaning unknown; not used |
| `messageData.messageType` | LINK, REQUIRE_PREMIUM, MESSAGE | Contact channel, not ownership |
| `type` | FLATIO, DOKONALY_NAJEMNIK, UNDEFINED | Programme type |
| Owner-only filter | not seen on the allowed path | Cannot be tested without the search route |

Result: `is_owner_listing` stays null. To close this, compare one listing known to be from an owner with one known to be from an agency.

## 9. Browser runs and the page's own requests

Two Chromium runs with the scenario tool (launch mode, default environment, no extra headers) on the listing page. The second run also recorded network traffic.

- The network run recorded 137 transactions: map tiles, ads and analytics, Cookiebot, Google tags. None failed. All were 2xx or 3xx.
- The page's own API calls on load (`POST api.bezrealitky.cz/graphql/`, all 200): `InfoBanner` (locale CS) once, and `MarkerList` (map markers) twice. There is no client-side `listAdverts`, so the list rows come from the server HTML.
- The Cookiebot consent banner appears on first load. The runs did not accept or reject it.
- A reCAPTCHA anchor document from www.google.com loaded on the page. No challenge was shown.
- **Robots disclosure:** after load, the single-page app rewrote `/vypis/…` to `/vyhledat?…`. The network run recorded one `GET /_next/data/<buildId>/cs/vyhledat.json` (200), issued by the page's own script. That is the data route for the disallowed search page. The first run also rewrote the URL, so it probably triggered the same fetch, though it was not recorded. I did not click any filter, did not navigate to `/vyhledat` myself, and made no further browser runs on `/vypis/`.

## 10. robots.txt and terms

robots.txt (`https://www.bezrealitky.cz/robots.txt`, fetched once: HTTP 200, 338 bytes, 12:42 CET):
- `User-agent: *`
- Disallow: `/vyhledat*`, `/search*`, `/moje-bezrealitky/*`, `/*callbackUrl=*`, `/centrum-sluzeb/bezrealitky-hypoteka/form*`, `/centrum-sluzeb/bezrealitky-hypoteka*price=*`, `/centrum-sluzeb/bezrealitky-hypoteka?*`
- No Crawl-delay. Sitemap: `https://www.bezrealitky.cz/sitemap/sitemap.xml`.
- The listing path `/vypis/…` and the detail path `/nemovitosti-byty-domy/…` are not disallowed.
- **Phase B must never request** `/vyhledat`, `/search`, or `/_next/data/…/vyhledat.json`.

`https://api.bezrealitky.cz/robots.txt`: HTTP 403 (nginx) to a plain request, at 12:50 CET. Not retried, and no headers changed.

**Terms of service:** not located and not read. The footer is not in the server HTML (`withFooter: false`), and no terms link appeared in the rendered listing after scrolling. Read the terms before the repo goes public at 17:30 (actor.md, open items).

## 11. Rate behaviour and blockers

- Plain requests (curl with its default user agent, no extra headers), one at a time: listing page 1, robots.txt, listing page 2, three detail pages, one photo, the API robots.txt. All returned 200 except the API robots.txt (403). No 429 responses and no CAPTCHA.
- The API host returns 403 to plain requests (GraphQL, per the brief; robots.txt, as above). I did not retry or change headers.
- **Blockers:** (a) no verified region filter on an allowed path; (b) the search UI is disallowed by robots.txt; (c) the API host is 403 to plain requests; (d) no positive owner signal; (e) terms not read.

## 12. Phase B decision

- **Plain HTTP is enough** for listing pages (`?page=N`), detail pages (`origAdvert` JSON) and photos (media path). Playwright is not needed, so the Docker image can stay the plain Python image.
- Pace requests at 0.5–1 s, with at most three in flight (actor.md, section 6).
- Fetch a detail page only for candidates that pass the list-level filters. Description, lift, floor, quarter, seller name and extra photos come from the detail.
- Keep 15 per page, scan newest first, and dedupe by `id`.

## 13. Open items

1. **Region filter on an allowed path** (Vinohrady, osmId 428841). Options: (a) the team approves the search route, which robots.txt disallows; (b) find the verified URL parameter in the static JavaScript bundle; (c) a detail-based quarter check on a nationwide scan (expensive).
2. **Positive owner signal:** one owner listing and one agency listing, then compare their payloads.
3. **Praha 2 and Praha 10 quarter ids:** not observed.
4. **Terms of service:** read before publication.
5. **Field semantics:** the `charges` split (energy vs services), the meaning of `fee`, and whether a deposit of 0 means none or unknown. Confirm on more listings.
6. **Page size above 15:** untested.
