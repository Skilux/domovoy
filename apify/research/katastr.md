# Katastr research (WP9, Phase A)

**Status: research only, no product code. API KN and the WSDP test environment were checked live. No WSDP production call was made. All four DOMOVOY credentials are missing (section 7), so no keyed API KN call was made either.** The old LV XML files arrived later in the afternoon. Section 4 confirms by structure only that they are WSDP LV 1.0.

- Date: 13 Nov 2026
- Scope: GitHub issue #57, Phase A. This note holds no personal data. Owner fields are named by element name only.
- Raw responses, WSDLs, XSDs and the WSDP 3.1 manual are kept outside the repo, in the orchestration workspace's `research-evidence/katastr/` folder. Test-environment responses there contain only ČÚZK's fictional, anonymised sample data.

## 1. API KN (`api-kn.cuzk.gov.cz`), free

**What it is.** ČÚZK's free REST API (OpenAPI spec `/swagger/v1.0/swagger.json`, v1.0). Terms page `/podminkyuzivani` (in force since 1 Jun 2024). Key points:

- **Auth:** HTTP header `ApiKey: <key>`. Without it the data endpoints return `401` (checked). An individual gets a key through the ČÚZK registration app after Identita občana login. A company gets one through its Remote Access (DP) customer account. The key must not be passed to anyone else and must never reach a client device: server-side or local script only.
- **No personal data.** The terms state: "API neposkytuje osobní údaje" (the API does not provide personal data). **No owners, no shares, no encumbrances.**
- **Price:** free. No SLA.
- **Use:** only for the purposes in § 1(2) of the Cadastral Act. Breaches can be fined up to 100,000 CZK. ČÚZK describes the API as for online access from external systems, not for extraction or bulk download ("neslouží pro vytěžování a hromadné stahování dat"). I saw that quote in a search-result summary of a ČÚZK page and did not open the page itself.
- **Rate limit:** there is a per-period call cap, and once it is reached every call is refused until the next period. The terms give no number. The live numbers come from `GET /api/v1/AplikacniSluzby/StavUctu` (`limitVolani`, `provedenoVolani`, `aktualniObdobi`, `expiraceApiKey`), and every response also carries `provedenoVolani`. A 2024 ČÚZK FOI reply on remote-access limits quotes 500 calls/day for individuals and 1,000/day for DP-account users. It is **unconfirmed** that these figures are the API KN cap. We need about 3 calls per lookup, so either cap is far above our use.
- **Health** (`/api/v1/AplikacniSluzby/Health`, no key): `200` on 13 Nov 2026. Data were current as of 13:00 that day.

**Endpoints that matter for us** (all `GET`, JSON, envelope `{data, zpravy[], aktualnostDatK, provedenoVolani}`):

| Step | Endpoint | Returns |
| --- | --- | --- |
| Address point → building | `/api/v1/Stavby/AdresniMisto/{kod}` | Building: `id`, `typStavby`, `cislaDomovni[]`, `castObce{kod}`, `lv{id,cislo,katastralniUzemi}`, `jednotky[]{id,cisloJednotky}`, `zpusobyOchrany[]`, `parcely[]`, `adresniMista[]`, **`rizeniPlomby[]`** |
| Unit by number | `/api/v1/Jednotky/Vyhledani?KodCastiObce&TypStavby(1 č.p./2 č.e.)&CisloDomovni&CisloJednotky` | Unit list. `CisloJednotky` > 9999 means an exact `DDDDJJJJ` match |
| Unit by ID | `/api/v1/Jednotky/{id}` | `cisloJednotky`, `typJednotky`, `zpusobVyuziti`, `zpusobyOchrany[]`, `podilNaSpolecnychCastechDomu`, **`lv{id,cislo,katastralniUzemi}`**, `vymezenaVeStavbe`, **`rizeniPlomby[]`** |
| Proceeding | `/api/v1/Rizeni/{id}` | `typRizeni` (V/Z/PGP/PD/ZPV), number/year/office, `datumPrijeti`, `stav`, `provedeneOperace[]` |

So API KN covers the address → building → unit → LV number chain and the pending-proceedings flag (`rizeniPlomby[]`, i.e. "plomba") at no cost. The units list in a building gives unit numbers only. **It does not give floor or door**, so the floor-and-door case still lists candidates.

**Address → RÚIAN address-point code.** API KN takes an address-point *code*, not text. ČÚZK's free, keyless ArcGIS services do the conversion (checked live with ČÚZK's own office address):
1. Geocode: `ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/Vyhledavaci_sluzba_nad_daty_RUIAN/MapServer/exts/GeocodeSOE/findAddressCandidates?SingleLine=…&f=json` returns candidates with `score`, `Type=AdresniMisto` and a point in S-JTSK (EPSG:5514).
2. Point → code: `ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer/1/query` (layer 1 `AdresniMisto`) with `geometry=x,y`, `inSR=5514`, `distance=2`, `units=esriSRUnit_Meter`, `outFields=kod,stavebniobjekt,cislodomovni,cisloorientacni,adresa`. This returns the address-point `kod` and the `stavebniobjekt` (RÚIAN building code).

Use only score-100 candidates. Below 100, report `unknown` and never guess.

## 2. WSDP 3.1 (Remote Access web services), billed

**What it is.** SOAP 1.1, WS-Security `UsernameToken` (PasswordText) in the SOAP header. Version 3.1 is current, and production 2.9 is being retired in autumn 2026. Manual and WSDL/XSD package: "Popis WSDP 3.1" ZIP on the ČÚZK WSDP page (technical description valid from May 2026). WSDP needs its **own customer account**, separate from interactive DP. Accounts are paying (`běžný`), free (`bezúplatný`, public bodies) or verifying (`ověřující`).

| | Production | Test ("WSDP na zkoušku") |
| --- | --- | --- |
| Base URL | `https://katastr.cuzk.gov.cz/ws/wsdp/3.1/{service}` | `https://wsdptrial.cuzk.gov.cz/trial/ws/wsdp/3.1/{service}` |
| WSDL | `https://katastr.cuzk.gov.cz/dokumentace/ws3_1/wsdp/{service}_v3_1.wsdl` | `https://wsdptrial.cuzk.gov.cz/trial/dokumentace/ws3_1/wsdp/{service}_v3_1.wsdl` |
| Data | Live cadastre | Prachatice office only, content deliberately altered, owners anonymised |
| Auth | Our `WSDP_USERNAME` / `WSDP_PASSWORD` | Public test accounts listed on the ČÚZK test page (one per account type) |
| Cost | Real charges | Free; the `cena` value is only simulated |

Services: `vyhledat`, `informace`, `sestavy`, `ciselnik`, `ucet`. Request namespaces are `urn:cz:gov:cuzk:iskn:types:wsdp:{service}:3.1`. The request root element is capitalised (`NajdiJednotkuRequest`): a lowercase root gets an HTML 404, because the router sees no endpoint. From Python, **call through `curl` or set up the client carefully.** Plain `urllib` received the HTML 404 page even with a correct envelope, while `curl` with the same bytes got `200`. Phase B should send the request with an `httpx`/`requests` client and test it against the test environment first.

**Calls for our chain** (all checked live on the test environment, 13 Nov 2026):

| Step | Operation | Billed? | Notes |
| --- | --- | --- | --- |
| Building | `vyhledat/najdiStavbu` (`castObceKod`, `typStavbyKod`, `cisloDomovni`) | Free | Returns `idStavby`, `lvId` |
| Units | `vyhledat/najdiJednotku` (building ident, optional `cisloJednotky`) | Free | One `Jednotka` per unit, each with `idJednotky`, `cislo` (DDDDJJJJ), `typJedKod`, `zpuVyKod`, **`lvId`** |
| Owners, cheap | `informace/dejInfoOJednotce`, `informace/dejNahledLV` | Free | **Free and verifying accounts only.** A paying test account got `kod 207 CHYBA` ("you lack the rights"); the free test account got owners and shares. `dejNahledLV` has no encumbrances. |
| Unit report | `sestavy/generujInfoOJednotkach` (`format=xml`) | **10 CZK** (item 5004, per unit) | Unit, owners and shares (`VLASTNICTVI/SUBJEKTY`), `PLOMBY`, `RIZENI`, `VAZBA_JPV` text. Does not list the C-section encumbrances. |
| LV extract | `sestavy/generujLV` (`lvId`) or `generujLVZjednodusene` (k.ú. code + LV number), `format=xml` | **100 CZK** (item 5001, per LV) | Full LV: owners (A), real estate (B), B1/C/D rights, plombs and notices, titles (E) |
| Report flow | `generuj*` → poll `seznamSestav(idSestavy)` until `stav=zpracován` → `vratSestavu` → `smazSestavu` | Free | The manual says `vratSestavu` is where the report "zaplatí (pokud nebyl ještě zaúčtován)", i.e. the charge is booked on retrieval, and the state then becomes `zaúčtován`. Reports were ready within about 6 s on the test environment. Keep ≥ 2 s between report requests. |

**Prices** (ČÚZK price list, Annex 5 of Decree 358/2013 Sb., XML outputs): 5001 LV extract **100 CZK** per LV; 5004 unit information **10 CZK** per unit; 5003 building information 10 CZK; 5006 proceeding information 10 CZK. Search, account, code-list and report-handling services are free. The test environment showed the same simulated prices: unit report `cena 10`, LV `cena 100`.

**LV XML versions.** `dejVerzeSestav` lists LV extract versions `1.0` and `3.0`. Without `verze`, the newest version (`3.0`) is returned. ČÚZK recommends always sending `verze`.
- `1.0`: no namespace, root `VypisZKatastruNemovitosti`, uppercase sections. The XSD is in the WSDP package (`xsd/sestavy/VypisZKatastruNemovitosti.xsd`).
- `3.0` ("NTŘ", the new print format): namespace `urn:cz:gov:cuzk:iskn:sestavy:VypisZKatastruNemovitosti:3.0`, root `vypisZKatastruNemovitosti`, camelCase. XSD at `katastr.cuzk.gov.cz/dokumentace/xsd/sestavy/VypisZKatastruNemovitosti_3.0.xsd` plus `types/base_3.0.xsd` and `types/common_3.0.xsd`. Download over HTTP/1.1: curl's HTTP/2 attempt failed on that host.

Both versions were fetched for the same test LV, so their element trees are in the evidence folder.

## 3. KatastrResult field sources

| `KatastrResult` field | API KN | WSDP LV 1.0 | WSDP LV 3.0 |
| --- | --- | --- | --- |
| `unit_type` | `Jednotky/{id}.typJednotky`, `zpusobVyuziti` | `JEDNOTKY/JEDNOTKA/TYP_JEDNOTKY@kod`, `ZP_VYUZITI@kod` | `nemovitosti/jednotky/jednotka/typ/kod`, `zpusobVyuziti/kod` |
| `owner_types[]` | — | `…/SUBJEKT/OPSUB_TYP`, `OPSUB_ZKRATKA/char_os` | `vlastnici/pravniVztahy/pravniVztah/seznamVlastnictvi/vlastnictvi/opravnenySubjekt/typ` (`OFO` person, `OPO` legal entity, `BSM` marital property) and `charKod` |
| `owner_count` | — | count of `SUBJEKT` under `TYP_VZTAHU` = ownership | count of `vlastnictvi` under `pravniVztah/kod = 30` (ownership) |
| shares | `Jednotka.podilNaSpolecnychCastechDomu` (common parts only) | `SUBJEKT/PODIL/{citatel,jmenovatel}` | `vlastnictvi/podil/{citatel,jmenovatel}` |
| `restrictions[]` | — | `JINA_PRAVA/SEKCE_LIST[@SEKCE=C]/JPV_LIST/JPV/TYP_PRAVNIHO_VZTAHU` (+ `D` notes) | `jinaPrava/jinePravo[sekce/zkratka=C]/pravniVztah/{kod,nazev}`, `popis` (`sekce` 1=B1, 2=C, 4=D) |
| `pending_change` | `Stavba.rizeniPlomby[]`, `Jednotka.rizeniPlomby[]` | `JEDNOTKA/PLOMBA_JEDNOTKY`, `ZMENY_PV/ZMENA_PV/PLOMBA`, `D1_UPOZORNENI/SEZNAM_RIZENI` | `…/jednotka/plomba` (`P`), `seznamUpozorneni/upozorneni/{nazev,objektyRizeni}` |
| `landlord_matches_owner` | — | names in `OPSUB_NAZEV` (`prijmeni`, `jmeno`, `titul_*`, `nazev`, `bsm1_*`, `bsm2_*`) | `opravnenySubjekt/oS` and `oS2` (`jmeno`, `prijmeni`, `titulPred`, `titulZa`, `nazev`); `nazevSJ` for BSM |
| `as_of` | `aktualnostDatK` | `PLATNOST`, `VYHOTOVENO` | `obecneUdaje/platnost`, `vyhotoveno` |
| LV ref (internal) | `lv{id,cislo,katastralniUzemi.kod}` | `ZAHLAVI_LV/CISLO_LV`, `KATASTR_UZEMI/kod` | `listVlastnictvi/{id,cislo,katastrUzemi/kod}` |

Name-matching inputs follow from this. SJM/BSM has two partner records (`bsm1_*`/`bsm2_*` in 1.0, `oS`/`oS2` in 3.0), so a landlord name matches either spouse. A company owner (`OPO`) has `nazev` only, so it is matched by company name. Titles have their own fields and are dropped.

## 4. Old LV XML → live WSDP schema

**Update, 13 Nov 2026, afternoon:** Vladimir has placed 75 old LV files in `~/.config/domovoy/lv/` (`KATASTR_LV_DIR` is now in `.env`). They are the LVs with units, out of 216 originals. They were inspected by a script that printed element and attribute names, paths and counts only. No text or attribute value was printed, and no file was copied.

- **The old files are WSDP LV 1.0.** All 75 parse. All have root `VypisZKatastruNemovitosti` with no namespace and a `ds:Signature`. **Every element and attribute path in all 75 files is declared in the v1.0 XSD** (0 unknown paths). The only XSD paths no file uses are under `NEM_BEZ_LV/NEMOVITOST`. So live `generujLV` with `verze=1.0` and `--cached-lv` can share one parser.
- **Several `TEXTY` blocks:** 68 files have one `LIST_TEXT/TEXTY`, and 7 have 2–30. The parser must read all of them.
- **Where units sit:** 63 files have units in `TEXTY/JEDNOTKY/JEDNOTKA` (the LV's own units; 9 files have exactly 1). In the other 12, top-level `JEDNOTKY` is empty and units appear only under `STAVBY/BUDOVA/JEDNOTKY` or `POZEMKY/PARCELA/JEDNOTKY`: a house or land owner's LV. Those nested units carry their own `NA_LV` and `VLASTNICTVI`, i.e. *other* LVs' owners, which must never be counted as this LV's owners.
- **Section shape:** `JINA_PRAVA` always has exactly three `SEKCE_LIST` (`@SEKCE` = B1, C, D), each with a `JPV_LIST` (XSD `minOccurs=maxOccurs=3`). C-section `JPV` counts per file range from 1 to 58. No file has a `ZMENY_PV/ZMENA_PV` or `D1_UPOZORNENI/SEZNAM_RIZENI` entry, so none of the 75 shows a pending change.
- **SJM:** 9 files carry the spouse fields (`OPSUB_NAZEV/bsm1_*`, `bsm2_*`).
- **Vladimir's demo picks, by structure:** the two mortgage cases each have 1 unit, 1 owner record and 4 C-section entries. The easement-only case has 1 unit, 1 owner record and 1 C entry. **The case labelled "SJM, no mortgage" does not look like SJM by structure:** it has 1 owner record with no `bsm1_*`/`bsm2_*` fields, and 3 units on the LV, not 1. Either the label or the file pick needs a second look by Vladimir; I did not read values to settle it. The LV numbers are kept out of the repo.
- **Synthetic fixtures** with the same structure are in `skill/domovoy/tests/fixtures/katastr/` (generator + README). All 5 validate against the v1.0 XSD, and their element paths occur in the real files, except the plomba case, which has no real example.
- **The 1.0 sections are:** `LIST_TEXT/TEXTY/{ZAHLAVI_LV, VLASTNICI_JINI_OPRAVNENI, POZEMKY, STAVBY, PRAVA_STAVBY, JEDNOTKY, JINA_PRAVA, D1_UPOZORNENI, ZMENY_PV, E_NABYVACI_TITULY, F_BONITY, UKONY_KN, PARCELY_ZE, UPOZORNENI1, UPOZORNENI2, CASTECNY}`, then `LIST_ZAPATI_LV`, `NEM_BEZ_LV`, `PLATNOST`, `BEZPL_PRISTUP`, `VYHOTOVENO`, `INFO_VYSTUP`. An unsigned test-environment 1.0 LV contained every one of these. A production LV also carries a `ds:Signature`.
- Section 3 maps both versions onto `KatastrResult`: **1.0** (root `VypisZKatastruNemovitosti`, no namespace) and **3.0** (root `{urn:cz:gov:cuzk:iskn:sestavy:VypisZKatastruNemovitosti:3.0}vypisZKatastruNemovitosti`).

## 5. Recommendation

| Step | Source | Cost |
| --- | --- | --- |
| Address text → address point + RÚIAN building | ČÚZK ArcGIS geocoder + `RUIAN/MapServer/1` query | Free, no key |
| Address point → building, LV, units, plombs | API KN `Stavby/AdresniMisto/{kod}` | Free, `ApiKey` |
| Unit by number | API KN `Jednotky/Vyhledani` then `Jednotky/{id}` (LV + `rizeniPlomby`) | Free |
| Unit by floor + door only | Not resolvable from either source (no floor/door data). List the building's units as candidates and return `unknown`. | Free |
| Fallback if API KN fails | WSDP `vyhledat/najdiStavbu`, `najdiJednotku` | Free (WSDP account needed) |
| Owners, shares, encumbrances (C), notes (D), plombs | WSDP `sestavy/generujLV` with `lvId` (or k.ú. + LV number), `format=xml`, **`verze` pinned** | **100 CZK, 1 billed output** |
| Cached path | `--cached-lv <xml>`, the same parser as the `generujLV` response | Free |

**Billed calls per live lookup: 1** (one LV extract, 100 CZK). The unit report (`generujInfoOJednotkach`, 10 CZK) is cheaper but lacks the C-section encumbrances, which `lease_risk` needs, so it is not worth an extra call. The free `dejInfoOJednotce`/`dejNahledLV` work only if Vladimir's WSDP account is the free or verifying type, which is unlikely, and they still lack encumbrances.

## 6. What Phase B needs

1. **Credentials** in `/Users/vladimir/.config/domovoy/.env`: `CUZK_API_KN_KEY`, `WSDP_USERNAME`, `WSDP_PASSWORD`, `WSDP_ENV` (`trial` | `prod`). All four are missing today. Default `WSDP_ENV=trial` so that development never bills.
2. **One parser module** for LV XML. The cached files are 1.0 (section 4), so pin `verze=1.0` on live calls and the live and cached paths go through the same code. Reject any other root with `unknown`; a 3.0 branch can come later if ČÚZK drops 1.0.
3. **Billing guard** `WSDP_MAX_BILLED_PER_DAY` (≤ 10), counted **before** `generujLV` (conservative: the manual books the charge at `vratSestavu`). The counter file goes outside the repo. Set `WSDP_ENV=prod` explicitly for the guard to apply. Always call `smazSestavu` after retrieval.
4. **`lease_risk` rule proposal**, open for Vladimir. A mortgage (`zástavní právo`) is normal and is reported but not flagged. Flagged items: a plomb or pending ownership change, execution or insolvency notes (`Nařízení exekuce`, `Exekuční příkaz`, `insolvence`), `zákaz zcizení nebo zatížení`, and co-ownership with more than 2 owner records.
5. **Fixtures:** the repo gets only hand-made synthetic XML, never a real or test-environment LV, even though test-environment data are fictional. This keeps the "names only in Notion" rule easy to check. The five 1.0 fixtures are in `skill/domovoy/tests/fixtures/katastr/`.
6. **Stdout redaction test:** a test asserting that the result text never contains an `oS`/`OPSUB_NAZEV` name value from a synthetic fixture.

## 7. Credentials and inputs, status 13 Nov 2026

| Item | Status |
| --- | --- |
| `CUZK_API_KN_KEY` | missing |
| `WSDP_USERNAME` | missing |
| `WSDP_PASSWORD` | missing |
| `WSDP_ENV` | missing |
| `KATASTR_LV_DIR` | set in `.env`; 75 LV 1.0 files (afternoon update) |

## Sources

- API KN home, terms, OpenAPI: `https://api-kn.cuzk.gov.cz/`, `/podminkyuzivani`, `/swagger/v1.0/swagger.json`
- ČÚZK FOI reply on API limits (2024): cuzk.gov.cz, "Limity a omezení dálkového přístupu k datům katastru"
- WSDP page, manual and package: cuzk.gov.cz → Katastr nemovitostí → Poskytování údajů z KN → Dálkový přístup → Webové služby (WSDP 3.1 ZIP, updated 2026)
- WSDP test environment: the same section → "Webové služby DP na zkoušku"
- Price list: the same section → "Účtování výstupů z KN poskytovaných DP a WSDP" (Annexes 4 and 5, Decree 358/2013 Sb.)
- LV 3.0 XSD: `https://katastr.cuzk.gov.cz/dokumentace/xsd/sestavy/VypisZKatastruNemovitosti_3.0.xsd`
