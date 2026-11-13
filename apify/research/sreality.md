# Sreality research (WP1, Phase A)

**Status: access permitted for all three portals by team decision (13 Nov 2026, 13:00). Sreality was first permitted at 12:53. Phase A confirmations are done on the Sreality v1 JSON API with plain HTTP.** The HTML detail page could not be checked (section 5). No browser capture was run.

- Date: 13 Nov 2026
- Scope: research only, no source code
- Client: plain HTTP, `User-Agent: DOMOVOY-research/0.1`, `Accept: application/json`, no cookies, no JavaScript
- Raw responses: kept outside the repo, in the orchestration workspace's research-evidence folder. Nothing raw is in this repo.

## 1. Access basis

- **Decision:** team decision, 13 Nov 2026, 13:00 (Vladimir): agent scraping of Sreality, Bezrealitky and iDNES is permitted for this hackathon. The organizers allow it, so robots.txt and terms-of-service or content-reuse clauses do not apply here. Sreality was first permitted at 12:53 on a verbal OK from a Sreality representative at the hackathon. No name is recorded here. Recorded in [docs/decisions.md](../../docs/decisions.md).
- **Context, kept on record:** `robots.txt` (fetched 13 Nov 2026) says `User-agent: *` / `Disallow: /`, and `Disallow: /api/` for SeznamBot. Our client falls under `*`. The 13:00 decision says this does not block us for the hackathon. No written confirmation is on file, and the team has not required one.

## 2. Requests made after the decision

| # | Request | Result |
| --- | --- | --- |
| 1 | Search, Praha 2 (`locality_district_id=5002`), `limit=100`, `offset=0` | 200, 100 items, `total` 132 |
| 2 | Search, `locality_district_id=5003,5010`, `limit=100` | 200, 100 items, `total` 349 |
| 3 | Search as 1, `offset=100` | 200, 32 items |
| 4 | Search, `locality_region_id=10`, `limit=500` | 200, 500 items, `total` 1643 |
| 5–7 | Detail `GET /api/v1/estates/{hash_id}`, three listings | 200 each |
| 8 | Detail page URL (HTML) | 302 to a Seznam login autologin, see section 5 |
| 9 | One listing image from Sreality's image CDN, with resize parameters | 200, JPEG, 400×300 |

**Rate deviation (disclosed):** request 8 went through urllib's automatic redirect following. The redirect led to `login.seznam.cz` and back, and urllib's loop guard stopped it after about 2 seconds. That was a short burst above one request per second, and it reached a second host. The count was not logged; my estimate is about 6–8 requests. No further HTML requests were made. The script now records redirects and does not follow them.

Otherwise the rate stayed within the limit. Responses took 0.3–1.3 s (2.2 MB for the 500-item page). No 429 or throttling was seen.

## 3. Verified results: v1 JSON API

### 3.1 Access path

- Search and detail return 200 to a plain client with no cookies and no JavaScript.
- **Playwright: not needed** for this path.

### 3.2 Search

| Parameter | Verified value |
| --- | --- |
| `category_main_cb` | `1` = Byty (flats) |
| `category_type_cb` | `2` = Pronájem (rent) |
| `category_sub_cb` | `4` = 2+kk, `5` = 2+1 (`4,5` for both) |
| `locality_district_id` | Praha 2 = `5002`, Praha 3 = `5003`, Praha 10 = `5010`. Comma lists work (`5003,5010`). |
| `locality_region_id` | `10` = Hlavní město Praha (Prague) |
| `limit` | Our default was 100. `500` returned 500 items. Not tested above 500. |
| `offset` | Record offset, not a page number. `offset=100` returned records 101–132. |
| Response | `results[]`, `pagination {limit, offset, total}`, `status_code` |

Disposition codes: in the first 100 Praha 2 items, code `4` (2+kk) appeared 71 times and code `5` (2+1) 29 times. The detail codebook uses the same names.

**Vinohrady filter (client-side):** keep items where `locality.citypart == "Vinohrady"`, an exact match. Vinohrady occurs in all three districts. In the 232 items sampled (all 132 Praha 2 items plus the first 100 Praha 3+10 items): Praha 2 91 of 132, Praha 3 19 of 49, Praha 10 9 of 51. Other `citypart` values include the empty string and "Praha 3", so do not match loosely. I did not find a server-side citypart filter and did not test one.

### 3.3 Detail

- Body shape: `{"result": {...}, "status_code", "status_message"}`. Read values from `result`.
- Carries almost every `Listing` field (section 4). The URL and the owner flag are missing.
- `hash_id` is an integer. All 232 sampled search items had distinct `hash_id` values.

### 3.4 Images

- Detail `advert_images[]`: objects with `url`, `width`, `height`, `order`, `kind`, `alt`, `id`. The sample originals are 1200×800 (3:2).
- Search `advert_images`: a list of URL strings (3 in the first item). `advert_images_all`: 14 objects in the first item.
- URL format: protocol-relative, `//d18-a.sdn.cz/d_18/c_img_<code>/<token>/<name>.jpeg`. Store as `https:` URLs.
- Resize: `?fl=res,400,300,3|shr,,20|jpg,90` returned HTTP 200, `image/jpeg`, 400×300. A 3:2 original that comes out 4:3 suggests a crop. The meaning of mode `3` was not checked.

### 3.5 Null and placeholder handling

- Detail, three samples: 31, 32 and 31 top-level null keys. 26 keys are null in all three, for example `acceptance_year`, `balcony_area`, `building_area`, `object_age`, `refundable_deposit`, `project`, `sale_date`. Nine keys are null in some samples only, for example `floors`, `floor_area`, `garage_count`, `parking`, `lease_type_cb`, `tenant_not_pay_commission`.
- Codebook objects `{name, value}`: value `0` with a placeholder name ("- vyber stav", "- nezadáno", and similar) means not entered. Map `0` to `null`.
- Empty strings: `cost_of_living` (all three samples), `matterport_url` (all three), `sdn_energy_performance_attachment_url` (empty or null). Map `""` to `null`.
- Search `locality.housenumber` is null in 103 of 232 items and `""` in 5. `streetnumber` is null in 103 and `""` in 7. `municipality` and `ward` are null in all 232.
- Search `poi_*_distance` (14 integer fields) are present in all 232 items. Whether `0` means "none in range" is not verified.
- `price_czk` is a float with whole values in every sample. Convert to int.

### 3.6 Codebook values seen

| Field | Values seen |
| --- | --- |
| `category_sub_cb` | 4 = 2+kk, 5 = 2+1 |
| `ownership` | 1 = Osobní (personal). Other codes not seen. |
| `elevator` | 1 = Ano, 0 = not entered |
| `furnished` | 1 = Ano, 2 = Ne, 0 = not entered |
| `object_location` | 1 = Centrum obce, 0 = not entered |
| `building_condition` | 1 = Velmi dobrý, 9 = Po rekonstrukci |
| `building_type` | 2 = Cihlová (brick) |
| `energy_efficiency_rating_cb` | 7 = G, 0 = not entered |
| `lease_type_cb` | 1 = Nájem (present in 1 of 3 samples) |
| `price_unit_cb` | 2 = za měsíc (per month) |
| `price_currency_cb` | 1 = Kč |

### 3.7 Contact location (structure only, no values recorded)

- **Detail `user`** (the listing's person): `user_name`, `user_email`, `user_phones` (list), `user_id`, `image`, `broker_rating`, `broker_review_count`.
- **Detail `premise`** (the agency): `name`, `seo_name`, `web_url`, `web_visible_url`, `logo`, `company` (`company_ic`, `company_subject_id`, `sos_custom_advert_card`), `locality`, `review_count`, `review_score`, `id`.
- **Search items:** `premise` (SEO names only), `premise_id`, `premise_logo`, `user_id`. No names or phones.
- Consequence for fixtures: scrub every `user` and `premise` value. Scrub emails and phones inside `advert_description` as well, per the implementation plan's fixture rule.

## 4. Field mapping into `Listing`

| Listing field | Sreality source | Observed |
| --- | --- | --- |
| `portal` | constant `sreality` | — |
| `source_id` | `hash_id` (int, as string) | present, distinct |
| `url` | **not in the JSON** | pattern unverified, section 5 |
| `title` | `advert_name` | e.g. "Pronájem bytu 2+kk 40 m²" |
| `address` | `locality.street` with `locality.citypart` and `locality.district` | street present in samples; house number often null |
| `address_detail.street` | `locality.street` | present |
| `address_detail.house_number` | `locality.housenumber` / `streetnumber` | often null or `""` |
| `address_detail.citypart` | `locality.citypart` | Vinohrady etc.; may be `""` |
| `address_detail.district` | `locality.district` | "Praha 2", "Praha 3", "Praha 10" |
| `address_detail.gps` | `locality.gps_lat`, `gps_lon` | present in search and detail |
| `address_detail.precision` | `locality.inaccuracy_type` | Seen in 232 items: `street` 95, `gps` 71, `address` 58, `ward` 4, `quarter` 4. Proposed: address → exact, street → street, ward and quarter → district. `gps` has no proposed mapping (open). |
| `disposition` | `category_sub_cb.name` | "2+kk", "2+1" |
| `area_m2` | `usable_area` (detail only) | int: 40, 75, 74 in samples |
| `floor` | `floor_number` (detail) | int: 0, 2, 2. Meaning of 0 not checked. |
| `elevator` | `elevator` codebook | 1 → true; 0 → null |
| `furnished` | `furnished` codebook | 1 → true; 2 → false; 0 → null |
| `rent` | `price_czk` (float, monthly) | 25,000; 28,000; 60,000 in samples |
| `price_note` | `price_note` | free text, 29–116 characters in samples |
| `description` | `advert_description` | free text, 976 characters in sample 1; may hold contacts (scrub) |
| `ready_date` | `ready_date` | ISO date, e.g. 2026-11-10 |
| `ownership` | `ownership` codebook | 1 = Osobní; others unknown |
| `is_owner_listing` | **no field seen** | owner listings not sampled; open |
| `contact` | `user` (person) and `premise` (agency) | structure in section 3.7 |
| `photos` | detail `advert_images[].url` | 14 in sample 1; `https:` prefix; resize as in 3.4 |
| `poi` | `poi_*_distance` (search items) | 14 integer fields, present in all 232 items |

**Not in the API** (must come from extraction or stay `null`): `kauce` (`refundable_deposit` is null in all samples); energy and service costs (`cost_of_living` is empty in all samples); `pets_allowed`, `permanent_residence`, `lease_length_months`; `url`; `is_owner_listing`.

Two partial mappings: `commission` is a float that was `0.0` in all three samples, and its unit is unknown, so do not map it yet. `lease_type` maps from `lease_type_cb` (1 = Nájem), but it is null in two of three samples. `move_in_date` has no direct source; `ready_date` is the closest field.

## 5. Not verified, open

- **Detail page URL.** Request 8 reached a Seznam SSO autologin on `login.seznam.cz`. A client without cookies loops on it. I did not handle cookies or the login flow. That is a session mechanism outside the v1 JSON API scope the team approved, and the 13:00 decision covers robots.txt and terms clauses, not logins. Candidate pattern: `https://www.sreality.cz/detail/pronajem/byt/{2+kk|2+1}/{slug}/{hash_id}`. The slug is unconfirmed. The team should decide whether to accept a browser-checked pattern or wait for a canonical URL.
- **`is_owner_listing`:** no field seen; owner listings not sampled.
- **`commission` unit:** float, `0.0` in all three samples.
- **`gps` precision** (`inaccuracy_type` = `gps`, 71 of 232 items): no exact mapping.
- **`floor_number` = 0:** meaning not checked. Probably ground floor.
- **`poi_*` zero:** meaning not checked.
- **Server-side citypart filter:** not found.
- **Stability:** the API is undocumented, and the PRD says it can change. Rerun the smoke test before each checkpoint.

## 6. REA

No REA browser capture was run. The brief allows plain HTTP for these confirmations. REA tool schemas were loaded earlier, but no capture or analysis of sreality.cz was done.

## 7. Notes for the team

- Decision row: one row in [docs/decisions.md](../../docs/decisions.md), in this commit, covers all three portals.
- Shared file: `docs/decisions.md` is a shared path. Its change needs the other lane's OK on the PR.
- Cross-lane: under the 13:00 decision, robots.txt does not block WP2 or WP3. The polite-rate and no-contact rules still apply.
- The Sreality verbal OK is not in writing. The team decided not to require written confirmation.
