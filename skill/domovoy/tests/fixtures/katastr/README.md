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

Parser notes the fixtures exercise:
- `LIST_TEXT` may contain several `TEXTY` blocks; 7 real files have 2–30. Read all of them, not only the first.
- The flat's own units are `TEXTY/JEDNOTKY/JEDNOTKA`. Units under `STAVBY/BUDOVA/JEDNOTKY` or `POZEMKY/PARCELA/JEDNOTKY` belong to other LVs (`NA_LV`). Their `VLASTNICTVI` lists *other* people and must never be counted as owners of this LV.
- Detect SJM from the `bsm1_*`/`bsm2_*` fields, not from the `OPSUB_TYP` text. The `OPSUB_TYP` values in the real files were not read; the fixtures assume `OFO`/`OPO`/`BSM`.
