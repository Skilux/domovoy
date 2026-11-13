#!/usr/bin/env python3
"""DOMOVOY katastr check: who owns a flat, what encumbers it, and whether that is a lease risk.

The human-gated flow (see SKILL.md, "Katastr check"):
  katastr.py locate --page ID [--point LAT,LON | --address TEXT] [--area-m2 N]
      Free. Finds the building from the listing's map point (read from the listing page) or an address,
      lists its units with their LV and their floor area estimated from the share on the common parts,
      and ranks the flats by the listing's area. Bills nothing and writes nothing.
  katastr.py fetch --area CODE --lv N [--format xml|pdf] --confirm-billed
      BILLED on WSDP_ENV=prod: one LV extract, 100 CZK. Saves it in KATASTR_LV_DIR (default
      ~/.config/domovoy/lv), never inside a git checkout. Refuses without --confirm-billed: ask the user first.
  katastr.py lookup --page ID --cached-lv FILE [--unit N] [--floor F --door D] [--landlord NAME]
      Free. Analyses the LV XML for the flat (owners, encumbrances, easements, pending changes) and appends
      a "Katastr check" section with the questions to ask the landlord to the Notion page.
  katastr.py attach --page ID --file LV.pdf
      Free. Uploads the LV PDF to Notion and adds it to the flat's page, once.

Also:
  katastr.py lookup --page ID --confirm-billed [--unit N] ...
      Live in one step: resolves the page's address, orders the LV (billed, as fetch) and analyses it.
  katastr.py parse --cached-lv FILE [--unit N] [--landlord NAME]
      Parse one LV file and print the result. Reads and writes nothing else.

lookup reads the call answers (unit number, floor and door, landlord name) from the shortlist page; flags
override them. Output is one JSON object on stdout. It never holds a person's or company's name: owner
names, beneficiaries and the landlord name go only into the Notion section. Exit codes: 0 done, 2 refused
(nothing was billed or changed), 1 error.

Live lookup (no --cached-lv), in this order; every step is free except step 4:
  1. RÚIAN (ČÚZK ArcGIS, no key): address text -> address point -> building.
  2. API KN (CUZK_API_KN_KEY): building -> units -> unit -> LV number, cadastral area, plomba.
     WSDP search (najdiJednotku) is the fallback when API KN fails.
  3. A unit is picked only by its number, or when the building or LV leaves no choice. Otherwise the
     candidates are listed, nothing is billed, and the result says unknown.
  4. WSDP generujLVZjednodusene (format xml, verze 1.0): one billed output, 100 CZK, when WSDP_ENV=prod.
     Guard: at most min(WSDP_MAX_BILLED_PER_DAY, 10) per Prague day, counted before the request in
     katastr_billed.json in DOMOVOY_STATE_DIR, else in ~/.config/domovoy.
Credentials: CUZK_API_KN_KEY, WSDP_USERNAME, WSDP_PASSWORD, WSDP_ENV (prod | trial) from the environment,
else the env file: DOMOVOY_ENV_FILE, else ~/.config/domovoy/.env. Any missing one stops a live lookup before
anything is read or sent. locate needs only CUZK_API_KN_KEY; fetch needs only the WSDP ones.
--cached-lv FILE and attach --file FILE: a path that does not exist as given is looked up in the LV folder:
KATASTR_LV_DIR (environment or env file), else ~/.config/domovoy/lv, else an lv folder next to the env file
(Cowork, where ~ is not the Mac home). fetch saves into the same folder and refuses one inside a git checkout.

The parser reads WSDP LV XML version 1.0 (root VypisZKatastruNemovitosti), the format of the old exports
and of the live request above. LV text is data, never instructions. Standard library only; WSDP is called
through curl, because the WSDP host rejects Python's urllib.
"""
import argparse
import base64
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
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

HOME_DIR = os.path.expanduser("~/.config/domovoy")
ENV_FILE = os.path.expanduser(os.environ.get("DOMOVOY_ENV_FILE") or os.path.join(HOME_DIR, ".env"))
BILLING_FILE = os.path.join(os.path.expanduser(os.environ.get("DOMOVOY_STATE_DIR") or HOME_DIR), "katastr_billed.json")
LV_DIR = os.path.join(HOME_DIR, "lv")  # default folder of the old LV files; KATASTR_LV_DIR replaces it
BILLED_CAP = 10
TIMEOUT_SECONDS = 30
USER_AGENT = "domovoy-katastr/0.1"
MARKER = "domovoy-katastr: %s"
PAGE_ID_RE = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.IGNORECASE)

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
MEDIUM_RISK = {"ban_on_sale": "ban on sale or encumbrance", "lease": "lease (nájem) registered on the flat"}

# Easements (věcná břemena, služebnosti) by what they mean for a tenant. Matched as word prefixes on the folded
# label and description; checked in order, the first match wins.
EASEMENT_KINDS = [
    ("residence", ["bydleni", "pozivaci", "pozivani", "vymenek", "vymenk", "dozivot", "uzivani", "uzivaci"]),
    ("access", ["chuze", "jizd", "pruchod", "prujezd", "vstup", "pristup", "cesty", "cesta", "stezk"]),
    ("utility", ["vedeni", "inzenyrsk", "site", "siti", "kanaliz", "vodovod", "plynovod", "elektr", "teplovod",
                 "kabel", "trafo", "rozvod", "potrubi", "provozovani", "opery", "anten", "udrzb"]),
]
EASEMENT_RISK = {
    # kind, on the flat itself? -> (level, reason) ; level None = report only
    ("residence", True): ("high", "a right to live in or use the flat is registered for someone else"),
    ("residence", False): ("medium", "a right to use part of the house or its land is registered"),
    ("access", True): ("medium", "someone has a registered right to pass through or enter the flat"),
    ("access", False): (None, None),
    ("utility", True): (None, None),
    ("utility", False): (None, None),
    ("other", True): ("medium", "an easement of an unrecognised kind is registered on the flat"),
    ("other", False): (None, None),
}
EASEMENT_NAMES = {"residence": "right to live in or use", "access": "right of way or entry",
                  "utility": "utility line", "other": "other easement"}
BILLED_PRICE_CZK = 100
LISTING_USER_AGENT = "Mozilla/5.0 (compatible; domovoy-katastr/0.1)"
CZ_BOX = (48.5, 51.1, 12.0, 19.0)                      # lat min, lat max, lon min, lon max
EXACT_METRES = 2.0                                     # a map point this close to an address point is that address
NEAR_METRES = 60                                       # candidates listed when the point is not exact
MAX_UNITS = 150                                        # API KN calls per locate are 1 + units

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


# What stdout may say about a restriction: internal category -> public type. Anything else is "other".
PUBLIC_TYPES = {"mortgage": "mortgage", "enforcement_lien": "distraint", "execution": "distraint",
                "insolvency": "insolvency", "ban_on_sale": "ban_on_sale", "easement": "easement",
                "dispute": "pending_change"}
SECTIONS = ("B1", "C", "D")
NOTION_CODES = {"object_not_found", "unauthorized", "restricted_resource", "validation_error", "rate_limited",
                "conflict_error", "internal_server_error", "service_unavailable", "invalid_request",
                "invalid_json", "missing_version", "gateway_timeout"}
SAFE_TYPES = {"KeyError", "ValueError", "TypeError", "OSError", "FileNotFoundError", "PermissionError",
              "ParseError", "JSONDecodeError", "RuntimeError", "NotionError", "IndexError", "AttributeError",
              "TimeoutError", "ConnectionError", "UnicodeDecodeError"}
STAGE = {"now": "starting"}
UNIT_RE = re.compile(r"\d{1,6}(/\d{1,6})?")
SHARE_RE = re.compile(r"\d{1,15}/\d{1,15}")
PROCEEDING_RE = re.compile(r"[A-Z]{1,4}-\d{1,8}/\d{4}-\d{1,4}")
DIGITS_RE = re.compile(r"\d{1,20}")
_BILLING_HOOK = None   # tests only: called inside the billing lock, after the counter is read


class Refusal(Exception):
    """Stopped on purpose; nothing was billed or changed. The message is a fixed local text."""


class KatastrError(RuntimeError):
    """A failure whose message is fixed local text with no response, fault or file content: safe to print."""


class LVFormatError(KatastrError):
    pass


def stage(name):
    STAGE["now"] = name


def safe(value, pattern):
    """value if it fully matches pattern, else "unrecognised". For strings that come from outside."""
    value = "" if value is None else str(value)
    return value if pattern.fullmatch(value) else "unrecognised"


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


def lv_dir():
    """The folder of the old LV files: KATASTR_LV_DIR, else ~/.config/domovoy/lv, else lv/ next to the env file."""
    configured = settings(["KATASTR_LV_DIR"])["KATASTR_LV_DIR"]
    if configured:
        return os.path.expanduser(configured)
    if os.path.isdir(LV_DIR):
        return LV_DIR
    return os.path.join(os.path.dirname(ENV_FILE), "lv")


def resolve_lv(path):
    """path as given when it is a file, else the same relative path inside the LV folder (when that is a file)."""
    if not path or os.path.isfile(path) or os.path.isabs(path):
        return path
    candidate = os.path.join(lv_dir(), path)
    return candidate if os.path.isfile(candidate) else path


def require_live_credentials(names=None):
    names = list(names or LIVE_CREDENTIALS)
    values = settings(names + ["WSDP_MAX_BILLED_PER_DAY"])
    missing = [name for name in names if not values[name]]
    if missing:
        raise Refusal("missing credentials: %s. Set them in %s. Nothing was read or changed."
                      % (", ".join(missing), ENV_FILE))
    if "WSDP_ENV" in names and values["WSDP_ENV"] not in WSDP:
        raise Refusal("WSDP_ENV must be prod or trial. Nothing was read or changed.")
    return values


def billed_gate(creds, confirmed, what):
    """The human gate: a billed WSDP output needs --confirm-billed, given only after the user said yes."""
    if creds["WSDP_ENV"] == "prod" and not confirmed:
        raise Refusal("%s orders 1 billed WSDP output (%d CZK, WSDP_ENV=prod). Ask the user, and only after a yes "
                      "run it again with --confirm-billed. Nothing was billed or changed." % (what, BILLED_PRICE_CZK))


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


def easement_kind(label, description=""):
    """residence | access | utility | other, from the label first, then from the description."""
    for text in (label, description):
        tokens = words(text)
        for kind, needles in EASEMENT_KINDS:
            if any(t.startswith(n) for t in tokens for n in needles):
                return kind
    return "other"


def jednotka_label(node):
    """'1200/65' from a <jednotka> element. Real LVs keep the building number in cp_ident and only the unit
    number in jed_ident; the synthetic fixtures carry both in jed_ident."""
    jed, cp = txt(node, "jed_ident"), txt(node, "cp_ident")
    digits = re.search(r"\d+", cp)
    if jed and "/" not in jed and digits:
        return "%s/%s" % (digits.group(0), jed)
    return jed


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
    except ET.ParseError:
        raise LVFormatError("the LV is not well-formed XML")
    if root.tag != "VypisZKatastruNemovitosti":
        raise LVFormatError("the LV is not a WSDP LV 1.0 file")
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
            ident = jednotka_label(j.find("CISLO_JEDNOTKY/jednotka"))
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
                description = joined(jpv, "JPV_POPISY/JPV_POPIS/POPIS_PRAVNIHO_VZTAHU")
                beneficiaries = [subject_of(n) for n in
                                 jpv.findall("JPV_OPRAV_PRO_OS/JPV_PRO_OS/PRO_IDENT_OS/oprav_subjekt")]
                burdened = jpv.findall("JPV_POVIN_K_NEM/JPV_K_NEM/K_IDENT_NEM")
                on_units = [jednotka_label(n.find("jednotka")) for n in burdened if txt(n, "jednotka/jed_ident")]
                others = [n for n in burdened if not txt(n, "jednotka/jed_ident")]
                if not (label or description or on_units or others or beneficiaries):
                    continue   # the empty JPV the XSD requires in every section: not an entry
                category = category_of(label)
                rights.append({
                    "section": section.get("SEKCE") if section.get("SEKCE") in SECTIONS else "unrecognised",
                    "label": label,
                    "category": category,
                    "description": description,
                    "beneficiaries": [b for b in beneficiaries if b and b["kind"] != "unknown"],
                    "units": on_units,
                    "other_objects": len(others),     # parcels or buildings burdened by the same entry
                    "for_property": jpv.find("JPV_OPRAV_PRO_NEM/JPV_PRO_NEM") is not None,
                    "easement_kind": easement_kind(label, description) if category == "easement" else None,
                })

    proceedings = []
    for t in texty:
        for p in t.findall("ZMENY_PV/ZMENA_PV/PLOMBA") + t.findall("D1_UPOZORNENI/SEZNAM_RIZENI/IDENT_RIZENI"):
            if txt(p, "typriz_kod"):
                proceedings.append("%s-%s/%s-%s" % (txt(p, "typriz_kod"), txt(p, "poradove_cislo"),
                                                    txt(p, "rok"), txt(p, "prares_kod")))
    building_lvs = sorted({txt(s, "cislo_tel") for t in texty for s in
                           t.findall("JEDNOTKY/JEDNOTKA/BUDOVY/BUDOVA/JED_OPSUB/stavba") if txt(s, "cislo_tel")})
    return {"lv": lv, "owners": owners, "units": units, "rights": rights,
            "proceedings": sorted(set(proceedings)), "as_of": prague_iso(txt(root, "PLATNOST")),
            "issued": prague_iso(txt(root, "VYHOTOVENO")), "building_lvs": building_lvs,
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
            return None, candidates, "the unit number from the call is not on this LV"
        return None, candidates, "the unit number from the call matches several units"
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

    high, medium, easements = [], [], []
    for r in relevant:
        on_unit = (unit["label"] in r["units"]) if unit and unit["label"] else bool(r["units"])
        if r["category"] in HIGH_RISK:
            high.append("%s in section %s" % (HIGH_RISK[r["category"]], r["section"]))
        elif r["category"] in MEDIUM_RISK:
            medium.append("%s in section %s" % (MEDIUM_RISK[r["category"]], r["section"]))
        elif r["category"] == "easement":
            kind = r.get("easement_kind") or "other"
            level, reason = EASEMENT_RISK[(kind, on_unit)]
            easements.append({"section": r["section"], "kind": kind, "on_unit": on_unit,
                              "for": "property" if r.get("for_property") else ("person" if r["beneficiaries"]
                                                                               else "unknown"),
                              "impact": level or "low", "label": r["label"], "description": r["description"],
                              "beneficiaries": r["beneficiaries"]})
            if level == "high":
                high.append("%s (section %s)" % (reason, r["section"]))
            elif level == "medium":
                medium.append("%s (section %s)" % (reason, r["section"]))
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
        "easements": easements,
        "building_lvs": list(parsed.get("building_lvs") or []),
        "as_of": parsed["as_of"],
    }
    result["questions"] = questions_for(result, relevant, kinds, len(owners))
    return result, owners, unit


def questions_for(result, relevant, kinds, owner_count):
    """What to ask the landlord or the realtor, from fixed English templates only (no LV text, no names)."""
    cats = {r["category"] for r in relevant}
    q = []
    if result["unit_number"] is None and result["unit_candidates"]:
        q.append("What is the flat's unit number in the land register (číslo jednotky)?")
    if result["landlord_matches_owner"] == "no":
        q.append("The landlord you named is not an owner in the land register. On what basis do they rent the "
                 "flat out, and can they show the owner's written consent to the sublease?")
    elif result["landlord_matches_owner"] == "unknown":
        q.append("Who exactly will be the landlord in the contract?")
    if "company" in kinds:
        q.append("A company owns the flat. Who signs the lease for it, and can they show their authority "
                 "(a commercial register extract or a power of attorney)?")
    if "cooperative" in kinds:
        q.append("A housing co-op owns the flat. Has the co-op agreed to the sublease in writing?")
    if owner_count > 2:
        q.append("The flat has %d co-owners. Do the owners holding a majority of the shares agree to the lease?"
                 % owner_count)
    if "mortgage" in cats and "ban_on_sale" in cats:
        q.append("The flat is mortgaged, with a ban on sale and encumbrance for the lender. Does the lender have to "
                 "agree to the lease, and has it?")
    elif "ban_on_sale" in cats:
        q.append("A ban on sale or encumbrance is registered. Who holds it, and does it need to agree to the lease?")
    if cats & {"execution", "enforcement_lien", "insolvency"}:
        q.append("An enforcement or insolvency entry is registered on the flat. What is its status? "
                 "A forced sale could end the lease.")
    if "dispute" in cats:
        q.append("A dispute note is registered on the flat. What is the dispute about?")
    if result["pending_change"]:
        ids = ", ".join(safe(p, PROCEEDING_RE) for p in result["pending_proceedings"])
        q.append("A change is pending in the land register%s. What is it, and will the owner change?"
                 % (" (%s)" % ids if ids else ""))
    if "lease" in cats:
        q.append("A lease is registered on the flat. Has it ended?")
    kinds_on = {(e["kind"], e["on_unit"]) for e in result["easements"]}
    if ("residence", True) in kinds_on:
        q.append("A right to live in or use the flat is registered for someone else. Who holds it, and will they "
                 "use the flat during the lease?")
    if ("residence", False) in kinds_on:
        q.append("A right to use part of the house or its land is registered. Which parts does it cover, and does "
                 "it touch the flat, its cellar or the shared spaces?")
    if ("access", True) in kinds_on:
        q.append("Someone has a registered right to pass through or enter the flat. Where exactly, and how often?")
    if ("utility", True) in kinds_on:
        q.append("A utility easement is registered on the flat. Does a utility company need access to the flat?")
    if ("other", True) in kinds_on:
        q.append("An easement is registered on the flat. What does it allow, and does it affect a tenant?")
    return q


def public_result(result):
    """The stdout view of a result: fixed vocabulary, counts, and validated numbers only.

    Raw LV text (restriction labels, descriptions, names) never goes here; it goes only to the Notion section.
    """
    restrictions = [{"section": r["section"] if r["section"] in SECTIONS else "unrecognised",
                     "type": PUBLIC_TYPES.get(r["type"], "other")} for r in result["restrictions"]]
    return {
        "unit_type": result["unit_type"],
        "unit_regime": result["unit_regime"],
        "unit_number": None if result["unit_number"] is None else safe(result["unit_number"], UNIT_RE),
        "unit_candidates": [safe(c, UNIT_RE) for c in result["unit_candidates"]],
        "unit_note": result["unit_note"],
        "owner_types": result["owner_types"],
        "owner_count": result["owner_count"],
        "owner_shares": [safe(s, SHARE_RE) for s in result["owner_shares"]],
        "restrictions": restrictions,
        "restriction_types": sorted({r["type"] for r in restrictions}),
        "pending_change": result["pending_change"],
        "pending_proceedings": [safe(p, PROCEEDING_RE) for p in result["pending_proceedings"]],
        "landlord_matches_owner": result["landlord_matches_owner"],
        "lease_risk": result["lease_risk"],
        "risk_reasons": result["risk_reasons"],
        "easements": [{"section": e["section"] if e["section"] in SECTIONS else "unrecognised",
                       "kind": e["kind"], "on_unit": bool(e["on_unit"]), "for": e["for"], "impact": e["impact"]}
                      for e in result.get("easements", [])],
        "questions": list(result.get("questions", [])),
        "building_lvs_not_checked": [safe(n, DIGITS_RE) for n in result.get("building_lvs", [])],
        "as_of": result["as_of"],
        "source": result.get("source"),
    }


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
            who = ", ".join(dict.fromkeys(display_name(b) for b in r["beneficiaries"]))
            lines.append("- %s (%s)%s%s" % (r["label"], r["category"], " for " + who if who else "",
                                            ": " + one_line(r["description"]) if r["description"] else ""))
    lines.append("Pending change: %s" % (", ".join(result["pending_proceedings"]) or "yes")
                 if result["pending_change"] else "Pending change: none")
    easements = result.get("easements") or []
    lines.append("Easements (věcná břemena) on this LV: %s" % ("none" if not easements else len(easements)))
    for e in easements:
        who = ", ".join(dict.fromkeys(display_name(b) for b in e["beneficiaries"]))
        lines.append("- %s: %s, %s, in favour of %s. Impact for a tenant: %s.%s"
                     % (e["label"] or "easement", EASEMENT_NAMES[e["kind"]],
                        "on the flat itself" if e["on_unit"] else "on other property on this LV",
                        who or ("a property" if e["for"] == "property" else "unknown"),
                        e["impact"], " " + one_line(e["description"]) if e["description"] else ""))
    for n in result.get("building_lvs") or []:
        lines.append("Not checked: LV %s (the land and the building as a whole). An easement or other entry on "
                     "the whole house would be listed there." % n)
    lines.append("Landlord from the call matches an owner: %s" % result["landlord_matches_owner"])
    reasons = " ".join(r[0].upper() + r[1:] + "." for r in result["risk_reasons"])
    lines.append("Lease risk: %s. %s" % (result["lease_risk"], reasons or "Nothing unusual."))
    questions = result.get("questions") or []
    if questions:
        lines.append("Questions for the landlord or the realtor:")
        lines += ["- " + q for q in questions]
    lines.append("Land register data are informative. This is not legal advice.")
    return lines


def one_line(text, limit=300):
    return " ".join((text or "").split())[:limit]


def private_tokens(parsed, landlord):
    """What must never reach stdout: person name words, and company names as whole phrases.

    A second line of defence behind public_result(): nothing here is exempted on the strength of LV content.
    """
    people, phrases = set(name_tokens(landlord)), set()
    subjects = list(parsed["owners"]) + [b for r in parsed["rights"] for b in r["beneficiaries"]]
    for s in subjects:
        for prijmeni, jmeno in s["persons"]:
            people.update(name_tokens(prijmeni) + name_tokens(jmeno))
        if s["company"]:
            core = [w for w in words(s["company"]) if w not in LEGAL_FORMS]
            if core:
                phrases.add(" ".join(core))
    return {"words": {t for t in people if len(t) >= 3}, "phrases": phrases}


def assert_redacted(out, private):
    printed = words(json.dumps(out, ensure_ascii=False))
    text = " " + " ".join(printed) + " "
    leaked = (set(printed) & private["words"]) or [p for p in private["phrases"] if " %s " % p in text]
    if leaked:
        raise KatastrError("redaction check failed: a name would have been printed; nothing was printed")


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

def http_json(url, headers=None, label="the service"):
    req = urllib.request.Request(url, headers=dict({"User-Agent": USER_AGENT, "Accept": "application/json"},
                                                   **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, ValueError, OSError):
        raise KatastrError("cannot read %s" % label)


def resolve_address(address):
    """Address text -> {"address_point", "building_code"} from RÚIAN, or a Refusal when not unique."""
    status, data = http_json(RUIAN_GEOCODE + "?" + urllib.parse.urlencode({"SingleLine": address, "f": "json"}),
                             label="RÚIAN")
    hits = [c for c in (data or {}).get("candidates", []) if c.get("score") == 100
            and (c.get("attributes") or {}).get("Type") == "AdresniMisto"]
    if status != 200 or len(hits) != 1:
        raise Refusal("the address did not resolve to exactly one RÚIAN address point (%d exact matches); "
                      "pass the unit's address more precisely. Nothing was billed or changed." % len(hits))
    x, y = hits[0]["location"]["x"], hits[0]["location"]["y"]
    status, data = http_json(RUIAN_LAYER % 1 + "?" + urllib.parse.urlencode({
        "geometry": "%s,%s" % (x, y), "geometryType": "esriGeometryPoint", "inSR": "5514", "distance": "2",
        "units": "esriSRUnit_Meter", "outFields": "kod,stavebniobjekt", "returnGeometry": "false", "f": "json"}),
        label="RÚIAN")
    features = (data or {}).get("features") or []
    if status != 200 or len(features) != 1:
        raise Refusal("the RÚIAN address point could not be read. Nothing was billed or changed.")
    a = features[0]["attributes"]
    return {"address_point": a["kod"], "building_code": a.get("stavebniobjekt")}


def ruian_building(building_code):
    status, data = http_json(RUIAN_LAYER % 3 + "?" + urllib.parse.urlencode({
        "where": "kod=%d" % int(building_code),
        "outFields": "isknbudovaid,castobce,cisladomovni,typstavebnihoobjektukod",
        "returnGeometry": "false", "f": "json"}), label="RÚIAN")
    features = (data or {}).get("features") or []
    return features[0]["attributes"] if status == 200 and len(features) == 1 else None


def api_kn(path, key):
    status, data = http_json(API_KN + path, {"ApiKey": key}, label="API KN")
    if status != 200 or not isinstance(data, dict) or data.get("data") is None:
        raise KatastrError("API KN answered HTTP %d without data" % int(status or 0))
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
        raise KatastrError("cannot reach WSDP (curl exit %d)" % int(run.returncode))
    return run.stdout


def soap_root(raw):
    m = re.search(rb"<(?:[\w-]+:)?Envelope\b.*?</(?:[\w-]+:)?Envelope>", raw, re.S)
    if not m:
        raise KatastrError("WSDP did not answer with SOAP")
    try:
        root = ET.fromstring(m.group(0))
    except ET.ParseError:
        raise KatastrError("WSDP answered with malformed XML")
    for e in root.iter():
        if e.tag.endswith("Fault"):
            raise KatastrError("WSDP returned a SOAP fault")
        if e.tag.endswith("}zprava") and e.get("uroven") == "CHYBA":
            code = e.get("kod") or ""
            raise KatastrError("WSDP returned error code %s" % (code if re.fullmatch(r"\d{1,4}", code) else "?"))
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
        raise KatastrError("WSDP returned no report file")
    inner = m.group(1)
    include = re.search(rb'href="cid:([^"]+)"', inner)
    if not include:
        try:
            return base64.b64decode(inner)
        except ValueError:
            raise KatastrError("WSDP returned a report file that is not base64")
    cid = urllib.parse.unquote(include.group(1).decode()).encode()
    for part in re.split(rb"\r?\n--[^\r\n]+", raw):
        head, sep, body = part.partition(b"\r\n\r\n")
        if not sep:
            head, sep, body = part.partition(b"\n\n")
        if cid in head:
            return body.strip()
    raise KatastrError("WSDP report attachment not found")


def billing_guard(creds, path=None, today=None):
    """Reserve one billed WSDP output before it is requested. Refuses once today's cap is reached.

    The read-check-increment runs under an exclusive flock on a stable lock file next to the counter, so
    concurrent lookups (threads or processes) cannot both take the last slot. The counter is replaced
    atomically through a unique temporary file. An unreadable counter refuses (fails closed).
    """
    if creds["WSDP_ENV"] != "prod":
        return None
    try:
        cap = min(int(creds.get("WSDP_MAX_BILLED_PER_DAY") or BILLED_CAP), BILLED_CAP)
    except ValueError:
        cap = BILLED_CAP
    path = path or BILLING_FILE
    folder = os.path.dirname(path) or "."
    day = today or (datetime.datetime.now(PRAGUE) if PRAGUE else datetime.datetime.now()).date().isoformat()
    os.makedirs(folder, exist_ok=True)
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            counts = {}
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        counts = json.load(f)
                    used = int(counts.get(day, 0))
                except (ValueError, TypeError, AttributeError):
                    raise Refusal("the WSDP billing counter is unreadable; refusing. Nothing was billed or changed.")
            else:
                used = 0
            if _BILLING_HOOK:
                _BILLING_HOOK()
            if used >= cap:
                raise Refusal("WSDP billed outputs today: %d of %d. Refusing another one. "
                              "Nothing was billed or changed." % (used, cap))
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".katastr_billed.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({day: used + 1}, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return {"billed_today": used + 1, "cap": cap}


def fetch_lv(creds, area_code=None, lv_number=None, lv_id=None, sleep=time.sleep, fmt="xml"):
    """Billed: generujLVZjednodusene (area code + LV number) or generujLV (LV id) -> poll -> vratSestavu ->
    smazSestavu. Returns (report bytes, billing). fmt "xml" pins LV XML version 1.0; "pdf" is the print form.

    lookup keeps the LV in memory only; fetch saves it outside any git checkout (KATASTR_LV_DIR).
    """
    if lv_id is not None:
        operation, body = "generujLV", "<v:lvId>%d</v:lvId>" % int(lv_id)
    else:
        operation = "generujLVZjednodusene"
        body = "<v:katastrUzemiKod>%d</v:katastrUzemiKod><v:lvCislo>%d</v:lvCislo>" % (int(area_code), int(lv_number))
    body += "<v:format>xml</v:format><v:verze>1.0</v:verze>" if fmt == "xml" else "<v:format>pdf</v:format>"
    billing = billing_guard(creds)
    stage("ordering the LV from WSDP")
    root = soap_root(wsdp_call(creds, "sestavy", operation, body))
    report_id = first(root, "id")
    if not DIGITS_RE.fullmatch(report_id):
        raise KatastrError("WSDP returned no usable report id")
    for _ in range(REPORT_POLLS):
        sleep(REPORT_POLL_SECONDS)
        state = first(soap_root(wsdp_call(creds, "sestavy", "seznamSestav",
                                          "<v:idSestavy>%s</v:idSestavy>" % report_id)), "stav")
        if state.startswith("zpracov"):
            break
        if state.startswith("chyba"):
            raise KatastrError("WSDP could not build the LV report")
    else:
        raise KatastrError("the WSDP LV report was not ready in time; report id %s can be fetched later" % report_id)
    raw = wsdp_call(creds, "sestavy", "vratSestavu", "<v:idSestavy>%s</v:idSestavy>" % report_id)
    soap_root(raw)
    data = report_file(raw)
    try:
        wsdp_call(creds, "sestavy", "smazSestavu", "<v:idSestavy>%s</v:idSestavy>" % report_id)
    except Exception:
        pass
    return data, billing


def locate_unit(creds, address, number):
    """Free steps: address -> building -> unit -> LV. Returns a dict, or candidates when the unit is ambiguous."""
    point = resolve_address(address)
    source = "api_kn"
    try:
        building = api_kn("/Stavby/AdresniMisto/%d" % int(point["address_point"]), creds["CUZK_API_KN_KEY"])
        units = [{"id": u["id"], "number": safe(u.get("cisloJednotky"), DIGITS_RE)}
                 for u in building.get("jednotky") or []]
        plomby = [plomba_id(p) for p in building.get("rizeniPlomby") or []]
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
                units.append({"id": first(j, "idJednotky"),
                              "number": safe(unit_number(first(j, "cislo"))[1], DIGITS_RE),
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
        lv_id = hits[0]["wsdp_lv_id"]
        if not DIGITS_RE.fullmatch(lv_id or ""):
            raise Refusal("WSDP search found the unit but no LV id. Nothing was billed or changed.")
        return {"lv_id": lv_id, "plomby": [], "source": source, "unit": hits[0]["number"]}
    unit = api_kn("/Jednotky/%d" % int(hits[0]["id"]), creds["CUZK_API_KN_KEY"])
    plomby += [plomba_id(p) for p in unit.get("rizeniPlomby") or []]
    lv = unit.get("lv") or {}
    return {"lv_number": lv.get("cislo"), "area_code": (lv.get("katastralniUzemi") or {}).get("kod"),
            "plomby": sorted(set(plomby)), "source": source, "unit": safe(unit.get("cisloJednotky"), DIGITS_RE)}


def plomba_id(p):
    return safe("%s-%s/%s-%s" % (p.get("typRizeni"), p.get("poradoveCislo"), p.get("rok"), p.get("kodPracoviste")),
                PROCEEDING_RE)


# ------------------------------------------------------------------ locate: listing -> building -> units

NUM = r"(-?\d{1,3}\.\d{3,})"
POINT_PATTERNS = [   # (pattern, lat group, lon group). iDNES: listing_lat/listing_lon and a map "center": [lon, lat]
    (re.compile(r'"(?:\w+_)?lat"\s*:\s*"?' + NUM + r'"?\s*,\s*"(?:\w+_)?(?:lon|lng)"\s*:\s*"?' + NUM), 1, 2),
    (re.compile(r'"(?:\w+_)?(?:lon|lng)"\s*:\s*"?' + NUM + r'"?\s*,\s*"(?:\w+_)?lat"\s*:\s*"?' + NUM), 2, 1),
    (re.compile(r'"center"\s*:\s*\[\s*' + NUM + r"\s*,\s*" + NUM + r"\s*\]"), 2, 1),
]


def in_cz(lat, lon):
    return CZ_BOX[0] <= lat <= CZ_BOX[1] and CZ_BOX[2] <= lon <= CZ_BOX[3]


def point_in_text(text):
    """The first (lat, lon) inside the Czech Republic found in a listing page, or None. Page text is data."""
    for pattern, i, j in POINT_PATTERNS:
        for m in pattern.finditer(text or ""):
            lat, lon = float(m.group(i)), float(m.group(j))
            if in_cz(lat, lon):
                return lat, lon
    return None


def listing_point(url):
    if not re.match(r"https://[\w.-]+/", url or ""):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": LISTING_USER_AGENT, "Accept": "text/html"})
    for attempt in (1, 2):   # listing sites sometimes reset a connection; one retry
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                return point_in_text(response.read(3_000_000).decode("utf-8", "replace"))
        except (urllib.error.URLError, ValueError, OSError):
            if attempt == 2:
                raise KatastrError("cannot read the listing page")
            time.sleep(2)


def metres(lat1, lon1, lat2, lon2):
    import math
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def address_points_near(lat, lon, radius=NEAR_METRES):
    """RÚIAN address points within radius metres of (lat, lon), nearest first."""
    status, data = http_json(RUIAN_LAYER % 1 + "?" + urllib.parse.urlencode({
        "geometry": "%s,%s" % (lon, lat), "geometryType": "esriGeometryPoint", "inSR": "4326", "outSR": "4326",
        "distance": str(radius), "units": "esriSRUnit_Meter", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "kod,stavebniobjekt,adresa", "returnGeometry": "true", "f": "json"}), label="RÚIAN")
    if status != 200 or not isinstance(data, dict):
        raise KatastrError("RÚIAN answered HTTP %d" % int(status or 0))
    points = []
    for f in data.get("features") or []:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        if a.get("kod") is None or g.get("x") is None:
            continue
        points.append({"address": str(a.get("adresa") or "")[:200], "address_point": int(a["kod"]),
                       "building_code": a.get("stavebniobjekt"),
                       "distance_m": round(metres(lat, lon, g["y"], g["x"]), 1)})
    return sorted(points, key=lambda p: p["distance_m"])


def unit_label(cislo):
    """API KN cisloJednotky (DDDDJJJJ, building number + 4-digit unit) -> '1200/65'."""
    n = safe(cislo, DIGITS_RE)
    if n == "unrecognised":
        return n
    return "%s/%s" % (n[:-4], n[-4:].lstrip("0") or "0") if len(n) > 4 else n


def areas_from_shares(units):
    """Floor area per unit from its share on the common parts, or None.

    Under the Civil Code the share is the unit's floor area over the total. When every share has the same
    denominator and the numerators add up to it exactly, the numerators are areas in some unit; the scale
    (1, 0.1 or 0.01 m2) is the one that puts the median flat between 20 and 200 m2. It is an estimate.
    """
    shares = [u.get("share") for u in units]
    if not shares or any(not s for s in shares):
        return None
    dens = {s[1] for s in shares}
    if len(dens) != 1:
        return None
    den = dens.pop()
    if sum(s[0] for s in shares) != den or re.fullmatch(r"10*", str(den)):
        return None
    nums = sorted(s[0] for s in shares)
    median = nums[len(nums) // 2]
    for scale in (1, 0.1, 0.01):
        if 20 <= median * scale <= 200:
            return [round(s[0] * scale, 1) for s in shares]
    return None


def locate_building(creds, args, flat):
    """(building dict, method) or a candidates dict when the point is not exactly on one address."""
    if args.address:
        point = resolve_address(args.address)
        return {"address_point": point["address_point"], "address": args.address[:200]}, "address"
    if args.point:
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", args.point)
        if not m or not in_cz(float(m.group(1)), float(m.group(2))):
            raise Refusal("--point must be LAT,LON inside the Czech Republic. Nothing was read or changed.")
        lat, lon, method = float(m.group(1)), float(m.group(2)), "point"
    else:
        url = args.url or ((flat or {}).get("listing") or {}).get("url")
        stage("reading the map point from the listing page")
        found = listing_point(url) if url else None
        if not found:
            raise Refusal("no map point on the listing page. Pass --point LAT,LON or --address TEXT. "
                          "Nothing was billed or changed.")
        (lat, lon), method = found, "listing_point"
    stage("finding the RÚIAN address point")
    near = address_points_near(lat, lon)
    if near and near[0]["distance_m"] <= EXACT_METRES:
        return near[0], method
    return {"candidates": near[:8], "point": [round(lat, 6), round(lon, 6)]}, method


def locate_command(args, backend_loader=None):
    creds = require_live_credentials(["CUZK_API_KN_KEY"])
    flat = None
    if args.page:
        if backend_loader is None:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import call
            def backend_loader():
                cfg = call.load_config()
                return cfg, call.load_backend(cfg).module
        stage("reading the Notion page")
        cfg, backend = backend_loader()
        flat = backend.get_flat(cfg, args.page)
    building_point, method = locate_building(creds, args, flat)
    out = {"method": method, "billed": False}
    if "candidates" in building_point:
        out.update(status="building_not_identified", point=building_point["point"],
                   address_candidates=building_point["candidates"],
                   note="the map point is not on one address point (it may be the street's centre). Read the "
                        "listing and its photos, ask the user, then rerun with --address. Nothing was billed.")
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 2
    stage("reading the building and its units from API KN")
    key = creds["CUZK_API_KN_KEY"]
    building = api_kn("/Stavby/AdresniMisto/%d" % int(building_point["address_point"]), key)
    refs = (building.get("jednotky") or [])[:MAX_UNITS]
    units = []
    for ref in refs:
        u = api_kn("/Jednotky/%d" % int(ref["id"]), key)
        share = u.get("podilNaSpolecnychCastechDomu") or {}
        lv = u.get("lv") or {}
        units.append({"unit": unit_label(u.get("cisloJednotky")),
                      "use": str((u.get("zpusobVyuziti") or {}).get("nazev") or "")[:60],
                      "lv": safe(lv.get("cislo"), DIGITS_RE),
                      "area_code": safe((lv.get("katastralniUzemi") or {}).get("kod"), DIGITS_RE),
                      "share": (int(share["citatel"]), int(share["jmenovatel"]))
                      if share.get("citatel") and share.get("jmenovatel") else None,
                      "plomba": bool(u.get("rizeniPlomby"))})
    areas = areas_from_shares(units)
    for u, area in zip(units, areas or [None] * len(units)):
        u["area_m2_estimated"] = area
        u["share"] = "%d/%d" % u["share"] if u["share"] else None
    flats = [u for u in units if fold(u["use"]).startswith("byt")]
    ranked = []
    if args.area_m2 and areas:
        ranked = sorted(flats, key=lambda u: abs(u["area_m2_estimated"] - args.area_m2))[:5]
    lv = building.get("lv") or {}
    out.update(status="located", address=building_point.get("address"),
               distance_m=building_point.get("distance_m"),
               building={"iskn_id": safe(building.get("id"), DIGITS_RE),
                         "numbers": [safe(n, DIGITS_RE) for n in building.get("cislaDomovni") or []],
                         "use": str((building.get("zpusobVyuziti") or {}).get("nazev") or "")[:60],
                         "lv": safe(lv.get("cislo"), DIGITS_RE),
                         "area_code": safe((lv.get("katastralniUzemi") or {}).get("kod"), DIGITS_RE),
                         "area_name": str((lv.get("katastralniUzemi") or {}).get("nazev") or "")[:60],
                         "plomba": bool(building.get("rizeniPlomby"))},
               units=units, units_truncated=len(building.get("jednotky") or []) > MAX_UNITS,
               area_basis="share on the common parts" if areas else None,
               best_matches=[u["unit"] for u in ranked],
               lvs_of_best_matches=sorted({u["lv"] for u in ranked}),
               note="The land register has no floor or door. Pick the unit with the user (listing area, floor, "
                    "photos), then ask before ordering the LV: fetch --area CODE --lv N --confirm-billed "
                    "(%d CZK)." % BILLED_PRICE_CZK)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ fetch and attach

def inside_git_checkout(path):
    path = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def save_dir():
    """Where fetch saves: the LV folder (lv_dir), never one inside a git checkout."""
    folder = lv_dir()
    if inside_git_checkout(folder):
        raise Refusal("KATASTR_LV_DIR is inside a git checkout; LV files hold owner names and must stay out of "
                      "any repo. Nothing was billed or changed.")
    return folder


def fetch_command(args):
    creds = require_live_credentials(["WSDP_USERNAME", "WSDP_PASSWORD", "WSDP_ENV"])
    for value, name in ((args.area, "--area"), (args.lv, "--lv")):
        if not DIGITS_RE.fullmatch(value or ""):
            raise Refusal("%s must be digits. Nothing was billed or changed." % name)
    billed_gate(creds, args.confirm_billed, "fetch")
    folder = save_dir()
    os.makedirs(folder, mode=0o700, exist_ok=True)
    data, billing = fetch_lv(creds, args.area, args.lv, fmt=args.format)
    magic = b"%PDF" if args.format == "pdf" else b"<"
    if not data.lstrip()[:4].startswith(magic):
        raise KatastrError("WSDP returned a file that is not %s" % args.format.upper())
    day = (datetime.datetime.now(PRAGUE) if PRAGUE else datetime.datetime.now()).date().isoformat()
    base = os.path.join(folder, "LV_%s_%s_%s" % (args.area, args.lv, day))
    path, n = base + "." + args.format, 1
    while os.path.exists(path):
        n += 1
        path = "%s-%d.%s" % (base, n, args.format)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    out = {"status": "saved", "file": path, "format": args.format, "bytes": len(data), "lv": args.lv,
           "area_code": args.area, "wsdp_env": creds["WSDP_ENV"], "billing": billing}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


ATTACH_MARKER = "domovoy-katastr-file: %s"


def attach_command(args, backend_loader=None):
    path = args.file
    if not os.path.isfile(path):
        raise Refusal("the file does not exist. Nothing was changed.")
    with open(path, "rb") as f:
        if not f.read(5).startswith(b"%PDF"):
            raise Refusal("the file is not a PDF. Nothing was changed.")
    if backend_loader is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import call
        def backend_loader():
            cfg = call.load_config()
            return cfg, call.load_backend(cfg).module
    cfg, backend = backend_loader()
    if not hasattr(backend, "attach_file"):
        raise KatastrError("the shortlist backend cannot attach files (config backend.module)")
    stage("reading the Notion page")
    flat = backend.get_flat(cfg, args.page)
    name = os.path.basename(path)
    marker = ATTACH_MARKER % name
    out = {"page_id": safe(flat.get("id"), PAGE_ID_RE), "file": name}
    if marker in (flat.get("text") or "") and not args.force:
        out.update(status="already_attached", attached=False)
    else:
        stage("uploading the file to Notion")
        backend.attach_file(cfg, flat["id"], path, caption="LV extract (výpis z katastru nemovitostí): " + name,
                            marker=marker)
        out.update(status="attached", attached=True)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ commands

def lookup(args, backend_loader=None):
    cached = args.cached_lv
    creds = None
    stage("checking the inputs")
    if cached:
        if not os.path.isfile(cached):
            raise Refusal("the LV file does not exist. Nothing was read or changed.")
        stage("parsing the LV")
        parsed = parse_lv(cached)      # fail before touching Notion
    else:
        creds = require_live_credentials()
    if backend_loader is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import call
        def backend_loader():
            cfg = call.load_config()
            return cfg, call.load_backend(cfg).module
    stage("loading the config and the shortlist backend")
    cfg, backend = backend_loader()
    if not (hasattr(backend, "get_flat") and hasattr(backend, "append")):
        raise KatastrError("the shortlist backend needs get_flat and append (config backend.module)")
    stage("reading the Notion page")
    flat = backend.get_flat(cfg, args.page)
    answers = call_answers(flat.get("text"))
    number = args.unit or answers.get("unit")
    landlord = args.landlord or answers.get("landlord")
    floor, door = args.floor or answers.get("floor"), args.door or answers.get("door")
    out = {"page_id": safe(flat.get("id"), PAGE_ID_RE),
           "inputs": {"unit_number": bool(number), "floor_door": bool(floor or door),
                      "landlord_name": bool(landlord)}}
    extra_plomba, billing = [], None
    if cached:
        source = "cached_lv"
        source_line = ("Source: cached LV XML from a WSDP export issued %s (%s), not a live lookup. "
                       "The address was not checked against it."
                       % (parsed.get("issued") or "on an unknown date", "signed" if parsed["signed"] else "unsigned"))
    else:
        address = (flat.get("listing") or {}).get("address")
        if not address:
            raise Refusal("the page has no address. Nothing was billed or changed.")
        stage("resolving the address and the unit")
        found = locate_unit(creds, address, number)
        if "candidates" in found:
            out.update(status="unit_not_identified", unit_candidates=found["candidates"], billed=False,
                       note="pass --unit with one of the candidates; nothing was billed or changed")
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return 2
        billed_gate(creds, args.confirm_billed, "A live lookup")
        if found.get("lv_id"):
            data, billing = fetch_lv(creds, lv_id=found["lv_id"])
        else:
            data, billing = fetch_lv(creds, found["area_code"], found["lv_number"])
        stage("parsing the LV")
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
        out.update(status="already_checked", appended=False, result=public_result(result))
    else:
        lines = notion_section(result, parsed, owners, source_line) + [marker]
        stage("appending to the Notion page")
        backend.append(cfg, flat["id"], "\n".join(lines))
        out.update(status="appended", appended=True, result=public_result(result))
    if billing:
        out["billing"] = billing
    assert_redacted(out, private_tokens(parsed, landlord))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def parse_command(args):
    stage("parsing the LV")
    parsed = parse_lv(args.cached_lv)
    result, _, _ = assess(parsed, args.landlord, args.unit, args.floor, args.door)
    result["source"] = "cached_lv"
    out = {"status": "parsed", "result": public_result(result)}
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
            p.add_argument("--confirm-billed", action="store_true",
                           help="live lookup only: the user said yes to one billed LV output")
        p.add_argument("--cached-lv", required=(name == "parse"), help="an LV XML file (WSDP LV 1.0)")
        p.add_argument("--unit", help="unit number, e.g. 12 or 1800/12")
        p.add_argument("--floor")
        p.add_argument("--door")
        p.add_argument("--landlord", help="landlord name as said in the call (never printed)")
    p = sub.add_parser("locate")
    p.add_argument("--page", help="Notion page id of the flat (its listing URL gives the map point)")
    p.add_argument("--url", help="listing URL, instead of the page's")
    p.add_argument("--point", help="LAT,LON instead of the listing's map point")
    p.add_argument("--address", help="full address with the house number, instead of a point")
    p.add_argument("--area-m2", type=float, help="the listing's floor area, to rank the flats")
    p = sub.add_parser("fetch")
    p.add_argument("--area", required=True, help="cadastral area code (katastrální území), six digits")
    p.add_argument("--lv", required=True, help="LV number")
    p.add_argument("--format", choices=("xml", "pdf"), default="xml")
    p.add_argument("--confirm-billed", action="store_true", help="the user said yes to one billed output")
    p = sub.add_parser("attach")
    p.add_argument("--page", required=True, help="Notion page id of the flat")
    p.add_argument("--file", required=True, help="the LV PDF from fetch --format pdf")
    p.add_argument("--force", action="store_true", help="attach even if this file is already on the page")
    args = parser.parse_args(argv)
    commands = {"lookup": lambda: lookup(args, backend_loader), "parse": lambda: parse_command(args),
                "locate": lambda: locate_command(args, backend_loader), "fetch": lambda: fetch_command(args),
                "attach": lambda: attach_command(args, backend_loader)}
    try:
        if getattr(args, "cached_lv", None):
            args.cached_lv = resolve_lv(args.cached_lv)
        if getattr(args, "file", None):
            args.file = resolve_lv(args.file)
        return commands[args.command]()
    except Refusal as e:
        print(json.dumps({"refused": str(e)}, indent=2, ensure_ascii=False))
        return 2
    except KatastrError as e:
        print(json.dumps({"error": str(e), "stage": STAGE["now"]}, indent=2, ensure_ascii=False))
        return 1
    except Exception as e:  # noqa: BLE001 - any other failure: fixed text only, never the exception message
        print(json.dumps({"error": error_summary(e), "stage": STAGE["now"]}, indent=2, ensure_ascii=False))
        return 1


def error_summary(e):
    """A fixed description of an unexpected exception: its type if known, and an allowlisted Notion code."""
    kind = type(e).__name__
    text = "unexpected %s" % (kind if kind in SAFE_TYPES else "error")
    if kind == "NotionError":
        m = re.search(r"failed: ([a-z_]+|http_\d{3})\b", str(e))
        if m and (m.group(1) in NOTION_CODES or re.fullmatch(r"http_\d{3}", m.group(1))):
            text += " (Notion %s)" % m.group(1)
    return text


if __name__ == "__main__":
    sys.exit(main())
