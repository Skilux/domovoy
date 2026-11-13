#!/usr/bin/env python3
"""DOMOVOY katastr check: who owns a flat, what encumbers it, and whether that is a lease risk.

  katastr.py lookup --page ID [--cached-lv FILE] [--unit N] [--floor F --door D] [--landlord NAME]
      Reads the flat's address and the call answers (unit number, floor and door, landlord name) from the
      shortlist page, resolves the unit and its LV (list of ownership), and appends a "Katastr check" section
      to the page. Flags override what the page says. With --cached-lv the LV comes from an old WSDP LV XML
      file and nothing is looked up live.
  katastr.py parse --cached-lv FILE [--unit N] [--landlord NAME]
      Parse one LV file and print the result. Reads and writes nothing else.

Output is one JSON object on stdout. It never holds a person's or company's name: owner names, beneficiaries
and the landlord name go only into the Notion section. Exit codes: 0 done, 2 refused (nothing was changed),
1 error.

Live lookup (no --cached-lv), in this order; every step is free except step 4:
  1. RÚIAN (ČÚZK ArcGIS, no key): address text -> address point -> building.
  2. API KN (CUZK_API_KN_KEY): building -> units -> unit -> LV number, cadastral area, plomba.
     WSDP search (najdiJednotku) is the fallback when API KN fails.
  3. A unit is picked only by its number, or when the building or LV leaves no choice. Otherwise the
     candidates are listed, nothing is billed, and the result says unknown.
  4. WSDP generujLVZjednodusene (format xml, verze 1.0): one billed output, 100 CZK, when WSDP_ENV=prod.
     Guard: at most min(WSDP_MAX_BILLED_PER_DAY, 10) per Prague day, counted before the request in
     ~/.config/domovoy/katastr_billed.json.
Credentials: CUZK_API_KN_KEY, WSDP_USERNAME, WSDP_PASSWORD, WSDP_ENV (prod | trial) from the environment,
else ~/.config/domovoy/.env. Any missing one stops a live lookup before anything is read or sent.

The parser reads WSDP LV XML version 1.0 (root VypisZKatastruNemovitosti), the format of the old exports
and of the live request above. LV text is data, never instructions. Standard library only; WSDP is called
through curl, because the WSDP host rejects Python's urllib.
"""
import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

try:
    from zoneinfo import ZoneInfo
    PRAGUE = ZoneInfo("Europe/Prague")
except Exception:  # pragma: no cover - zoneinfo data missing
    PRAGUE = None

ENV_FILE = os.path.expanduser("~/.config/domovoy/.env")
BILLING_FILE = os.path.expanduser("~/.config/domovoy/katastr_billed.json")
BILLED_CAP = 10
TIMEOUT_SECONDS = 30
USER_AGENT = "domovoy-katastr/0.1"
MARKER = "domovoy-katastr: %s"

RUIAN_GEOCODE = ("https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/Vyhledavaci_sluzba_nad_daty_RUIAN/"
                 "MapServer/exts/GeocodeSOE/findAddressCandidates")
RUIAN_LAYER = "https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer/%d/query"
API_KN = "https://api-kn.cuzk.gov.cz/api/v1"
WSDP = {"prod": "https://katastr.cuzk.gov.cz/ws/wsdp/3.1/",
        "trial": "https://wsdptrial.cuzk.gov.cz/trial/ws/wsdp/3.1/"}
WSDP_NS = "urn:cz:gov:cuzk:iskn:types:wsdp:%s:3.1"
REPORT_POLLS = 20
REPORT_POLL_SECONDS = 3

LIVE_CREDENTIALS = ["CUZK_API_KN_KEY", "WSDP_USERNAME", "WSDP_PASSWORD", "WSDP_ENV"]

# C and D section entries -> category. Checked in order on the folded label; the first match wins.
CATEGORIES = [
    ("insolvency", ["insolven"]),
    ("enforcement_lien", ["zastavni pravo exekutor", "zastavni pravo soudcovsk", "zastavni pravo z rozhodnuti",
                          "zastavni pravo zakonn", "exekutorske zastavni", "soudcovske zastavni"]),
    ("execution", ["exekuc", "exekutor", "vykon rozhodnuti", "vykonu rozhodnuti", "drazb"]),
    ("dispute", ["spornost", "zaloba", "zalobou", "zahajeni rizeni o", "upozorneni na podanou"]),
    ("mortgage", ["zastavni pravo", "podzastavni"]),
    ("ban_on_sale", ["zakaz zcizeni", "zakaz zatizeni"]),
    ("pre_emption", ["predkupni"]),
    ("easement", ["vecne bremeno", "sluzebnost", "bremeno"]),
    ("lease", ["najem", "pacht"]),
]
HIGH_RISK = {"insolvency": "insolvency entry", "enforcement_lien": "lien from an enforcement or court decision",
             "execution": "enforcement (exekuce) entry", "dispute": "dispute or lawsuit note"}
MEDIUM_RISK = {"ban_on_sale": "ban on sale or encumbrance"}

TITLES = {"ing", "mgr", "bc", "mudr", "judr", "phdr", "rndr", "paeddr", "mvdr", "mddr", "pharmdr", "thdr",
          "doc", "prof", "phd", "csc", "drsc", "dis", "mba", "llm", "dr", "arch", "akad", "mga", "bca", "msc",
          "ba", "ma", "dipl", "th", "ing.arch"}
STOPWORDS = {"the", "a", "an", "is", "are", "was", "of", "and", "owner", "owners", "landlord", "landlords", "name",
             "named", "called", "his", "her", "their", "mr", "mrs", "ms", "miss", "it", "its", "by", "pan", "pani",
             "slecna", "majitel", "majitelka", "pronajimatel", "pronajimatelka", "jmenuje", "se", "je", "to",
             "says", "said", "i", "think", "flat", "belongs", "to", "from", "company", "firma"}
LEGAL_FORMS = {"s", "r", "o", "sro", "a", "as", "spol", "k", "v", "z", "se", "ltd", "gmbh", "inc", "llc",
               "ks", "vos", "zs", "ops", "zu", "druzstvo"}
COMPANY_HINTS = re.compile(r"s\.\s?r\.\s?o|a\.\s?s\.|spol\.|druzstv|\bltd\b|gmbh|\binc\b|\bsro\b", re.IGNORECASE)
COOP = ("druzstvo", "druzstevni")


class Refusal(Exception):
    pass


class LVFormatError(RuntimeError):
    pass


# ------------------------------------------------------------------ settings

def env_values():
    values = {}
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                if line.lstrip().startswith("#"):
                    continue
                key, sep, value = line.strip().partition("=")
                key = key.strip()
                if key.startswith("export "):
                    key = key[len("export "):].strip()
                if sep and key:
                    values[key] = value.strip().strip("'\"")
    return values


def settings(names):
    file_values = env_values()
    return {name: os.environ.get(name) or file_values.get(name) or "" for name in names}


def require_live_credentials():
    values = settings(LIVE_CREDENTIALS + ["WSDP_MAX_BILLED_PER_DAY"])
    missing = [name for name in LIVE_CREDENTIALS if not values[name]]
    if missing:
        raise Refusal("missing credentials: %s. Set them in %s. Nothing was read or changed."
                      % (", ".join(missing), ENV_FILE))
    if values["WSDP_ENV"] not in WSDP:
        raise Refusal("WSDP_ENV must be prod or trial. Nothing was read or changed.")
    return values


# ------------------------------------------------------------------ text helpers

def fold(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def words(text):
    return re.findall(r"[a-z0-9]+", fold(text))


def name_tokens(text):
    return [w for w in words(text) if w not in TITLES and w not in STOPWORDS and not w.isdigit()]


def txt(node, path):
    found = node.find(path) if node is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


def joined(node, path):
    return " ".join(t for t in ((e.text or "").strip() for e in node.findall(path)) if t)


def now_iso():
    now = datetime.datetime.now(PRAGUE) if PRAGUE else datetime.datetime.now().astimezone()
    return now.replace(microsecond=0).isoformat()


def prague_iso(text):
    m = re.search(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})(?:\D+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", text or "")
    if not m:
        return None
    day, month, year, hour, minute, second = m.groups()
    value = datetime.datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0))
    value = value.replace(tzinfo=PRAGUE) if PRAGUE else value.astimezone()
    return value.isoformat()


# ------------------------------------------------------------------ LV 1.0 parser

def subject_of(node):
    """One owner or beneficiary record: names stay inside this dict, which is never printed."""
    if node is None:
        return None
    nazev = txt(node, "nazev")
    spouses = [(txt(node, "bsm%d_prijmeni" % i), txt(node, "bsm%d_jmeno" % i)) for i in (1, 2)]
    spouses = [s for s in spouses if s[0]]
    if spouses:
        return {"kind": "sjm", "persons": spouses, "company": None}
    if txt(node, "prijmeni"):
        return {"kind": "person", "persons": [(txt(node, "prijmeni"), txt(node, "jmeno"))], "company": None,
                "titles": " ".join(t for t in (txt(node, "titul_pred"), txt(node, "titul_za")) if t)}
    if nazev:
        kind = "cooperative" if any(c in fold(nazev) for c in COOP) else "company"
        return {"kind": kind, "persons": [], "company": nazev}
    return {"kind": "unknown", "persons": [], "company": None}


def display_name(subject):
    if subject is None:
        return "unknown"
    if subject["company"]:
        return subject["company"]
    people = ["%s %s" % (jmeno, prijmeni) if jmeno else prijmeni for prijmeni, jmeno in subject["persons"]]
    name = " and ".join(people) or "unknown"
    return "%s %s" % (subject["titles"], name) if subject.get("titles") else name


def category_of(label):
    folded = " ".join(words(label))
    for category, needles in CATEGORIES:
        if any(n in folded for n in needles):
            return category
    return "other"


def unit_number(jed_ident):
    """('101/12' style) -> (building number, unit number) as strings, or (None, digits)."""
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*$", jed_ident or "")
    if m:
        return m.group(1), m.group(2).lstrip("0") or "0"
    digits = re.findall(r"\d+", jed_ident or "")
    return None, (digits[-1].lstrip("0") or "0") if digits else None


def usage_kind(zp_vyuziti):
    folded = fold(zp_vyuziti)
    if folded.startswith("byt") or folded == "byt":
        return "flat"
    if "garaz" in folded:
        return "garage"
    if "atelier" in folded:
        return "studio"
    return "non_residential" if folded else None


def regime_of(typ):
    folded = fold(typ).replace(" ", "")
    if folded.startswith("byt"):
        return "apartment_act_72_1994"
    if folded.startswith("obc"):
        return "civil_code"
    return None


def parse_lv(source):
    """Parse WSDP LV 1.0 XML (a file path, or the bytes of a live report).

    Returns the full parse, names included: it must never be printed or stored outside Notion.
    """
    try:
        root = ET.fromstring(source) if isinstance(source, bytes) else ET.parse(source).getroot()
    except ET.ParseError as e:
        raise LVFormatError("the LV file is not well-formed XML: %s" % e)
    if root.tag != "VypisZKatastruNemovitosti":
        raise LVFormatError("not a WSDP LV 1.0 file (root element %s)" % root.tag.split("}")[-1])
    texty = root.findall("LIST_TEXT/TEXTY")
    header = next((t.find("ZAHLAVI_LV") for t in texty if t.find("ZAHLAVI_LV") is not None), None)
    lv = {"number": txt(header, "CISLO_LV"), "area_code": txt(header, "KATASTR_UZEMI/kod"),
          "area_name": txt(header, "KATASTR_UZEMI/nazev")}

    owners = []
    for t in texty:
        for rel in t.findall("VLASTNICI_JINI_OPRAVNENI/TYP_VZTAHU"):
            relation = txt(rel, "TYP_VZTAHU")
            for s in rel.findall("SUBJEKTY/SUBJEKT"):
                node = s.find("OPSUB_NAZEV")
                if node is None or not any((e.text or "").strip() for e in node):
                    node = s.find("VLA_IDENT/oprav_subjekt")
                subject = subject_of(node)
                share = "1/1"
                if txt(s, "PODIL/citatel"):
                    share = "%s/%s" % (txt(s, "PODIL/citatel"), txt(s, "PODIL/jmenovatel"))
                owners.append(dict(subject, relation=relation, share=share,
                                   ownership="vlastnick" in fold(relation)))

    units = []
    for t in texty:
        for j in t.findall("JEDNOTKY/JEDNOTKA"):
            ident = txt(j, "CISLO_JEDNOTKY/jednotka/jed_ident")
            building, number = unit_number(ident)
            usage = txt(j, "ZP_VYUZITI")
            units.append({"id": txt(j, "CISLO_JEDNOTKY/jednotka/id"), "label": ident, "building": building,
                          "number": number, "usage": usage, "usage_kind": usage_kind(usage),
                          "regime": regime_of(txt(j, "TYP_JEDNOTKY")), "plomba": txt(j, "PLOMBA_JEDNOTKY")})

    rights = []
    for t in texty:
        for section in t.findall("JINA_PRAVA/SEKCE_LIST"):
            for jpv in section.findall("JPV_LIST/JPV"):
                label = txt(jpv, "TYP_PRAVNIHO_VZTAHU")
                beneficiaries = [subject_of(n) for n in
                                 jpv.findall("JPV_OPRAV_PRO_OS/JPV_PRO_OS/PRO_IDENT_OS/oprav_subjekt")]
                rights.append({
                    "section": section.get("SEKCE"),
                    "label": label,
                    "category": category_of(label),
                    "description": joined(jpv, "JPV_POPISY/JPV_POPIS/POPIS_PRAVNIHO_VZTAHU"),
                    "beneficiaries": [b for b in beneficiaries if b and b["kind"] != "unknown"],
                    "units": [txt(n, "jednotka/jed_ident") for n in jpv.findall("JPV_POVIN_K_NEM/JPV_K_NEM/K_IDENT_NEM")
                              if txt(n, "jednotka/jed_ident")],
                })

    proceedings = []
    for t in texty:
        for p in t.findall("ZMENY_PV/ZMENA_PV/PLOMBA") + t.findall("D1_UPOZORNENI/SEZNAM_RIZENI/IDENT_RIZENI"):
            if txt(p, "typriz_kod"):
                proceedings.append("%s-%s/%s-%s" % (txt(p, "typriz_kod"), txt(p, "poradove_cislo"),
                                                    txt(p, "rok"), txt(p, "prares_kod")))
    return {"lv": lv, "owners": owners, "units": units, "rights": rights,
            "proceedings": sorted(set(proceedings)), "as_of": prague_iso(txt(root, "PLATNOST")),
            "signed": any(c.tag.endswith("}Signature") for c in root)}


# ------------------------------------------------------------------ matching and risk

def match_person(landlord, prijmeni, jmeno):
    surname = name_tokens(prijmeni)
    if not surname:
        return "unknown"
    if not all(t in landlord for t in surname):
        return "no"
    rest = [t for t in landlord if t not in surname]
    first = name_tokens(jmeno)
    if not rest or not first:
        return "unknown"
    return "yes" if any(t[0] == first[0][0] for t in rest) else "no"


def match_owner(landlord_text, owner):
    landlord = name_tokens(landlord_text)
    if not landlord:
        return "unknown"
    if owner["kind"] in ("person", "sjm"):
        if COMPANY_HINTS.search(landlord_text or ""):
            return "no"
        votes = [match_person(landlord, p, j) for p, j in owner["persons"]]
        return "yes" if "yes" in votes else ("unknown" if "unknown" in votes else "no")
    if owner["kind"] in ("company", "cooperative"):
        core = [w for w in words(owner["company"]) if w not in LEGAL_FORMS]
        if core and all(w in words(landlord_text) for w in core):
            return "yes"
        return "no" if COMPANY_HINTS.search(landlord_text or "") else "unknown"
    return "unknown"


def landlord_matches(landlord_text, owners):
    if not landlord_text or not owners:
        return "unknown"
    votes = [match_owner(landlord_text, o) for o in owners]
    return "yes" if "yes" in votes else ("unknown" if "unknown" in votes else "no")


def pick_unit(units, number=None, floor=None, door=None):
    """(unit, candidates, note). Never guesses: ambiguity returns no unit and the candidate list."""
    candidates = [u["label"] or u["number"] for u in units]
    if number:
        want = str(number).strip()
        n = (want.split("/")[-1].lstrip("0") or "0") if re.search(r"\d", want) else None
        hits = [u for u in units if u["label"] == want or (n and u["number"] == n)]
        if len(hits) == 1:
            return hits[0], [], None
        if not hits:
            return None, candidates, "unit %s is not on this LV" % want
        return None, candidates, "unit number %s matches several units" % want
    if len(units) == 1:
        return units[0], [], None
    flats = [u for u in units if u["usage_kind"] == "flat"]
    if len(flats) == 1:
        return flats[0], [], "the only flat on the LV; the other units are not flats"
    if not units:
        return None, [], "the LV lists no unit of its own"
    note = "floor and door are not in the land register" if floor or door else "no unit number from the call"
    return None, candidates, note + "; the unit was not identified"


def assess(parsed, landlord=None, number=None, floor=None, door=None, extra_plomba=()):
    owners = [o for o in parsed["owners"] if o["ownership"]] or parsed["owners"]
    unit, candidates, unit_note = pick_unit(parsed["units"], number, floor, door)
    relevant = [r for r in parsed["rights"] if r["section"] in ("C", "D")]
    if unit and unit["label"]:
        relevant = [r for r in relevant if not r["units"] or unit["label"] in r["units"]]
    pending = bool(parsed["proceedings"] or any(u["plomba"] for u in ([unit] if unit else parsed["units"]))
                   or extra_plomba)
    match = landlord_matches(landlord, owners)
    kinds = sorted({o["kind"] for o in owners})

    high, medium = [], []
    for r in relevant:
        if r["category"] in HIGH_RISK:
            high.append("%s in section %s" % (HIGH_RISK[r["category"]], r["section"]))
        elif r["category"] in MEDIUM_RISK:
            medium.append("%s in section %s" % (MEDIUM_RISK[r["category"]], r["section"]))
    if pending:
        high.append("a change is pending in the land register (plomba)")
    if match == "no":
        high.append("the landlord named in the call is not an owner on the LV: this would be a sublease")
    if "cooperative" in kinds:
        medium.append("a housing co-op owns the flat: renting is a sublease from a member "
                      "and needs the co-op's consent")
    if "company" in kinds:
        medium.append("a company owns the flat: check who may sign for it, or that a sublease is allowed")
    if len(owners) > 2:
        medium.append("%d co-owners: the lease needs the agreement of the majority by shares" % len(owners))
    if not owners:
        medium.append("no owner found on the LV")
    if match == "unknown":
        medium.append("the landlord could not be matched to an owner")
    if unit is None and parsed["units"]:
        medium.append("the unit was not identified on the LV")
    level = "high" if high else ("medium" if medium else "low")

    result = {
        "unit_type": unit["usage_kind"] if unit else None,
        "unit_regime": unit["regime"] if unit else None,
        "unit_number": unit["label"] if unit else None,
        "unit_candidates": candidates,
        "unit_note": unit_note,
        "owner_types": kinds,
        "owner_count": len(owners),
        "owner_shares": [o["share"] for o in owners],
        "restrictions": [{"section": r["section"], "type": r["category"], "label": r["label"]} for r in relevant],
        "pending_change": pending,
        "pending_proceedings": list(parsed["proceedings"]) + list(extra_plomba),
        "landlord_matches_owner": match,
        "lease_risk": level,
        "risk_reasons": high + medium,
        "as_of": parsed["as_of"],
    }
    return result, owners, unit


# ------------------------------------------------------------------ Notion section and redaction

def notion_section(result, parsed, owners, source_line):
    rel = [r for r in parsed["rights"] if {"section": r["section"], "type": r["category"], "label": r["label"]}
           in result["restrictions"]]
    lines = ["Katastr check", source_line,
             "LV %s, cadastral area %s (%s). Data as of %s."
             % (parsed["lv"]["number"] or "unknown", parsed["lv"]["area_name"] or "unknown",
                parsed["lv"]["area_code"] or "?", result["as_of"] or "unknown")]
    if result["unit_number"]:
        lines.append("Unit: %s, %s, %s." % (result["unit_number"], result["unit_type"] or "unknown use",
                                           result["unit_regime"] or "unknown regime"))
    else:
        lines.append("Unit: not identified (%s). Candidates: %s."
                     % (result["unit_note"] or "unknown", ", ".join(result["unit_candidates"]) or "none"))
    lines.append("Owners (%d):" % len(owners))
    for o in owners:
        lines.append("- %s, %s, share %s" % (display_name(o), o["kind"], o["share"]))
    for section, title in (("C", "Section C, encumbrances"), ("D", "Section D, notes")):
        items = [r for r in rel if r["section"] == section]
        lines.append("%s: %s" % (title, "none" if not items else len(items)))
        for r in items:
            who = ", ".join(display_name(b) for b in r["beneficiaries"])
            lines.append("- %s (%s)%s%s" % (r["label"], r["category"], " for " + who if who else "",
                                            ": " + r["description"][:300] if r["description"] else ""))
    lines.append("Pending change: %s" % (", ".join(result["pending_proceedings"]) or "yes")
                 if result["pending_change"] else "Pending change: none")
    lines.append("Landlord from the call matches an owner: %s" % result["landlord_matches_owner"])
    reasons = " ".join(r[0].upper() + r[1:] + "." for r in result["risk_reasons"])
    lines.append("Lease risk: %s. %s" % (result["lease_risk"], reasons or "Nothing unusual."))
    lines.append("Land register data are informative. This is not legal advice.")
    return lines


def private_tokens(parsed, landlord):
    """What must never reach stdout: person name words, and company names as whole phrases.

    Person name words that are also words of the LV's own legal labels (e.g. a surname equal to a common noun)
    are left out, because those labels are printed on purpose.
    """
    label_words = {w for r in parsed["rights"] for w in words(r["label"])}
    people, phrases = set(name_tokens(landlord)), set()
    subjects = list(parsed["owners"]) + [b for r in parsed["rights"] for b in r["beneficiaries"]]
    for s in subjects:
        for prijmeni, jmeno in s["persons"]:
            people.update(name_tokens(prijmeni) + name_tokens(jmeno))
        if s["company"]:
            core = [w for w in words(s["company"]) if w not in LEGAL_FORMS]
            if core:
                phrases.add(" ".join(core))
    return {"words": {t for t in people if len(t) >= 3} - label_words, "phrases": phrases}


def assert_redacted(out, private):
    printed = words(json.dumps(out, ensure_ascii=False))
    text = " " + " ".join(printed) + " "
    leaked = (set(printed) & private["words"]) or [p for p in private["phrases"] if " %s " % p in text]
    if leaked:
        raise RuntimeError("redaction check failed: %d name(s) would be printed; nothing was printed" % len(leaked))


# ------------------------------------------------------------------ call answers on the page

ANSWER = re.compile(r"^-\s*Asked:\s*(.*?)\s+Answer:\s*(.*)$")
NO_ANSWER = re.compile(r"\b(unknown|not sure|don't know|do not know|no answer|did not say|n/a)\b", re.IGNORECASE)


def call_answers(text):
    """Unit number, floor, door and landlord name from the '- Asked: ... Answer: ...' lines of a call result."""
    found = {}
    for line in (text or "").splitlines():
        m = ANSWER.match(line.strip())
        if not m:
            continue
        question, answer = fold(m.group(1)), m.group(2).strip()
        if not answer or NO_ANSWER.search(answer):
            continue
        if re.search(r"unit|apartment number|flat number|jednotk|cislo bytu", question):
            n = re.search(r"\d+\s*/\s*\d+|\d+", answer)
            if n:
                found.setdefault("unit", re.sub(r"\s", "", n.group(0)))
        elif re.search(r"floor|patro|podlazi", question):
            n = re.search(r"-?\d+", answer)
            if n:
                found.setdefault("floor", n.group(0))
        elif re.search(r"door|dvere", question):
            found.setdefault("door", answer[:40])
        elif re.search(r"landlord|owner|majitel|pronajimatel|who owns|who rents", question):
            found.setdefault("landlord", answer[:200])
    return found


# ------------------------------------------------------------------ HTTP: RÚIAN, API KN

def http_json(url, headers=None):
    req = urllib.request.Request(url, headers=dict({"User-Agent": USER_AGENT, "Accept": "application/json"},
                                                   **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, ValueError) as e:
        raise RuntimeError("cannot read %s: %s" % (urllib.parse.urlsplit(url).netloc, e))


def resolve_address(address):
    """Address text -> {"address_point", "building_code"} from RÚIAN, or a Refusal when not unique."""
    status, data = http_json(RUIAN_GEOCODE + "?" + urllib.parse.urlencode({"SingleLine": address, "f": "json"}))
    hits = [c for c in (data or {}).get("candidates", []) if c.get("score") == 100
            and (c.get("attributes") or {}).get("Type") == "AdresniMisto"]
    if status != 200 or len(hits) != 1:
        raise Refusal("the address did not resolve to exactly one RÚIAN address point (%d exact matches); "
                      "pass the unit's address more precisely. Nothing was billed or changed." % len(hits))
    x, y = hits[0]["location"]["x"], hits[0]["location"]["y"]
    status, data = http_json(RUIAN_LAYER % 1 + "?" + urllib.parse.urlencode({
        "geometry": "%s,%s" % (x, y), "geometryType": "esriGeometryPoint", "inSR": "5514", "distance": "2",
        "units": "esriSRUnit_Meter", "outFields": "kod,stavebniobjekt", "returnGeometry": "false", "f": "json"}))
    features = (data or {}).get("features") or []
    if status != 200 or len(features) != 1:
        raise Refusal("the RÚIAN address point could not be read. Nothing was billed or changed.")
    a = features[0]["attributes"]
    return {"address_point": a["kod"], "building_code": a.get("stavebniobjekt")}


def ruian_building(building_code):
    status, data = http_json(RUIAN_LAYER % 3 + "?" + urllib.parse.urlencode({
        "where": "kod=%d" % int(building_code),
        "outFields": "isknbudovaid,castobce,cisladomovni,typstavebnihoobjektukod",
        "returnGeometry": "false", "f": "json"}))
    features = (data or {}).get("features") or []
    return features[0]["attributes"] if status == 200 and len(features) == 1 else None


def api_kn(path, key):
    status, data = http_json(API_KN + path, {"ApiKey": key})
    if status != 200 or not isinstance(data, dict) or data.get("data") is None:
        raise RuntimeError("API KN %s answered %s" % (path.split("/")[1], status))
    return data["data"]


# ------------------------------------------------------------------ WSDP (SOAP over curl)

def wsdp_call(creds, service, operation, body):
    """One WSDP SOAP call. The password goes to curl on stdin, never on the command line."""
    envelope = (
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v="%s">'
        '<soapenv:Header><wsse:Security soapenv:mustUnderstand="1" xmlns:wsse="http://docs.oasis-open.org/wss/2004/'
        '01/oasis-200401-wss-wssecurity-secext-1.0.xsd"><wsse:UsernameToken><wsse:Username>%s</wsse:Username>'
        '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0'
        '#PasswordText">%s</wsse:Password></wsse:UsernameToken></wsse:Security></soapenv:Header>'
        '<soapenv:Body><v:%sRequest>%s</v:%sRequest></soapenv:Body></soapenv:Envelope>'
        % (WSDP_NS % service, escape(creds["WSDP_USERNAME"]), escape(creds["WSDP_PASSWORD"]),
           operation[0].upper() + operation[1:], body, operation[0].upper() + operation[1:]))
    url = WSDP[creds["WSDP_ENV"]] + service
    run = subprocess.run(["curl", "-sS", "-m", "90", "-X", "POST", "-A", USER_AGENT,
                          "-H", "Content-Type: text/xml; charset=utf-8", "--data-binary", "@-", url],
                         input=envelope.encode("utf-8"), capture_output=True)
    if run.returncode != 0:
        raise RuntimeError("cannot reach WSDP (%s): curl exit %d" % (service, run.returncode))
    return run.stdout


def soap_root(raw):
    m = re.search(rb"<(?:[\w-]+:)?Envelope\b.*?</(?:[\w-]+:)?Envelope>", raw, re.S)
    if not m:
        raise RuntimeError("WSDP did not answer with SOAP")
    root = ET.fromstring(m.group(0))
    for e in root.iter():
        if e.tag.endswith("faultstring"):
            raise RuntimeError("WSDP fault: %s" % (e.text or "")[:160])
        if e.tag.endswith("}zprava") and e.get("uroven") == "CHYBA":
            raise RuntimeError("WSDP error %s: %s" % (e.get("kod"), (e.text or "")[:160]))
    return root


def first(root, local):
    for e in root.iter():
        if e.tag.split("}")[-1] == local:
            return (e.text or "").strip()
    return ""


def report_file(raw):
    """The report bytes from a vratSestavu answer: inline base64, or an MTOM attachment."""
    m = re.search(rb"<(?:[\w-]+:)?souborSestavy[^>]*>(.*?)</(?:[\w-]+:)?souborSestavy>", raw, re.S)
    if not m:
        raise RuntimeError("WSDP returned no report file")
    inner = m.group(1)
    include = re.search(rb'href="cid:([^"]+)"', inner)
    if not include:
        return base64.b64decode(inner)
    cid = urllib.parse.unquote(include.group(1).decode()).encode()
    for part in re.split(rb"\r?\n--[^\r\n]+", raw):
        head, sep, body = part.partition(b"\r\n\r\n")
        if not sep:
            head, sep, body = part.partition(b"\n\n")
        if cid in head:
            return body.strip()
    raise RuntimeError("WSDP report attachment not found")


def billing_guard(creds, path=None, today=None):
    """Count one billed WSDP output before it is requested. Refuses once today's cap is reached."""
    if creds["WSDP_ENV"] != "prod":
        return None
    try:
        cap = min(int(creds.get("WSDP_MAX_BILLED_PER_DAY") or BILLED_CAP), BILLED_CAP)
    except ValueError:
        cap = BILLED_CAP
    path = path or BILLING_FILE
    day = today or (datetime.datetime.now(PRAGUE) if PRAGUE else datetime.datetime.now()).date().isoformat()
    counts = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            counts = json.load(f)
    used = int(counts.get(day, 0))
    if used >= cap:
        raise Refusal("WSDP billed outputs today: %d of %d. Refusing another one. Nothing was billed or changed."
                      % (used, cap))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({day: used + 1}, f)
    os.replace(tmp, path)
    return {"billed_today": used + 1, "cap": cap}


def fetch_lv(creds, area_code, lv_number, sleep=time.sleep):
    """Billed: generujLVZjednodusene -> poll -> vratSestavu -> smazSestavu. Returns (LV XML bytes, billing).

    The LV is kept in memory only: owner names may be stored in Notion and nowhere else.
    """
    billing = billing_guard(creds)
    root = soap_root(wsdp_call(creds, "sestavy", "generujLVZjednodusene",
                               "<v:katastrUzemiKod>%d</v:katastrUzemiKod><v:lvCislo>%d</v:lvCislo>"
                               "<v:format>xml</v:format><v:verze>1.0</v:verze>" % (int(area_code), int(lv_number))))
    report_id = first(root, "id")
    if not report_id:
        raise RuntimeError("WSDP returned no report id")
    for _ in range(REPORT_POLLS):
        sleep(REPORT_POLL_SECONDS)
        state = first(soap_root(wsdp_call(creds, "sestavy", "seznamSestav",
                                          "<v:idSestavy>%s</v:idSestavy>" % report_id)), "stav")
        if state.startswith("zpracov"):
            break
        if state.startswith("chyba"):
            raise RuntimeError("WSDP could not build the LV report (%s)" % state)
    else:
        raise RuntimeError("the WSDP LV report was not ready in time; report id %s can be fetched later" % report_id)
    raw = wsdp_call(creds, "sestavy", "vratSestavu", "<v:idSestavy>%s</v:idSestavy>" % report_id)
    soap_root(raw)
    data = report_file(raw)
    try:
        wsdp_call(creds, "sestavy", "smazSestavu", "<v:idSestavy>%s</v:idSestavy>" % report_id)
    except RuntimeError:
        pass
    return data, billing


def locate_unit(creds, address, number):
    """Free steps: address -> building -> unit -> LV. Returns a dict, or candidates when the unit is ambiguous."""
    point = resolve_address(address)
    source = "api_kn"
    try:
        building = api_kn("/Stavby/AdresniMisto/%d" % int(point["address_point"]), creds["CUZK_API_KN_KEY"])
        units = [{"id": u["id"], "number": str(u["cisloJednotky"])} for u in building.get("jednotky") or []]
        plomby = ["%s-%s/%s-%s" % (p.get("typRizeni"), p.get("poradoveCislo"), p.get("rok"), p.get("kodPracoviste"))
                  for p in building.get("rizeniPlomby") or []]
        building_lv = building.get("lv") or {}
    except RuntimeError:
        source = "wsdp"
        so = ruian_building(point["building_code"]) if point.get("building_code") else None
        if not so or not so.get("isknbudovaid"):
            raise
        root = soap_root(wsdp_call(creds, "vyhledat", "najdiJednotku",
                                   "<v:stavbaId>%d</v:stavbaId>" % int(so["isknbudovaid"])))
        units = []
        for j in root.iter():
            if j.tag.endswith("}Jednotka"):
                units.append({"id": first(j, "idJednotky"), "number": unit_number(first(j, "cislo"))[1] or "",
                              "wsdp_lv_id": first(j, "lvId")})
        plomby, building_lv = [], {}
    if number:
        n = str(number).split("/")[-1].lstrip("0") or "0"
        hits = [u for u in units if u["number"].lstrip("0") == n or u["number"][-4:].lstrip("0") == n]
    else:
        hits = units if len(units) == 1 else []
    if not units:
        lv = building_lv
        if not lv.get("cislo"):
            raise Refusal("the building has no units and no LV in API KN. Nothing was billed or changed.")
        return {"lv_number": lv["cislo"], "area_code": lv["katastralniUzemi"]["kod"], "plomby": plomby,
                "source": source, "unit": None}
    if len(hits) != 1:
        return {"candidates": sorted(u["number"] for u in units), "source": source}
    if source == "wsdp":
        raise Refusal("API KN is unavailable and the WSDP fallback gives the LV id, not its number; "
                      "retry later. Nothing was billed or changed.")
    unit = api_kn("/Jednotky/%d" % int(hits[0]["id"]), creds["CUZK_API_KN_KEY"])
    plomby += ["%s-%s/%s-%s" % (p.get("typRizeni"), p.get("poradoveCislo"), p.get("rok"), p.get("kodPracoviste"))
               for p in unit.get("rizeniPlomby") or []]
    lv = unit.get("lv") or {}
    return {"lv_number": lv.get("cislo"), "area_code": (lv.get("katastralniUzemi") or {}).get("kod"),
            "plomby": sorted(set(plomby)), "source": source, "unit": str(unit.get("cisloJednotky"))}


# ------------------------------------------------------------------ commands

def lookup(args, backend_loader=None):
    cached = args.cached_lv
    creds = None
    if cached:
        if not os.path.isfile(cached):
            raise Refusal("the LV file does not exist. Nothing was read or changed.")
        parsed = parse_lv(cached)      # fail before touching Notion
    else:
        creds = require_live_credentials()
    if backend_loader is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import call
        def backend_loader():
            cfg = call.load_config()
            return cfg, call.load_backend(cfg).module
    cfg, backend = backend_loader()
    if not (hasattr(backend, "get_flat") and hasattr(backend, "append")):
        raise RuntimeError("the shortlist backend needs get_flat and append (config backend.module)")
    flat = backend.get_flat(cfg, args.page)
    answers = call_answers(flat.get("text"))
    number = args.unit or answers.get("unit")
    landlord = args.landlord or answers.get("landlord")
    floor, door = args.floor or answers.get("floor"), args.door or answers.get("door")
    out = {"page_id": flat["id"], "inputs": {"unit_number": bool(number), "floor_door": bool(floor or door),
                                             "landlord_name": bool(landlord)}}
    extra_plomba, billing = [], None
    if cached:
        source = "cached_lv"
        source_line = ("Source: cached LV XML from an earlier WSDP export (%s), not a live lookup. "
                       "The address was not checked against it." % ("signed" if parsed["signed"] else "unsigned"))
    else:
        address = (flat.get("listing") or {}).get("address")
        if not address:
            raise Refusal("the page has no address. Nothing was billed or changed.")
        found = locate_unit(creds, address, number)
        if "candidates" in found:
            out.update(status="unit_not_identified", unit_candidates=found["candidates"], billed=False,
                       note="pass --unit with one of the candidates; nothing was billed or changed")
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return 2
        data, billing = fetch_lv(creds, found["area_code"], found["lv_number"])
        parsed = parse_lv(data)
        number = number or found.get("unit")
        extra_plomba = [p for p in found["plomby"] if p not in parsed["proceedings"]]
        source = "wsdp"
        source_line = ("Source: live WSDP LV extract (WSDP_ENV=%s, %s), address resolved through RÚIAN and %s."
                       % (creds["WSDP_ENV"], "1 billed output" if billing else "not billed",
                          "API KN" if found["source"] == "api_kn" else "WSDP search"))
    result, owners, _ = assess(parsed, landlord, number, floor, door, extra_plomba)
    result["source"] = source
    marker = MARKER % "%s %s %s" % (source, parsed["lv"]["number"], result["as_of"])
    if marker in (flat.get("text") or "") and not args.force:
        out.update(status="already_checked", appended=False, result=result)
    else:
        lines = notion_section(result, parsed, owners, source_line) + [marker]
        backend.append(cfg, flat["id"], "\n".join(lines))
        out.update(status="appended", appended=True, result=result)
    if billing:
        out["billing"] = billing
    assert_redacted(out, private_tokens(parsed, landlord))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def parse_command(args):
    parsed = parse_lv(args.cached_lv)
    result, _, _ = assess(parsed, args.landlord, args.unit, args.floor, args.door)
    result["source"] = "cached_lv"
    out = {"status": "parsed", "result": result}
    assert_redacted(out, private_tokens(parsed, args.landlord))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv=None, backend_loader=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("lookup", "parse"):
        p = sub.add_parser(name)
        if name == "lookup":
            p.add_argument("--page", required=True, help="Notion page id of the flat")
            p.add_argument("--force", action="store_true", help="append even if this LV was already checked")
        p.add_argument("--cached-lv", required=(name == "parse"), help="an LV XML file (WSDP LV 1.0)")
        p.add_argument("--unit", help="unit number, e.g. 12 or 1800/12")
        p.add_argument("--floor")
        p.add_argument("--door")
        p.add_argument("--landlord", help="landlord name as said in the call (never printed)")
    args = parser.parse_args(argv)
    try:
        return lookup(args, backend_loader) if args.command == "lookup" else parse_command(args)
    except Refusal as e:
        print(json.dumps({"refused": str(e)}, indent=2, ensure_ascii=False))
        return 2
    except (RuntimeError, OSError, ValueError, KeyError, LVFormatError) as e:
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
