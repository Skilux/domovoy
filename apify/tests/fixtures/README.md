# Fixtures

- `profile_vinohrady.json`: the example profile from docs/prd/actor.md.
- `listing_example.json`, `flatitem_example.json`: built by hand and valid against the models. The contact is "Example Agent", with no phone or email. These are not real flats.
- `texts/*.json`: 5 real Sreality listing texts for the extraction tests in WP4.

## Texts: source and scrubbing

- Source: the Sreality v1 API. Search `GET https://www.sreality.cz/api/v1/estates/search` with the actor.md parameters (Praha, district 5002, rentals), at offsets 0, 20 and 40. Detail `GET https://www.sreality.cz/api/v1/estates/{hash_id}` for 24 listings. Plain HTTP with the default client headers, one request per second.
- Fetched on 13 Nov 2026 during WP0. The team decided at 13:00 that robots.txt and the portal terms do not block this hackathon work. The terms must still be reviewed before the repo goes public.
- `url` is the API detail URL, because the API does not return the public listing URL. WP1 documents the public URL format.
- `description` is the listing text and `price_note` is the portal's price-note field, both as published. The texts are in Czech because that is the source data. Our own notes are in English.
- Realtor and agency names are replaced with `<name>` and `<agency>`. Emails and phone numbers are replaced with `<email>` and `<phone>`. None of these appears in the five texts. No contact data (name, phone, email, agency) is copied.

## Variety covered

| File | Covers |
| --- | --- |
| `sreality-13369420.json` | unfurnished; fees stated (services advance, cellar, parking); deposit 2x the total monthly payment |
| `sreality-1015095372.json` | per-person energy advance; per-flat fees; deposit 1 month's rent; commission 1 month, VAT-free |
| `sreality-270794828.json` | fees missing (the price note lists fees but no amounts); no commission; furnishing not stated |
| `sreality-688549964.json` | fees stated per flat; energy transferred, no amount; deposit 3 months' rent; commission 1 month; fully furnished |
| `sreality-2073653324.json` | per-person fee; energy transferred, no amount; deposit 2 months' rent; commission 1 month, VAT-free |

Not covered: a commission with VAT added on top. None of the 24 listings read has one. The nearest case is the VAT-free commission above.
