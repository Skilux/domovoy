"""Generate the synthetic WSDP LV 1.0 fixtures in this folder.

Every name, number and address here is invented. The structure follows the
WSDP "Výpis z katastru nemovitostí" XML, version 1.0 (VypisZKatastruNemovitosti.xsd
from the ČÚZK WSDP 3.1 package), which is also the structure of the old LV files
kept outside the repo. No real LV content was used.

Run: python3 skill/domovoy/tests/fixtures/katastr/generate.py
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent

KU = {"kod": "999901", "nazev": "Fiktivní Ves"}
OBEC = {"kod": "999911", "nazev": "Fiktivní Město"}


def el(tag: str, text: str | None = None, attrs: dict | None = None, children: list[str] | None = None) -> str:
    a = "".join(f' {k}="{escape(v)}"' for k, v in (attrs or {}).items())
    if children:
        return f"<{tag}{a}>" + "".join(children) + f"</{tag}>"
    if text is None or text == "":
        return f"<{tag}{a}/>"
    return f"<{tag}{a}>{escape(text)}</{tag}>"


def kv(**fields: str | None) -> list[str]:
    return [el(k, v) for k, v in fields.items() if v is not None]


# ---------------------------------------------------------------- owners

def person(os_id: str, prijmeni: str, jmeno: str, titul_pred: str = "", titul_za: str = "") -> dict:
    return {"kind": "OFO", "id": os_id, "prijmeni": prijmeni, "jmeno": jmeno, "titul_pred": titul_pred, "titul_za": titul_za}


def spouses(os_id: str, a: tuple[str, str, str], b: tuple[str, str, str]) -> dict:
    return {"kind": "BSM", "id": os_id, "a": a, "b": b}


def company(os_id: str, nazev: str, ico: str) -> dict:
    return {"kind": "OPO", "id": os_id, "nazev": nazev, "ico": ico}


ADRESA = el("adresa", children=kv(nazev_ulice="Smyšlená", cp_ce="1", cislo_domovni="1", cislo_orientacni="1",
                                  cast_obce=OBEC["nazev"], obec=OBEC["nazev"], psc="99901", stat="Česká republika"))


def subjekt(o: dict, citatel: str = "1", jmenovatel: str = "1") -> str:
    if o["kind"] == "OFO":
        name = kv(prijmeni=o["prijmeni"], jmeno=o["jmeno"], titul_pred=o["titul_pred"] or None, titul_za=o["titul_za"] or None)
        ident = el("oprav_subjekt", children=kv(id=o["id"]) + name + [ADRESA])
        nazev = el("OPSUB_NAZEV", children=kv(id=o["id"]) + name)
        char = ("1", "OFO", "")
        opsub_ident = el("OPSUB_IDENT", children=kv(id=o["id"], rc6="000000", rc7="0000"))
    elif o["kind"] == "BSM":
        (p1, j1, t1), (p2, j2, t2) = o["a"], o["b"]
        bsm = kv(bsm1_prijmeni=p1, bsm1_jmeno=j1, bsm1_pred=t1 or None,
                 bsm2_prijmeni=p2, bsm2_jmeno=j2, bsm2_pred=t2 or None)
        ids = kv(id=o["id"], bsm1_id=o["id"] + "1", bsm2_id=o["id"] + "2")
        ident = el("oprav_subjekt", children=ids + bsm + [ADRESA])
        nazev = el("OPSUB_NAZEV", children=ids + bsm)
        char = ("3", "SJM", "SJM")
        opsub_ident = el("OPSUB_IDENT", children=kv(id=o["id"]))
    else:
        ident = el("oprav_subjekt", children=kv(id=o["id"], nazev=o["nazev"]) + [ADRESA])
        nazev = el("OPSUB_NAZEV", children=kv(id=o["id"], nazev=o["nazev"]))
        char = ("2", "OPO", "")
        opsub_ident = el("OPSUB_IDENT", children=kv(id=o["id"], ico=o["ico"]))
    zkratka = el("OPSUB_ZKRATKA", children=[el("char_os", children=kv(kod=char[0], zkratka=char[1], zkratka_alv=char[2]))])
    return el("SUBJEKT", children=[
        el("VLA_IDENT", children=[ident]),
        el("OPSUB_TYP", o["kind"]),
        zkratka,
        nazev,
        opsub_ident,
        el("PODIL", children=kv(citatel=citatel, jmenovatel=jmenovatel)),
    ])


def vlastnici(owners: list[tuple[dict, str, str]]) -> str:
    return el("VLASTNICI_JINI_OPRAVNENI", children=[el("TYP_VZTAHU", children=[
        el("TYP_VZTAHU", "Vlastnické právo"),
        el("SUBJEKTY", children=[subjekt(o, c, j) for o, c, j in owners]),
    ])])


# ---------------------------------------------------------------- real estate

def jednotka_ident(jed_id: str, cp: str, cislo: str) -> str:
    return el("jednotka", children=kv(id=jed_id, caobce=OBEC["nazev"], cp_ident=f"č.p. {cp}", jed_ident=f"{cp}/{cislo}"))


def stavba(st_id: str, cp: str, with_use: bool = True) -> str:
    return el("stavba", children=kv(id=st_id, caobce=OBEC["nazev"], typbud_zkr="č.p.", cisla_domovni=cp,
                                    vyuziti_zkr="byt.dům" if with_use else None))


def parcela(par_id: str, cislo: str) -> str:
    return el("parcela", children=kv(id=par_id, zkratka="St.", druh_cis="2", par_cis=cislo))


def jednotka(u: dict) -> str:
    return el("JEDNOTKA", children=[
        el("PLOMBA_JEDNOTKY", u.get("plomba", "")),
        el("CISLO_JEDNOTKY", children=[jednotka_ident(u["id"], u["cp"], u["cislo"])]),
        el("ZP_VYUZITI", u.get("vyuziti", "byt"), {"kod": u.get("vyuziti_kod", "1")}),
        el("ZP_OCHRANY"),
        el("TYP_JEDNOTKY", u.get("typ", "byt.z."), {"kod": u.get("typ_kod", "4")}),
        el("PODIL_B", children=kv(citatel=u.get("podil", "6543"), jmenovatel="100000")),
        el("POPIS", ""),
        el("BUDOVY", children=[el("BUDOVA", children=[
            el("JED_OPSUB", children=[stavba(u["building_id"], u["cp"])]),
            el("PARCELY", children=[el("PAR_IDENT", children=[parcela(u["parcel_id"], u["parcel"])])]),
        ])]),
        el("PRAVA_STAVBY"),
        el("PARCELY"),
    ])


def budova_with_units(b: dict) -> str:
    """Section B building row whose unit list is nested under it (house-owner LV).

    Each nested unit points to its own LV (NA_LV) and lists that unit's owners
    (VLASTNICTVI). Those are owners of other LVs, not of this one.
    """
    units = []
    for u in b["units"]:
        o = u["owner"]
        name = kv(prijmeni=o["prijmeni"], jmeno=o["jmeno"])
        units.append(el("JEDNOTKA", children=[
            el("JED_ZP_VYUZITI", "byt"),
            el("CISLO_JEDNOTKY", children=[jednotka_ident(u["id"], b["cp"], u["cislo"])]),
            el("TYP_JEDNOTKY", "byt.z."),
            el("PODIL_BA", children=kv(citatel=u["podil"], jmenovatel="10000")),
            el("POPIS", ""),
            el("TEL_ID", "9" + u["na_lv"]),
            el("NA_LV", u["na_lv"]),
            el("VLASTNICTVI", children=[
                el("VLA_IDENT", children=[el("oprav_subjekt", children=kv(id=o["id"]) + name)]),
                el("OPSUB_NAZEV", children=kv(id=o["id"]) + name),
                el("PODIL", children=kv(citatel="1", jmenovatel="1")),
            ]),
        ]))
    return el("BUDOVA", children=[
        el("ID", b["id"]),
        el("PLOMBA_BUDOVY"),
        el("KOD", ""),
        el("CISLO_DOMOVNI", children=[stavba(b["id"], b["cp"], with_use=False)]),
        el("ZP_VYUZITI", "bytový dům"),
        el("ZP_OCHRANY"),
        el("PARCELY", children=[el("PAR_IDENT", children=[parcela(b["parcel_id"], b["parcel"])])]),
        el("JEDNOTKY", children=units),
    ])


# ---------------------------------------------------------------- other rights (B1 / C / D)

def rizeni(typ: str, cislo: str, rok: str) -> str:
    return el("IDENT_RIZENI", children=kv(typriz_kod=typ, poradove_cislo=cislo, rok=rok, prares_kod="999"))


def jpv(hjpv_id: str, typ: str, popis: str, pro_os: dict | None, unit: dict, listina: str) -> str:
    pro = []
    if pro_os is not None:
        pro = [el("JPV_PRO_OS", children=[
            el("PRO_IDENT_OS", children=[el("oprav_subjekt", children=kv(id=pro_os["id"], ico=pro_os.get("ico"), nazev=pro_os.get("nazev")))]),
            el("PODIL_POHLEDAVKA", ""),
        ])]
    return el("JPV", children=[
        el("HJPV_ID", hjpv_id),
        el("TYP_PRAVNIHO_VZTAHU", typ),
        el("JPV_POPISY", children=[el("JPV_POPIS", children=[el("POPIS_PRAVNIHO_VZTAHU", popis)])]),
        el("JPV_OPRAV_PRO_OS", children=pro),
        el("JPV_POVIN_K_OS"),
        el("JPV_POVIN_K_NEM", children=[el("JPV_K_NEM", children=[
            el("K_IDENT_NEM", children=[jednotka_ident(unit["id"], unit["cp"], unit["cislo"])]),
        ])]),
        el("JPV_LISTINY", children=[el("JPV_LISTINA", children=[
            el("NAZEV_LIST", children=kv(tlist=listina, dalsi_udaje="", por_cis_zhot="", popis="", vystav_txt="",
                                         prav_moc_txt="", podani_txt="", vykonatelnost_txt="", podani_z_txt="", zplatneni_txt="")),
            rizeni("V", hjpv_id[-5:], "2020"),
            el("LISTIN_ID", hjpv_id + "9"),
            el("POPIS_LIST", ""),
        ])]),
    ])


def jina_prava(b1: list[str], c: list[str], d: list[str]) -> str:
    return el("JINA_PRAVA", children=[
        el("SEKCE_LIST", attrs={"SEKCE": s}, children=[el("JPV_LIST", children=items)])
        for s, items in (("B1", b1), ("C", c), ("D", d))
    ])


# ---------------------------------------------------------------- whole LV

def lv(cislo: str, owners, units: list[dict], b1=(), c=(), d=(), plomby: list[tuple[str, str, str]] = (),
       budovy: list[dict] = ()) -> str:
    d1 = []
    for typ, num, rok in plomby:
        d1 += [el("NAZEV", "Plomby a upozornění"), el("SEZNAM_RIZENI", children=[
            el("DATUM_PODANI", f"01.10.{rok}"), rizeni(typ, num, rok),
            el("NEMOVITOSTI", children=[el("NEMOVITOST", children=[jednotka_ident(u["id"], u["cp"], u["cislo"]) for u in units])]),
        ])]
    texty = el("TEXTY", children=[
        el("ZAHLAVI_LV", children=[
            el("OKRES", children=kv(nazev="Fiktivní okres")),
            el("OBEC", children=kv(**OBEC)),
            el("KATASTR_UZEMI", children=kv(**KU)),
            el("CIS_RADA", ""),
            el("TEL_ID", "9" + cislo),
            el("CISLO_LV", cislo),
        ]),
        vlastnici(owners),
        el("POZEMKY"),
        el("STAVBY", children=[budova_with_units(b) for b in budovy]),
        el("E_NABYVACI_TITULY"),
        el("JEDNOTKY", children=[jednotka(u) for u in units]),
        el("F_BONITY"),
        el("D1_UPOZORNENI", children=d1),
        el("ZMENY_PV", children=[el("ZMENA_PV", children=[el("PLOMBA", children=kv(typriz_kod=t, poradove_cislo=n, rok=r, prares_kod="999"))]) for t, n, r in plomby]),
        el("PARCELY_ZE"),
        el("UKONY_KN"),
        jina_prava(list(b1), list(c), list(d)),
        el("UPOZORNENI1", ""),
        el("UPOZORNENI2", ""),
        el("CASTECNY", ""),
    ])
    root = el("VypisZKatastruNemovitosti", children=[
        el("LIST_TEXT", children=[texty]),
        el("LIST_ZAPATI_LV", children=[el("ZAPATI_LV", children=kv(KODKP="999", KP="Katastrální pracoviště Fiktivní"))]),
        el("PLATNOST", "Platnost ke dni: 01.11.2026 00:00"),
        el("BEZPL_PRISTUP", ""),
        el("VYHOTOVENO", "Vyhotoveno: 02.11.2026 10:00:00"),
    ])
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!-- SYNTHETIC FIXTURE: every name, number and address is invented. -->\n' + root + "\n"


BANK = company("900001", "Fiktivní banka, a.s.", "99999901")
UNIT = dict(id="800001", cp="101", cislo="12", building_id="700001", parcel_id="600001", parcel="1001")
FLAT_AND_CELLAR = [
    dict(UNIT, id="800011", cislo="5"),
    dict(UNIT, id="800012", cislo="105", typ="obc.z.", typ_kod="5", vyuziti="jiný nebytový prostor", vyuziti_kod="13", podil="321"),
    dict(UNIT, id="800013", cislo="205", typ="obc.z.", typ_kod="5", vyuziti="garáž", vyuziti_kod="2", podil="210"),
]

B1_COMMON = jpv("500001", "Věcné břemeno užívání", "Oprávnění pro jednotku užívat společný sklep", None, UNIT, "Smlouva o zřízení věcného břemene")
D_COMMON = jpv("500002", "Vznik práva", "Prohlášení vlastníka o rozdělení domu na jednotky", None, UNIT, "Prohlášení vlastníka")

CASES = {
    # Single flat, one person, mortgage with the usual companion entries.
    "lv_synth_mortgage.xml": lv(
        "90001", [(person("400001", "Vzorová", "Jana", titul_pred="Ing."), "1", "1")], [UNIT],
        b1=[B1_COMMON],
        c=[jpv("510001", "Zástavní právo smluvní", "pohledávka ve výši 3 000 000 Kč", BANK, UNIT, "Smlouva o zřízení zástavního práva"),
           jpv("510002", "Zákaz zcizení nebo zatížení", "", BANK, UNIT, "Smlouva o zřízení zástavního práva"),
           jpv("510003", "Věcné břemeno vedení", "vedení inženýrských sítí", None, UNIT, "Smlouva o zřízení věcného břemene"),
           jpv("510004", "Zástavní právo smluvní", "budoucí pohledávky do 500 000 Kč", BANK, UNIT, "Smlouva o zřízení zástavního práva")],
        d=[D_COMMON]),
    # Single flat, one person, only an easement in section C.
    "lv_synth_easement.xml": lv(
        "90002", [(person("400002", "Fiktivní", "Petr"), "1", "1")], [UNIT],
        b1=[B1_COMMON],
        c=[jpv("520001", "Věcné břemeno zřizování a provozování vedení", "kabelové vedení", None, UNIT, "Smlouva o zřízení věcného břemene")],
        d=[D_COMMON]),
    # Flat + cellar + garage on one LV, owned by spouses in SJM (both partner fields filled), no mortgage.
    "lv_synth_sjm.xml": lv(
        "90003", [(spouses("400003", ("Smyšlený", "Karel", "Mgr."), ("Smyšlená", "Eva", "")), "1", "1")], FLAT_AND_CELLAR,
        b1=[B1_COMMON],
        c=[jpv("530001", "Věcné břemeno chůze a jízdy", "přes pozemek domu", None, FLAT_AND_CELLAR[0], "Smlouva o zřízení věcného břemene")],
        d=[D_COMMON]),
    # Company owner, enforcement order in C and a pending proceeding (plomba) on the flat.
    "lv_synth_company_plomba.xml": lv(
        "90004", [(company("400004", "Testovací nemovitosti s.r.o.", "99999904"), "1", "1")], [dict(UNIT, plomba="V-1234/2026")],
        b1=[B1_COMMON],
        c=[jpv("540001", "Exekuční příkaz k prodeji nemovitosti", "", None, UNIT, "Exekuční příkaz"),
           jpv("540002", "Zástavní právo exekutorské", "", None, UNIT, "Exekuční příkaz")],
        d=[D_COMMON],
        plomby=[("V", "1234", "2026")]),
    # House-owner LV: the units are listed only under the building in section B (STAVBY/BUDOVA/JEDNOTKY);
    # the top-level JEDNOTKY section is empty. 12 of the 75 real files have this shape.
    "lv_synth_building_owner.xml": lv(
        "90005", [(person("400005", "Vzorový", "Tomáš"), "1", "2"), (person("400006", "Vzorová", "Lenka"), "1", "2")], [],
        budovy=[dict(id="700005", cp="105", parcel_id="600005", parcel="1005",
                     units=[dict(id="800051", cislo="1", podil="5000", na_lv="90051",
                                 owner=dict(id="400051", prijmeni="Nájemná", jmeno="Alena")),
                            dict(id="800052", cislo="2", podil="5000", na_lv="90052",
                                 owner=dict(id="400052", prijmeni="Pokusný", jmeno="Ondřej"))])]),
}


def main() -> None:
    for name, xml in CASES.items():
        (HERE / name).write_text(xml, encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
