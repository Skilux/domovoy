# Sreality fixtures

Scrubbed copies of responses from the public v1 JSON API, saved on 13 Nov 2026 (see `research/sreality.md`).

- `search_praha2_page1.json`, `search_praha2_page2.json`: search responses for Praha 2, 2+kk and 2+1 rentals, first 8 items of pages 1 and 2. The pagination block is the real one.
- `detail_1032417356.json`: Vinohrady, 2+kk, 40 m2. Elevator and furnished both stated.
- `detail_270794828.json`: Nusle, 2+1, 75 m2. Elevator and furnished are placeholders (not entered).
- `detail_552337484.json`: Nové Město, 2+kk, 74 m2. The text describes a commercial office in the flat category.

Scrubbing: the `user` and `premise` objects are replaced by placeholders (`Example Agent`, `Example Agency`, no email, no phone, no IČO). Emails and phones in free text would become `<email>` and `<phone>`; none occurred. Keys that `normalize` does not use are removed, and each listing keeps at most 4 image URLs.

Guard: no `@` and no phone-like digit runs in any string value.
