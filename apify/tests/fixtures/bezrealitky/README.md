# Bezrealitky fixtures

Scrubbed payloads for `apify/tests/test_bezrealitky.py`. Captured on 13 Nov 2026 (about 13:00 to 13:12 CET) with plain requests, the same ones the source makes. No header changes.

| File | What it is |
| --- | --- |
| `list_vinohrady_page1.json` | Page 1 of the Vinohrady region from the page's JSON route (`regionOsmIds=R428841`). `totalCount` 71. |
| `list_vinohrady_page2.json` | Page 2 of the same route. `totalCount` 71. Shares no ids with page 1. |
| `detail_686144.json` | Vinohrady, 2+kk, 63 m², rent 25000, no price note. Furnished "none". |
| `detail_932647.json` | Vinohrady developer project, 3+1, 72 m², 20 photos. Used to test the disposition filter. |
| `detail_1089140.json` | Žižkov (Praha 3), disposition not stated, price note present. Used to test the quarter filter. |

## Trimming

- List pages keep only what the list parser reads: the `ROOT_QUERY` `listAdverts` entry (`list`, `totalCount`) and the 15 `Advert` entries, with their id, uri, disposition, surface, price, address, gps, tags and `dataJson`. The buildId for the JSON route was `47e6d89414dc43cfe44900f6fc5fa9339f433218`.
- Detail files hold `advert` (the `origAdvert` keys that `normalize_detail` reads), `jsonld` (the `RealEstateListing` node, trimmed to name, url, about, offers) and `source_url`.

## Scrubbing

- Seller names (`offers.seller.name`) are replaced with `<name>`.
- The `messageData` URL is replaced with `<form-url>` when present.
- Email and phone patterns are replaced with `<email>` and `<phone>`. None were present in these payloads.
- The page's `tel:` and `mailto:` anchors are not in the fixtures. They are identical on every listing, so they belong to the site, not to the advertiser.
- Flatio advert links inside `dataJson` are kept. They are public advert links.
- `@type` keys in the JSON-LD are normal schema.org keys, not email addresses.
