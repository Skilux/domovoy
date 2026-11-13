# iDNES fixtures (WP3)

Scrubbed, trimmed copies of iDNES Reality pages. They were fetched with plain HTTP on 13 Nov 2026 during the research and Phase B. `tests/test_idnes.py` reads them.

| File | What it covers |
| --- | --- |
| `list_praha-2_2kk_p1.html` | Praha 2, 2+kk, search page 1: the Korunní listing (Vinohrady, passes the example profile), a Vyšehrad listing (wrong citypart), a Vinohrady listing over 30 000 CZK (over `max_rent`), and one advertisement slot |
| `list_praha-3_2kk_p2.html` | Praha 3, 2+kk, search results: Písecká (passes the profile), V Horní Stromce (43 m2, under `min_area_m2`), a Žižkov listing (wrong citypart), and one advertisement slot |
| `detail_praha-2_korunni.html` | Elevator row present, furnishing from the headline, price note, 12 photos, map centre, enquiry form, agency heading |
| `detail_praha-3_pisecka.html` | No elevator row, no furnishing word, no ready-date row, price note about utilities, name-only heading |
| `detail_praha-3_horni-stromce.html` | "Vybavení" row (partly furnished), discounted price (old and new in the header), commission named in the price note, ready-date row, name-only heading |

## Scrubbing

- Contact values become placeholders: names `<name>`, agencies `<agency>`, phone links `tel:<phone>`, email links `mailto:<email>`. They are escaped in the HTML, so they parse as text. The parser rejects them (`_email` and `_phone` return `None`).
- Descriptions had no emails or phone numbers. Any that appear would become `<email>` or `<phone>`.
- Listing IDs, addresses, prices, descriptions and photo URLs are kept as published. They are public listing data.
- Trimmed to the elements `domovoy/sources/idnes.py` reads: cards, header, parameter rows, price note, description, gallery, map centre, author block, enquiry form. Navigation, ads, similar listings and tracking attributes are dropped.
- The test `test_fixtures_hold_no_email_or_phone_and_only_placeholder_contacts` checks that no email or phone pattern appears, and that each author heading is a placeholder.

The team decided at 13:00 on 13 Nov 2026 that robots.txt and the portal terms do not block this work. Texts and photos may be used in scrubbed fixtures.
