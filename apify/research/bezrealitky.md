# Bezrealitky research (WP2, Phase A)

Status: research only, no source code. Observed live on 13 Nov 2026, about 12:40–13:40 CET. Re-check before Phase B. Raw HTML, JSON captures and the request log are kept outside the repo and are not committed.

**Team decision (13:00):** this is a government hackathon sponsored by the real-estate portals, and the organisers allow agent scraping of all portals. robots.txt and the terms / content-reuse clauses do not block this project, so Phase B does not stop on them. Rules that still hold: at most 3 concurrent requests with a 0.5–1 s delay; no realtor names, phones or emails in the repo, which goes public at 17:30.

Scope: rental flats (`offerType` PRONAJEM, `estateType` BYT).

## 1. Recommendation

- **Access path: plain HTTP GET, no Playwright.** Listing and detail data are server-side JSON, either in `__NEXT_DATA__` on HTML pages or from the page's own `_next/data` JSON route. No GraphQL call and no header changes.
- **Phase B entry point (region JSON route):** `GET https://www.bezrealitky.cz/_next/data/<buildId>/cs/vyhledat.json?estateType=BYT&offerType=PRONAJEM&country=ceska-republika&currency=CZK&locale=CS&location=exact&regionOsmIds=R<osmId>&page=N`. Verified with a plain request on 13 Nov: HTTP 200, JSON (about 36 KB), and the region filter is applied server-side. Vinohrady (`R428841`) returned `totalCount` 71. `<buildId>` is `__NEXT_DATA__.buildId` from any `/vypis/` page (`47e6d89414dc43cfe44900f6fc5fa9339f433218` on 13 Nov). It changes on each deploy, so read it first. Page 2 of this route is not yet verified.
- **Verified fallback (HTML):** `GET https://www.bezrealitky.cz/vypis/nabidka-pronajem/byt/praha-vinohrady?page=N` (71 flats; pages 1 and 2 checked, 15 per page) and `…/byt/praha?page=N` (Praha, 1067 flats).
- **`regionOsmIds` needs the `R` prefix.** The bare id (428841) returned HTTP 500. Do not retry it.
- **Owner default:** `is_owner_listing = True`, as a documented assumption (section 8).

## 2. Endpoints

| Purpose | Request | Where the data is | Verified |
| --- | --- | --- | --- |
| Region listing, JSON (Phase B entry) | `GET https://www.bezrealitky.cz/_next/data/<buildId>/cs/vyhledat.json?…&regionOsmIds=R<osmId>&page=N` | `pageProps.apolloCache.ROOT_QUERY["listAdverts({…})"]` (`list`, `totalCount`); `pageProps.filter` | Vinohrady page 1 (71 flats), HTTP 200, JSON; page 2 not yet |
| Region listing, HTML | `GET https://www.bezrealitky.cz/vypis/nabidka-pronajem/byt/<region>?page=N` (`praha`, `praha-vinohrady`) | `__NEXT_DATA__`, same keys as below | `praha-vinohrady` pages 1–2; `praha` page 1 |
| Nationwide listing, HTML | `GET https://www.bezrealitky.cz/vypis/nabidka-pronajem/byt?page=N` | `__NEXT_DATA__` | pages 1 and 2 |
| Detail | `GET https://www.bezrealitky.cz/nemovitosti-byty-domy/<id>-<slug>` | `props.pageProps.origAdvert` (110 keys); JSON-LD `RealEstateListing` | 3 pages |
| Photo | `GET https://api.bezrealitky.cz/media/cache/record_thumb/…jpeg` (also `record_main`) | `Image:<id>` entries in the Apollo cache | 1 request, HTTP 200, image/jpeg |
| Sitemap | `https://www.bezrealitky.cz/sitemap/sitemap.xml` (index of 8 child sitemaps) | — | index and `sitemap_list_1.xml` fetched |

The listing filter echoes `limit` 15, `offset` 15×(N−1), `order` TIMEORDER_DESC (newest first), `currency` CZK, `country` ceska-republika, `offerType` [PRONAJEM], `estateType` [BYT]. Region requests also carry `location` exact and `regionOsmIds`.

## 3. Pagination and page size

- Page size is 15 on every route checked.
- Nationwide page 2: offset 15, no ids in common with page 1.
- `praha-vinohrady` page 2: offset 15, no ids in common with page 1 (verified).
- The JSON route's page 2 is still to be checked.
- Nationwide `totalCount` was 4925 (last page 329). The search-UI header showed a different count (2 100) for the map view, so use only the SSR `totalCount`.
- Larger page sizes were not tested.
- Newest-first ordering can shift items between pages during a scan. Dedupe by `id`.

## 4. Regions

Region data comes from `regionTree` on each detail page. Region URLs use the same ids.

| Node | subType | osmId | Verified use |
| --- | --- | --- | --- |
| Praha | REGION | 435514 (`R435514`) | `/vypis/…/byt/praha`: 1067 flats (HTTP 200). Bezrealitky region id 486. |
| Praha-Vinohrady | CITY_DISTRICT | 428841 (`R428841`) | JSON route: 71 flats. `/vypis/…/byt/praha-vinohrady`: 71 flats (page 2 checked). Not in the sitemap, but served. |
| Praha-Žižkov | CITY_DISTRICT | 428824 | Praha 3 (zip 130 00). Not yet used as a region request. |

- `/vypis/…/byt/praha-2` returns 404. Praha 2, Praha 3 and Praha 10 are not nodes; the granularity is the quarter. Quarter ids for Nové Město and Vršovice are not yet observed. Phase B can collect them from `regionTree` on detail pages.
- The quarter is also in the list payload. In every list item checked, the last comma-separated part of `address({"locale":"CS"})` is "Praha - <quarter>" (for example "Praha - Vinohrady" or "Praha - Žižkov"). Use it as the citypart filter, and treat `regionTree` as the authority on the detail page.
- Data quirks: some titles repeat the prefix ("Praha - Praha-Praha-Vinohrady"). `zip` is a string ("130 00") on some adverts and an integer (12000) on others. Normalise it to five digits.
- The sitemap lists 125 flat-rental region URLs (`/vypis/nabidka-pronajem/byt/<region>`) and includes `praha`. It does not list `praha-vinohrady`.

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

Fallback when the enum is UNDEFINED: parse JSON-LD `about.name` (for example "Byt 2+kk, 63 m²"). The disposition parameter on the JSON route was not tested, so Phase B filters disposition client-side on the list payload.

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
| address_detail.citypart | last part of `address` (L); `regionTree` quarter (D) | "Praha - <quarter>" in the list; `regionTree` is authoritative |
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
| is_owner_listing | assumption | `True` by default; see section 8 |
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

## 8. is_owner_listing: assumption (team default)

**Default: `is_owner_listing = True`.** This is a documented assumption. Bezrealitky's premise is listings without agencies. Set it to False only if an advert field clearly marks an agency. None was found.

Evidence checked on three detail pages (1089140, 686144, 932647):

| Candidate | Observed | Verdict |
| --- | --- | --- |
| Title suffix "• bez RK" | all three | Appears on every sampled listing, including a developer project. Read as a site-wide suffix. If it is per-listing, it supports the default. |
| JSON-LD `offers.seller` `@type` | Person on all three | Not discriminating |
| `showOwnest` | false on all three | Meaning unknown; not used |
| `messageData.messageType` | LINK, REQUIRE_PREMIUM, MESSAGE | Contact channel, not ownership |
| `type` | FLATIO, DOKONALY_NAJEMNIK, UNDEFINED | Programme type |
| Owner-only filter | not seen | Not tested |

**Review flag:** the list tag "Developerský projekt" appears on some listings (932647, 711719 and 692399 in page 1). Developer projects may be agency-built. It is not a clear agency marker, so the default stays True. Phase B should log these rows for review.

To confirm the default, compare one owner listing and one agency listing (open item 2).

## 9. Browser runs and the page's own requests

Two Chromium runs with the scenario tool (launch mode, default environment, no extra headers) on the listing page. The second run also recorded network traffic.

- The network run recorded 137 transactions: map tiles, ads and analytics, Cookiebot, Google tags. None failed. All were 2xx or 3xx.
- The page's own API calls on load (`POST api.bezrealitky.cz/graphql/`, all 200): `InfoBanner` (locale CS) once, and `MarkerList` (map markers) twice. There is no client-side `listAdverts`, so the list rows come from the server.
- The page's own script fetched `/_next/data/<buildId>/cs/vyhledat.json` (200). The plain request to the same route, with a region filter, also returned 200 (section 1).
- The Cookiebot consent banner appears on first load. The runs did not accept or reject it.
- A reCAPTCHA anchor document from www.google.com loaded on the page. No challenge was shown.
- After load, the single-page app rewrote `/vypis/…` to `/vyhledat?…`. I did not click any filter, did not navigate to `/vyhledat` myself, and made no further browser runs on `/vypis/`.

## 10. robots.txt, terms and the team decision

**Team decision (13:00):** see the top of this note. Under that decision, the robots.txt rules below do not block Phase B. Phase B uses `/_next/data/…/vyhledat.json` as its entry point.

robots.txt (`https://www.bezrealitky.cz/robots.txt`, HTTP 200, 338 bytes, 12:42 CET):
- `User-agent: *`
- Disallow: `/vyhledat*`, `/search*`, `/moje-bezrealitky/*`, `/*callbackUrl=*`, `/centrum-sluzeb/bezrealitky-hypoteka/form*`, `/centrum-sluzeb/bezrealitky-hypoteka*price=*`, `/centrum-sluzeb/bezrealitky-hypoteka?*`
- No Crawl-delay. Sitemap listed.
- The listing and detail paths are not disallowed.
- The `_next/data/…/vyhledat.json` route is the `/vyhledat` page's data, so it falls under `/vyhledat*` in substance. The team decision covers it. This is recorded for transparency.

`https://api.bezrealitky.cz/robots.txt`: HTTP 403 (nginx) to a plain request, at 12:50 CET. Not retried.

**Terms of service (one attempt, as asked):**
- Footer link: `https://www.bezrealitky.cz/informace/smluvni-podminky` (linked from the detail page HTML). HTTP 200, about 55 KB of HTML.
- The page is an index of terms documents. Its text, about 2,200 characters, has no clause on automated access or scraping.
- Relevant line (Czech, verbatim): "Proto si vyhrazujeme právo nedoručovat nevyžádanou či jinak obtěžující poštu našim klientům." English: "We therefore reserve the right not to deliver unsolicited or otherwise annoying mail to our clients." The page also sets contractual penalties for estate agencies and brokers who ignore the prohibitions. Phase B messages no one, so this does not affect us.
- The main "Obchodní podmínky serveru Bezrealitky" is a PDF on the API host: `https://api.bezrealitky.cz/page-file/obchodni-podminky-bezrealitky-1794559591.pdf`. Not fetched. The one-attempt limit applied, and the API host returns 403 to plain requests. The team's content-reuse decision covers it. Read it before publication if time allows.

## 11. Rate behaviour and blockers

- Plain requests so far: 17 in total, all sequential, default curl user agent, no extra headers. They covered the listing pages, robots.txt, the sitemap index and one child, the terms page, three region pages, region page 2, three details, one photo, the API robots.txt, and two `vyhledat.json` variant tests.
- Results: all 200, except the API robots.txt (403), the `vyhledat.json` variant with a bare osmId (500), and `praha-2` (404).
- No 429 responses and no CAPTCHA.
- **Resolved:** the region filter (section 1).
- **Remaining blockers:** (a) the API host is 403 to plain requests (GraphQL, not used); (b) the main terms PDF is not read; (c) no positive owner signal (default in place); (d) the buildId changes on deploy, so Phase B must read it each run.

## 12. Phase B decision

- **Entry point:** the region JSON route (section 1). First read `buildId` from one `/vypis/` page, then request `…/_next/data/<buildId>/cs/vyhledat.json?…&regionOsmIds=R428841&page=N`.
- **Fallback:** `/vypis/nabidka-pronajem/byt/praha-vinohrady?page=N` (HTML, `__NEXT_DATA__`).
- **Demo scope:** Vinohrady, 71 flats, 5 pages of 15. Praha (1067 flats, 72 pages) if needed.
- **Pacing:** at most 3 concurrent requests, 0.5–1 s delay.
- **Access:** plain HTTP only. No Playwright, so the plain Python Docker image is enough.
- **Fields:** citypart from the list `address`; disposition from the list `disposition`, with the `about.name` fallback on the detail page. Fetch a detail page only for candidates that pass the list filters.
- **Owner:** `is_owner_listing = True` by default. Flag rows with the "Developerský projekt" tag.
- Keep 15 per page and dedupe by `id`.

## 13. Open items

1. **JSON route page 2** (`&page=2` on `vyhledat.json`): verify on the first Phase B run.
2. **Owner signal:** the default is True. Review the "Developerský projekt" rows, and find one owner and one agency listing to confirm.
3. **Quarter ids for Praha 2 and Praha 10:** not observed. Collect them from `regionTree`.
4. **Main terms PDF:** read before publication (API host; plain requests return 403).
5. **Field semantics:** the `charges` split (energy vs services), the meaning of `fee`, and whether a deposit of 0 means none or unknown.
6. **Page sizes above 15:** untested.
