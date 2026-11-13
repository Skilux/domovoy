# iDNES Reality research (WP3, Phase A)

Owner: Vladimir (Actor lane). Status: research only, no source code. Observed live on 13 Nov 2026 (Europe/Prague) on one sample: rentals (`pronájem`, `byty`), 2+kk, Praha 2, 3 and 10. Raw HTML, REA captures, the decoded advertiser terms and the two front-end bundles are kept outside the repo in `research-evidence/idnes/`. No agent names, agency names, phone numbers or emails are recorded here.

Labels: **observed** = seen in the sample; **inferred** = my reading, not yet tested.

## 1. Summary

- **Access path:** plain HTTP GET of server-rendered HTML. Search and detail pages carry every field the portal publishes for a listing; the gaps are in section 7. No JSON API or XHR is needed.
- **Playwright:** not needed. Phase B uses plain HTTP and an HTML parser. Keep the plain Python Docker image.
- **Pagination is incomplete.** The header count (`N inzerátů`) is not the number of reachable cards: Praha 2 shows 30 of 56, Praha 3 shows 53 of 79. Phase B must page until the server redirects, and test splits before claiming completeness.
- **No Vinohrady facet.** Filter on the citypart name in the address text.
- **Robots:** `*/admin.api/*` is disallowed, and the page's own locality autocomplete calls it. The Actor must not call it. Never combine `page=` with `sort=`.
- **Terms:** the site footer prohibits use of texts and photos without MAFRA's consent. Needs a team decision before texts or photos go into Notion or the public repo (section 10).

## 2. Search URLs and pagination

| Purpose | URL | Observed |
| --- | --- | --- |
| Rentals, all Prague | `https://reality.idnes.cz/s/pronajem/byty/praha/` | 200 |
| Rentals, district | `/s/pronajem/byty/praha-<n>/` (n = 1 to 10) | 200 for n = 2, 3, 10 |
| Rentals, disposition in district | `/s/pronajem/byty/<disp>/praha-<n>/`, e.g. `2+kk/praha-2/` | 200 |
| Next page | add `?page=<n>` | observed; a full document navigation in the browser too |
| Sort (page 1 only) | `?sort=nejlevnejsi` or `?sort=nejdrazsi` | seen as links; robots disallows `page=` with `sort=` |

**Page size:** 26 cards on full pages (Praha 2 page 1: 26; Praha 3 pages 1 and 2: 26 each). Praha 10 page 1 had 25.

**Paging end:** asking past the last page returns `302` to the last page (Praha 2, `?page=3` redirects to `?page=2`). Fetch with `follow_redirects=False` and stop on a 3xx or on a page with no cards. Following the redirect would re-fetch page 2 and create duplicates.

| Query (2+kk rentals) | Header `N inzerátů` | JSON-LD count | Cards reachable |
| --- | --- | --- | --- |
| Praha 2 | 56 | 58 | 30 (26 + 4); page 3 redirects |
| Praha 3 | 79 | 74 | 53 (26 + 26 + 1); page 4 not tested |
| Praha 10 | not recorded | 97 | page 1 only checked: 25 cards |

The header and JSON-LD counts disagree with each other and with what pagination exposes. Treat both as non-authoritative. Plain HTTP and the browser agree exactly: Praha 2 page 1 gave the same 26 IDs and page 2 the same 4 IDs in both, with no overlap.

## 3. Region (locality) ids

Source: `GET /search-localities/` (JSON, seen in the browser capture; not matched by any robots rule). It lists regions and districts with codes.

| Area | Code | URL slug |
| --- | --- | --- |
| Hlavní město Praha (region) | `VUSC-19` | `praha` |
| Praha 1 | `MOP-19` | `praha-1` |
| **Praha 2** | **`MOP-27`** | `praha-2` |
| **Praha 3** | **`MOP-35`** | `praha-3` |
| Praha 4 | `MOP-43` | `praha-4` |
| Praha 5 | `MOP-51` | `praha-5` |
| Praha 6 | `MOP-60` | `praha-6` |
| Praha 7 | `MOP-78` | `praha-7` |
| Praha 8 | `MOP-86` | `praha-8` |
| Praha 9 | `MOP-94` | `praha-9` |
| **Praha 10** | **`MOP-108`** | `praha-10` |

The codes match the card links (`s-l=MOP-27` on Praha 2 cards, `MOP-35` on Praha 3, `MOP-108` on Praha 10). Build URLs with the slug.

**Vinohrady has no code.** The directory has no citypart level. Filter on the citypart after ` - ` in the address line, matching the whole name (not a substring: `Vyšehrad` and `Nové Město` also appear in these results).

Vinohrady cards seen per page: Praha 2 page 1: 22 of 26; page 2: 2 of 4. Praha 3 page 1: 11 of 26; page 2: 9 of 26; page 3: 1 of 1. Praha 10 page 1: 3 of 25.

## 4. Disposition and filters

| Disposition | URL segment | Internal code on card links |
| --- | --- | --- |
| 2+kk | `2+kk` | `2k` (observed) |
| 2+1 | `2+1` | not observed |
| 1+kk, 1+1, 3+kk, 3+1, 4+kk, 4+1, 5+kk, 5+1 | same pattern | not observed |
| 6+kk and larger | `6+kk-a-vetsi` | not observed |
| Atypical | `atypicke` | not observed |

Read disposition from the title (`Pronájem bytu 2+kk 56 m²`), not from the URL.

Query facets seen in the Prague filter (inferred to work in combination; not tested):
- `vybaveni` (equipment): `vytah` (elevator), `balkon`, `terasa`, `lodzie`, `sklep` (cellar), `garaz`, `parkovani`, `zahrada`, `bezbarierovy`, `zarizeny` (furnished), `castecne-zarizeny` (partly furnished), `nezarizeny` (unfurnished)
- `vlastnictvi`: `osobni` (personal), `druzstevni` (cooperative)
- `konstrukce`: `cihlova` (brick), `drevena` (wood), `panelova` (panel)
- Condition takes the disposition's path slot: `novostavby`, `po-rekonstrukci`, `dobry-stav`, and others

Facet splits may reach more cards than the cap. Phase B must check whether each split's reachable count matches its header count.

## 5. List page (cards)

Container: `div.c-products__item` (fallback: `div.c-products__list` > `article`, or id prefix `snippet-s-result-article-`).

| Field | Selector or attribute | Example form |
| --- | --- | --- |
| Detail URL | `a.c-products__link[href]` | `https://reality.idnes.cz/detail/pronajem/byt/praha-2-korunni/6ad5ce02475d52a1040d8535/` |
| Listing ID | last URL path segment (also in the `id` of `snippet-s-result-article-<id>`) | `6ad5ce02475d52a1040d8535` |
| Title with disposition and area | `img[alt]` in `.c-products__img` | `Pronájem bytu 2+kk 56 m², Korunní, Praha 2 - Vinohrady` |
| Address line | `p.c-products__info` | `Korunní, Praha 2 - Vinohrady` |
| Rent | `p.c-products__price strong` | `30 000 Kč/měsíc` |
| Thumbnail | first `img[data-src]` | see section 8 |
| Agency | `data-brand` on the card link; `data-fakelink-url` on the agency control | do not record (section 9) |

Cards carry disposition, area, citypart and rent, so the profile's disposition, area, citypart and max-rent checks can run before any detail request.

**Embedded data:** list pages have a page-level JSON-LD `Product` with counts and a price floor only, not listing items. A `dataLayer` push gives `search_region`, which was "Hlavní město Praha" on every list page checked, so it does not help with districts. No `__NEXT_DATA__` or `__INITIAL_STATE__`.

## 6. Detail page and the Listing mapping

The detail page is server-rendered. Data sits in label/value rows (`dt` label, `dd` value) and in a few named blocks. **Select rows by label text, not by position.** Icon-only rows (check icon) mean present.

**Embedded data:** no JSON-LD on detail pages. One `script[type="application/json"][data-maptiler-json]` block holds the map setup: `mtMapOptions.center` (`[lon, lat]`), a GeoJSON line for the highlighted street, and points for similar listings. Ignore the map provider key in it.

Sample: Korunní, Praha 2 (observed).

| Listing field | Source | Sample value | Notes |
| --- | --- | --- | --- |
| `portal` | constant | `idnes` | |
| `source_id` | last segment of the detail URL | `6ad5ce02475d52a1040d8535` | the order number row `Číslo zakázky` (`IDNES-26116`) is a second ID; keep it in `raw_ref` |
| `url` | `link[rel=canonical]` (same as `og:url`) | detail URL above | |
| `collected_at` | fetch time | — | ISO 8601 with offset |
| `title` | `h2` in `div.b-desc` (same as `og:title`) | `Pronájem zařízeného bytu s balkonem Praha 2 - Vinohrady, Korunní` | free text, data only |
| `address` | card address line | `Korunní, Praha 2 - Vinohrady` | |
| `address_detail.street` | text before the first comma | `Korunní` | |
| `address_detail.house_number` | not published | `null` | |
| `address_detail.citypart` | text after `Praha N - ` | `Vinohrady` | |
| `address_detail.district` | `Praha N` | `Praha 2` | |
| `address_detail.gps` | `mtMapOptions.center`, order `[lon, lat]` | lat 50.07543, lon 14.45573 | centre of the highlighted street, **not** the flat |
| `address_detail.precision` | sentence with `nemá přesnou adresu` (no exact address, in a marked area) | `street` (inferred) | exact not observed |
| `disposition` | title | `2+kk` | |
| `area_m2` | `dt` `Užitná plocha` | `56` | usable area |
| `floor` | `dt` `Podlaží` → `3. patro (4. NP)` | `3` | `3. patro` = 4th storey above ground (`4. NP`) |
| `elevator` | `dt` `Výtah` with check icon; description also says "s výtahem" | `true` | absent row = `null`, not `false` |
| `furnished` | title wording `zařízeného` (furnished) | `full` (inferred) | `částečně` = partial, `nezařízeného` = none; no explicit row |
| `rent` | `dt` `Cena` → `30 000 Kč/měsíc` | `30000` | strip NBSP, U+200D and spaces |
| `price_note` | text after `Poznámka k ceně:` | `+ poplatky na služby a energie 6.000 Kč` | services and energy **combined**: 6,000 CZK/month |
| `description` | `div.b-desc` paragraphs | Czech free text | do not copy into the repo |
| `ready_date` / `move_in_date` | `dt` `Datum nastěhování` → `02.01.2027` | `2027-01-02` | DD.MM.YYYY; description also says available from January 2027 |
| `ownership` | `dt` `Vlastnictví` → `osobní` | `personal` | `družstevní` = cooperative |
| `is_owner_listing` | `og:description` names the offering agency (`Nabízí realitní kancelář …`) | `false` | owner listing not observed |
| `contact` | `div.b-author` block | — | section 9 |
| `photos`, `image_url` | gallery images with `/sta/compile/thumbs/` | 14 photos; `image_url` = first (equals `og:image`) | section 8 |
| `poi` | no structured distances | `null` | description names metro and tram in words only |

Other rows on the page, not in the Listing schema: `Stav bytu` (condition, `velmi dobrý stav`), `Konstrukce budovy` (brick), `Počet podlaží budovy` (6), `Balkon` (1 m²), `Sklep` (present), `Internet` (present), `Plyn` (`nezaveden`, gas not connected). **`PENB G` is the energy performance class, not running costs.** Never map it to energy costs.

## 7. Missing or unknown in the sample

- `house_number`: not published. Precision stays `street`.
- `poi` distances: not structured.
- `kauce` (deposit), `commission`, `one_time_fees`: absent for this listing. The listing text has no `kauc`; `provize` appears only in news items. Null.
- `lease_type`, `lease_length_months`, `pets_allowed`, `permanent_residence`: absent. Null.
- `services` and `energy`: not split. Keep the combined amount in `price_note`. Split only through extraction, marked `estimated`.
- `is_owner_listing = true`: not observed. Needs a private-owner listing sample.
- `precision = exact`: not observed.

## 8. Photos

- Format: `https://sta-reality2.1gr.cz/sta/compile/thumbs/<c0>/<c1>/<c2>/<rest>.<ext>`. The path is a 32-character hex digest split as 3 characters and 29 characters (checked on all 200 distinct photo URLs in the saved pages). Extension: `webp` (188) or `jpg` (12).
- One size only. Cards (420×260 display) and the gallery (1018×600 display) use the same URL. Nothing in the URL selects a size.
- Gallery: the first photo has `src`. Lazy photos carry the real URL in `data-lazy` and a placeholder in `src`. Skip `no-image-gallery` and `logo-reality-idnes` URLs. Sample: 14 listing photos.
- Notion cover: an external image URL should suffice (no download). Confirm during WP7.

## 9. Contact data (structure only)

- **Card:** the agency name sits in `data-brand`; an agency control carries `data-fakelink-url` to the agency profile.
- **Detail page:** a `div.b-author` block holds:
  - an agent name in `h2.b-author__title`;
  - an agency link;
  - a **phone** row: `a` with an `href` using the `tel:` scheme, present in static HTML;
  - an **email** row: `a` with an `onclick` handler (about 185 characters) and an `href`. I did not finish classifying the href. Treat email as possibly click-revealed until Phase B checks it;
  - an office-address row (marker icon).
- **Enquiry form** (`form.form-contact`, reCAPTCHA): never submit. Not used.
- Storage: contacts only in the private Notion shortlist (CLAUDE.md). I did not copy any value into this file, a fixture or a summary. Raw HTML in `research-evidence/idnes/` contains them; that folder stays outside the repo.

## 10. robots.txt and terms

**robots.txt** (fetched once, 967 bytes): `User-agent: *`, `Allow: /`, no `Crawl-delay`, no `Sitemap`. Rules that matter here:
- `Disallow: /s/*page=*sort=`: do not combine `page` with `sort`.
- `Disallow: /s/*;` and `/s/*|*`: avoid `;` and `|` in URLs.
- `Disallow: /s/*cena-nad-*`, `/s/*cena-do*sort=`, `/s/*/do-*sort=`, `/s/*priceMin*sort=`, `/s/*priceMax*sort=`: no price filters with sort.
- `Disallow: */admin.api/*`: the page's locality autocomplete (`/admin.api/autocomplete-locality`) is disallowed. **The Actor must not call it.**
- Also disallowed: `*s-localitySelector-locality`, `*addRemoveLocality`, `*s-result-openPopup`, `*popupManager-popups`, `/s/*openHouse`, `/broker-evaluation/*`, `*inquiryFilter`, `*watchdogFilter`, `*estateType*`, `/s/*s-rd` (with an allow for `s-rd=3`).

The planned URLs (`/s/pronajem/byty/<disp>/praha-<n>/?page=<n>` and `/detail/...`) match none of these rules.

**Terms:**
- Site footer, on every page checked (Czech): use of content, including taking over, distributing or further making available texts and photos, is prohibited without MAFRA a.s.'s consent. Storing listing texts or photos, or committing them to the repo, needs a decision.
- General terms for advertising on Reality.iDNES.cz (valid 1 Feb 2026; read from the PDF). They govern advertisers. I searched the decoded text for automation, scraping, crawling, download, database and API wording. The only hits concern the advertiser's admin interface and copyright in listing content. **No explicit anti-scraping clause found.** A legal read is still needed before the repo goes public.
- Privacy: agent names, phones and emails are personal data. Keep them out of the repo.

## 11. Rate behaviour and blockers

- Plain HTTP: 17 GET requests (15 to `reality.idnes.cz`, 2 to the static CDN), spaced at least 1 s apart. All returned 200 or 302. No 403, 429, CAPTCHA or challenge page. A repeat of page 2 returned identical bytes (107,591).
- Browser (REA, launch mode, owned profile, Chromium 157 via Google Chrome): 2 scenarios, 5 page loads. Run 1 had 253 network transactions; no blocks. The page loads reCAPTCHA and consent scripts; I clicked no consent or form controls.
- **Blockers: none.** Open issues: header and JSON-LD counts differ from reachable cards (section 2), and the page calls a disallowed `/admin.api/*` endpoint (section 10).
- No proxy, no header or fingerprint change, no stealth plugin, no CAPTCHA solving.

## 12. Access decision for Phase B

- Plain HTTP (one client, at most 3 concurrent, 0.5 to 1 s delay), HTML parser (lxml or selectolax). No Playwright, no Crawlee. The integrator's Docker decision: plain Python image.
- If the site starts requiring JS or challenges plain clients, stop and report, as the brief says. Run the live smoke test before each checkpoint.

## 13. REA usage and failures

Tools used (results in `research-evidence/idnes/`):
- `capture_browser_scenario`, launch mode, Google Chrome executable, default scope (page origin) × 2. Run 1: start, wait for list, settle, click page 2, wait for a card, settle, click detail, wait for `h1`. All 8 steps completed. Parent evidence `ev_aab33640dcb5393259b78f61d6305ff372c4ca545ac9d7725f32a4063c1f3935`. Run 2 (same up to page 2, DOM captured after each step): parent `ev_dad46623dd6909d06481000d945b6413956d23de4a3f31fe4c8a63208c1a25f6`.
- `inspect_analysis_view`: transactions, network content and DOM text, paged. Output over the MCP limit was saved to files and read locally.
- `analyze_javascript_application` on the two front-end bundles (`frontAsync.js`, `frontHead.js`): 2 files parsed, 0 parse failures. Graph partial (27,951 unknowns, mostly dynamic calls). Routes view empty. No endpoint recovered statically.

Not run, and why:
- `analyze_web_bundle`: needs a loopback CDP target. I did not start one; the static bundle analysis above covers the script step.
- `inspect_api_contract`: no OpenAPI or GraphQL document exists.
- `inspect_web_network_capture`: no HAR file; I read the scenario's own transactions instead.

REA failures and quirks:
- `search_guidance` failed twice: `Structured content does not match the tool's output schema: data must have required property 'result'`. I used the skill's reference files instead.
- `capture_browser_scenario` rejected top-level `capture` keys `dom` and `accessibility`. Valid shape: `after_each_step: ["dom"]` (or `"accessibility"`), plus `at_end`, `events`, `network`, `limits`.
- Results over the MCP size limit are written to a file path rather than returned inline.

## 14. Open items for Phase B (not yet verified)

1. Full listing set: test `sort` on page 1, and splits by disposition, district and facets (`vybaveni`, `vlastnictvi`). Compare each reachable count with its header count. Then choose the query plan.
2. Owner listing sample (`is_owner_listing`).
3. An exact-address listing, to confirm `precision`.
4. Classify the email row (`onclick` against `href`).
5. Browser versus plain parity on a detail page (only list pages compared).
6. Photo count and sizes on other listings (14 seen once).
7. Page 4 for Praha 3, to confirm the paging end.

## 15. Team decisions and flags

- **Content reuse (section 10):** decide whether Notion pages may hold iDNES texts and photos, or only links and derived fields. Suggested default: links and derived fields, no verbatim descriptions, no photo bytes.
- **Public repo at 17:30:** fixtures must be synthetic. No iDNES descriptions, photos or contacts. This file contains none of them.
- **Robots:** keep `/admin.api/*` out of the code.
- **Forms:** the Actor never submits the enquiry form.
