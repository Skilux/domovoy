# Katastr LV fixtures (synthetic)

**Every name, number and address in these files is invented.** No real LV content was copied. Regenerate with:

```
python3 skill/domovoy/tests/fixtures/katastr/generate.py
```

The files follow the WSDP "Výpis z katastru nemovitostí" XML, **version 1.0**: root `VypisZKatastruNemovitosti`, no namespace, sections under `LIST_TEXT/TEXTY`. This is the structure of the old LV files kept outside the repo (`KATASTR_LV_DIR`). It is also what live WSDP returns for `generujLV` with `verze=1.0`. See [apify/research/katastr.md](../../../../../apify/research/katastr.md), section 4.

How they were checked (13 Nov 2026):
- All 5 validate against `VypisZKatastruNemovitosti.xsd` from the ČÚZK WSDP 3.1 package (lxml).
- Element paths were compared with the paths in the 75 real files, by name only. Every path in the first four fixtures, and in `lv_synth_building_owner.xml`, occurs in the real files. `lv_synth_company_plomba.xml` also uses `D1_UPOZORNENI/SEZNAM_RIZENI` and `ZMENY_PV/ZMENA_PV/PLOMBA`. No real file has a pending proceeding, so those two are XSD-valid but have no real example.
- Real files are signed (`ds:Signature`). The fixtures are not, and a parser must accept both.

| File | Shape | Mirrors |
| --- | --- | --- |
| `lv_synth_mortgage.xml` | 1 flat, 1 person (with a title), C: mortgage ×2, ban on sale, easement; B1 and D one entry each | single-unit mortgage case |
| `lv_synth_easement.xml` | 1 flat, 1 person, C: one easement | easement-only case |
| `lv_synth_sjm.xml` | flat + 2 non-residential units, spouses in SJM (`bsm1_*`/`bsm2_*`), C: one easement | SJM case without mortgage |
| `lv_synth_company_plomba.xml` | 1 flat, company owner, C: enforcement order + enforcement lien, plomb on the unit, `ZMENY_PV` and `D1_UPOZORNENI` entries | risk case (no real example) |
| `lv_synth_building_owner.xml` | top-level `JEDNOTKY` empty; 2 units nested under `STAVBY/BUDOVA/JEDNOTKY`, each with its own `NA_LV` and `VLASTNICTVI` | the 12 real files of this shape |
| `lv_synth_attic_company.xml` | company owns 3 flats + 1 shop on one LV; two mortgages, each with a ban on sale, on different unit pairs; B1 and D hold only the empty `JPV` the XSD requires; units name their building LV (`stavba/cislo_tel`) | a live LV 1.0 export of 13 Nov 2026, by shape only |
| `lv_synth_easements.xml` | 1 flat with three easements: a right to live in it for a person, a right of way through it for a property (`JPV_OPRAV_PRO_NEM`), a utility line on a parcel; B1 and D empty | the easement kinds `katastr.py` grades for a tenant |

The last two files were added later and were **not** validated against the XSD (the XSD is outside the repo). Their new paths (`stavba/cislo_tel`, `JPV_OPRAV_PRO_NEM/JPV_PRO_NEM`, the empty `JPV`) occur in a live LV 1.0 export; `K_IDENT_NEM/parcela` was not seen in one.

Parser notes the fixtures exercise:
- `LIST_TEXT` may contain several `TEXTY` blocks; 7 real files have 2–30. Read all of them, not only the first.
- The flat's own units are `TEXTY/JEDNOTKY/JEDNOTKA`. Units under `STAVBY/BUDOVA/JEDNOTKY` or `POZEMKY/PARCELA/JEDNOTKY` belong to other LVs (`NA_LV`). Their `VLASTNICTVI` lists *other* people and must never be counted as owners of this LV.
- A section with no entries still carries one `JPV` with empty children. It is not an entry.
- Real files keep the building number in `cp_ident` and only the unit number in `jed_ident` (`1200` + `65`); the older fixtures put both in `jed_ident`. `jednotka_label()` reads both shapes.
- Detect SJM from the `bsm1_*`/`bsm2_*` fields, not from the `OPSUB_TYP` text. The `OPSUB_TYP` values in the real files were not read; the fixtures assume `OFO`/`OPO`/`BSM`.
