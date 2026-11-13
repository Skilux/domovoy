"""Tests for scripts/katastr.py on the synthetic LV 1.0 fixtures in fixtures/katastr/.

Offline: RÚIAN, API KN, WSDP and Notion are all fakes. No real credentials are read (settings are patched),
and the billing counter lives in a temporary directory.
"""
import base64
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import katastr  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "katastr")
MORTGAGE = os.path.join(FIX, "lv_synth_mortgage.xml")
EASEMENT = os.path.join(FIX, "lv_synth_easement.xml")
SJM = os.path.join(FIX, "lv_synth_sjm.xml")
COMPANY = os.path.join(FIX, "lv_synth_company_plomba.xml")
BUILDING = os.path.join(FIX, "lv_synth_building_owner.xml")
PAGE = "cccccccc-0000-4000-8000-000000000003"
# Every invented person or company name in the fixtures. None of them may appear on stdout.
NAMES = ["Vzorová", "Jana", "Fiktivní Petr", "Petr", "Smyšlený", "Karel", "Smyšlená", "Eva", "Testovací nemovitosti",
         "Fiktivní banka", "Vzorový", "Tomáš", "Lenka", "Nájemná", "Alena", "Pokusný", "Ondřej"]
LIVE = {"CUZK_API_KN_KEY": "test-key", "WSDP_USERNAME": "test-user", "WSDP_PASSWORD": "test-pass",
        "WSDP_ENV": "prod", "WSDP_MAX_BILLED_PER_DAY": "10"}


def run(argv, backend=None):
    out = io.StringIO()
    loader = (lambda: ({}, backend)) if backend is not None else None
    with contextlib.redirect_stdout(out):
        code = katastr.main(argv, backend_loader=loader)
    return code, out.getvalue()


def leaked_names(text):
    printed = " " + " ".join(katastr.words(text)) + " "
    return [n for n in NAMES if " %s " % " ".join(katastr.words(n)) in printed]


class FakeBackend:
    def __init__(self, text="", address="Smyšlená 1, Fiktivní Město"):
        self.flat = {"id": PAGE, "title": "[TEST] katastr", "url": "https://www.notion.so/test",
                     "listing": {"address": address}, "text": text}
        self.calls = []

    def get_flat(self, cfg, flat_id):
        self.calls.append(("get_flat", flat_id))
        return dict(self.flat)

    def append(self, cfg, flat_id, text):
        self.calls.append(("append", flat_id, text))


class ParseTest(unittest.TestCase):
    def test_mortgage_case(self):
        result, owners, unit = katastr.assess(katastr.parse_lv(MORTGAGE))
        self.assertEqual(result["unit_type"], "flat")
        self.assertEqual(result["unit_number"], "101/12")
        self.assertEqual(result["unit_regime"], "apartment_act_72_1994")
        self.assertEqual(result["owner_types"], ["person"])
        self.assertEqual(result["owner_count"], 1)
        self.assertEqual([(r["section"], r["type"]) for r in result["restrictions"]],
                         [("C", "mortgage"), ("C", "ban_on_sale"), ("C", "easement"), ("C", "mortgage"), ("D", "other")])
        self.assertFalse(result["pending_change"])
        self.assertEqual(result["as_of"], "2026-11-01T00:00:00+01:00")
        self.assertEqual(result["lease_risk"], "medium")          # ban on sale + no landlord name

    def test_easement_only_with_matching_landlord_is_low_risk(self):
        result, _, _ = katastr.assess(katastr.parse_lv(EASEMENT), landlord="Petr Fiktivní")
        self.assertEqual([r["type"] for r in result["restrictions"] if r["section"] == "C"], ["easement"])
        self.assertEqual(result["landlord_matches_owner"], "yes")
        self.assertEqual(result["lease_risk"], "low")
        self.assertEqual(result["risk_reasons"], [])

    def test_sjm_flat_is_picked_among_non_flat_units(self):
        result, owners, _ = katastr.assess(katastr.parse_lv(SJM))
        self.assertEqual(result["owner_types"], ["sjm"])
        self.assertEqual(len(owners[0]["persons"]), 2)
        self.assertEqual(result["unit_number"], "101/5")
        self.assertIn("only flat", result["unit_note"])

    def test_sjm_unit_by_number(self):
        result, _, _ = katastr.assess(katastr.parse_lv(SJM), number="205")
        self.assertEqual(result["unit_number"], "101/205")
        self.assertEqual(result["unit_type"], "garage")

    def test_unknown_unit_number_lists_candidates(self):
        result, _, _ = katastr.assess(katastr.parse_lv(SJM), number="7")
        self.assertIsNone(result["unit_number"])
        self.assertEqual(result["unit_candidates"], ["101/5", "101/105", "101/205"])
        self.assertIn("the unit was not identified on the LV", result["risk_reasons"])

    def test_company_plomba_case_is_high_risk(self):
        result, _, _ = katastr.assess(katastr.parse_lv(COMPANY))
        self.assertEqual(result["owner_types"], ["company"])
        self.assertTrue(result["pending_change"])
        self.assertEqual(result["pending_proceedings"], ["V-1234/2026-999"])
        self.assertEqual(result["lease_risk"], "high")
        self.assertEqual({r["type"] for r in result["restrictions"] if r["section"] == "C"},
                         {"execution", "enforcement_lien"})

    def test_building_owner_ignores_nested_units_and_their_owners(self):
        parsed = katastr.parse_lv(BUILDING)
        self.assertEqual(parsed["units"], [])
        surnames = {p for o in parsed["owners"] for p, _ in o["persons"]}
        self.assertEqual(surnames, {"Vzorový", "Vzorová"})
        result, _, _ = katastr.assess(parsed)
        self.assertEqual(result["owner_count"], 2)
        self.assertEqual(result["owner_shares"], ["1/2", "1/2"])
        self.assertIsNone(result["unit_number"])

    def test_several_texty_blocks_are_all_read(self):
        with open(EASEMENT, encoding="utf-8") as f:
            xml = f.read()
        block = re.search(r"<TEXTY>.*</TEXTY>", xml, re.S).group(0)
        second = block.replace("101/12", "101/13").replace("800001", "800002")
        two = xml.replace(block, block + second)
        parsed = katastr.parse_lv(two.encode("utf-8"))
        self.assertEqual([u["label"] for u in parsed["units"]], ["101/12", "101/13"])

    def test_other_formats_are_rejected(self):
        with self.assertRaises(katastr.LVFormatError):
            katastr.parse_lv(b'<vypisZKatastruNemovitosti xmlns="urn:cz:gov:cuzk:iskn:sestavy:VypisZKatastru'
                             b'Nemovitosti:3.0"/>')
        with self.assertRaises(katastr.LVFormatError):
            katastr.parse_lv(b"<not-xml")


class CategoryTest(unittest.TestCase):
    def test_every_restriction_type(self):
        cases = {
            "Zástavní právo smluvní": "mortgage",
            "Podzástavní právo": "mortgage",
            "Zástavní právo exekutorské": "enforcement_lien",
            "Zástavní právo soudcovské": "enforcement_lien",
            "Zástavní právo zákonné": "enforcement_lien",
            "Exekuční příkaz k prodeji nemovitosti": "execution",
            "Nařízení exekuce": "execution",
            "Zahájení exekuce": "execution",
            "Insolvenční řízení": "insolvency",
            "Rozhodnutí o úpadku - insolvence": "insolvency",
            "Poznámka spornosti zápisu": "dispute",
            "Zákaz zcizení nebo zatížení": "ban_on_sale",
            "Zákaz zatížení": "ban_on_sale",
            "Předkupní právo": "pre_emption",
            "Věcné břemeno užívání": "easement",
            "Služebnost inženýrské sítě": "easement",
            "Nájem": "lease",
            "Pacht": "lease",
            "Vznik práva": "other",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(katastr.category_of(label), expected)


def person(prijmeni, jmeno, kind="person"):
    return {"kind": kind, "persons": [(prijmeni, jmeno)], "company": None, "ownership": True, "share": "1/1"}


class MatchTest(unittest.TestCase):
    def test_person(self):
        owner = person("Vzorová", "Jana")
        self.assertEqual(katastr.match_owner("Jana Vzorová", owner), "yes")
        self.assertEqual(katastr.match_owner("Ing. VZOROVA Jana, Ph.D.", owner), "yes")   # titles, case, accents
        self.assertEqual(katastr.match_owner("The owner is J. Vzorová", owner), "yes")      # surname + initial
        self.assertEqual(katastr.match_owner("Karel Vzorová", owner), "no")                 # wrong initial
        self.assertEqual(katastr.match_owner("Petr Fiktivní", owner), "no")
        self.assertEqual(katastr.match_owner("paní Vzorová", owner), "unknown")             # surname only
        self.assertEqual(katastr.match_owner("Fiktivní s.r.o.", owner), "no")               # company named

    def test_sjm_matches_either_spouse(self):
        owner = {"kind": "sjm", "persons": [("Smyšlený", "Karel"), ("Smyšlená", "Eva")], "company": None}
        self.assertEqual(katastr.match_owner("Karel Smyšlený", owner), "yes")
        self.assertEqual(katastr.match_owner("Eva Smyšlená", owner), "yes")
        self.assertEqual(katastr.match_owner("Ondřej Pokusný", owner), "no")

    def test_company_only_by_name(self):
        owner = {"kind": "company", "persons": [], "company": "Testovací nemovitosti s.r.o."}
        self.assertEqual(katastr.match_owner("Testovací nemovitosti, s. r. o.", owner), "yes")
        self.assertEqual(katastr.match_owner("Jiná firma a.s.", owner), "no")
        self.assertEqual(katastr.match_owner("Petr Fiktivní", owner), "unknown")   # a person may act for it

    def test_overall(self):
        owners = [person("Vzorová", "Jana"), person("Fiktivní", "Petr")]
        self.assertEqual(katastr.landlord_matches("Petr Fiktivní", owners), "yes")
        self.assertEqual(katastr.landlord_matches("Alena Nájemná", owners), "no")
        self.assertEqual(katastr.landlord_matches(None, owners), "unknown")
        self.assertEqual(katastr.landlord_matches("", owners), "unknown")


class RiskTest(unittest.TestCase):
    def parsed_with(self, owners):
        parsed = katastr.parse_lv(EASEMENT)
        parsed["owners"] = owners
        return parsed

    def test_coop_owner_is_a_sublease_risk(self):
        coop = {"kind": "cooperative", "persons": [], "company": "Bytové družstvo Fiktivní", "ownership": True,
                "share": "1/1", "relation": "Vlastnické právo"}
        self.assertEqual(katastr.subject_of(None), None)
        result, _, _ = katastr.assess(self.parsed_with([coop]), landlord="Petr Fiktivní")
        self.assertEqual(result["owner_types"], ["cooperative"])
        self.assertEqual(result["lease_risk"], "medium")
        self.assertTrue(any("co-op" in r and "sublease" in r for r in result["risk_reasons"]))

    def test_coop_detected_from_name(self):
        with open(COMPANY, encoding="utf-8") as f:
            xml = f.read().replace("Testovací nemovitosti s.r.o.", "Stavební bytové družstvo Fiktivní")
        result, _, _ = katastr.assess(katastr.parse_lv(xml.encode("utf-8")))
        self.assertEqual(result["owner_types"], ["cooperative"])

    def test_company_owner_is_a_sublease_risk(self):
        result, _, _ = katastr.assess(katastr.parse_lv(COMPANY))
        self.assertTrue(any("company owns" in r and "sublease" in r for r in result["risk_reasons"]))

    def test_landlord_not_owner_is_high(self):
        result, _, _ = katastr.assess(katastr.parse_lv(EASEMENT), landlord="Alena Nájemná")
        self.assertEqual(result["landlord_matches_owner"], "no")
        self.assertEqual(result["lease_risk"], "high")

    def test_many_co_owners_is_medium(self):
        owners = [dict(person("Vzorová", "Jana"), share="1/3") for _ in range(3)]
        result, _, _ = katastr.assess(self.parsed_with(owners), landlord="Jana Vzorová")
        self.assertEqual(result["lease_risk"], "medium")
        self.assertTrue(any("3 co-owners" in r for r in result["risk_reasons"]))


class BillingTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "katastr_billed.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_eleventh_billed_call_is_refused(self):
        for i in range(10):
            self.assertEqual(katastr.billing_guard(LIVE, self.path, "2026-11-13")["billed_today"], i + 1)
        with self.assertRaises(katastr.Refusal):
            katastr.billing_guard(LIVE, self.path, "2026-11-13")
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"2026-11-13": 10})
        self.assertEqual(katastr.billing_guard(LIVE, self.path, "2026-11-14")["billed_today"], 1)

    def test_cap_never_exceeds_ten(self):
        creds = dict(LIVE, WSDP_MAX_BILLED_PER_DAY="50")
        for _ in range(10):
            katastr.billing_guard(creds, self.path, "2026-11-13")
        with self.assertRaises(katastr.Refusal):
            katastr.billing_guard(creds, self.path, "2026-11-13")

    def test_lower_cap_and_trial(self):
        creds = dict(LIVE, WSDP_MAX_BILLED_PER_DAY="2")
        katastr.billing_guard(creds, self.path, "2026-11-13")
        katastr.billing_guard(creds, self.path, "2026-11-13")
        with self.assertRaises(katastr.Refusal):
            katastr.billing_guard(creds, self.path, "2026-11-13")
        other = os.path.join(self.dir.name, "trial.json")
        self.assertIsNone(katastr.billing_guard(dict(LIVE, WSDP_ENV="trial"), other, "2026-11-13"))
        self.assertFalse(os.path.exists(other))


class CallAnswersTest(unittest.TestCase):
    def test_answers_from_call_result(self):
        text = "\n".join([
            "Call result: Viewing booked",
            "- Asked: What is the unit number of the flat? Answer: It is unit 1800/12.",
            "- Asked: Which floor is it on? Answer: Third floor, 3",
            "- Asked: Which door? Answer: left door",
            "- Asked: What is the owner's name? Answer: The owner is Jana Vzorová.",
            "- Asked: Is there a cellar? Answer: unknown",
        ])
        found = katastr.call_answers(text)
        self.assertEqual(found["unit"], "1800/12")
        self.assertEqual(found["floor"], "3")
        self.assertEqual(found["door"], "left door")
        self.assertEqual(found["landlord"], "The owner is Jana Vzorová.")

    def test_unknown_answers_are_skipped(self):
        found = katastr.call_answers("- Asked: Who is the landlord? Answer: I don't know")
        self.assertEqual(found, {})


class CachedLookupTest(unittest.TestCase):
    def test_lookup_appends_names_to_notion_only(self):
        text = "- Asked: What is the landlord's name? Answer: Ing. Jana Vzorová"
        backend = FakeBackend(text)
        code, out = run(["lookup", "--page", PAGE, "--cached-lv", MORTGAGE], backend)
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        self.assertEqual(data["status"], "appended")
        self.assertEqual(data["result"]["source"], "cached_lv")
        self.assertEqual(data["result"]["landlord_matches_owner"], "yes")
        self.assertEqual(leaked_names(out), [])
        appended = [c for c in backend.calls if c[0] == "append"]
        self.assertEqual(len(appended), 1)
        section = appended[0][2]
        self.assertTrue(section.startswith("Katastr check\nSource: cached LV XML"))
        self.assertIn("Jana Vzorová", section)             # owner names live in Notion
        self.assertIn("Fiktivní banka, a.s.", section)     # and the mortgage holder
        self.assertIn("domovoy-katastr: cached_lv 90001", section)

    def test_second_lookup_does_not_append_again(self):
        backend = FakeBackend()
        run(["lookup", "--page", PAGE, "--cached-lv", EASEMENT], backend)
        backend.flat["text"] = backend.calls[-1][2]
        code, out = run(["lookup", "--page", PAGE, "--cached-lv", EASEMENT], backend)
        self.assertEqual(json.loads(out)["status"], "already_checked")
        self.assertEqual(len([c for c in backend.calls if c[0] == "append"]), 1)

    def test_no_names_on_stdout_for_any_fixture(self):
        for path in (MORTGAGE, EASEMENT, SJM, COMPANY, BUILDING):
            for landlord in (None, "Karel Smyšlený", "Testovací nemovitosti s.r.o."):
                argv = ["parse", "--cached-lv", path] + (["--landlord", landlord] if landlord else [])
                code, out = run(argv)
                with self.subTest(path=os.path.basename(path), landlord=landlord):
                    self.assertEqual(code, 0, out)
                    self.assertEqual(leaked_names(out), [])

    def test_redaction_check_stops_a_leak(self):
        parsed = katastr.parse_lv(MORTGAGE)
        with self.assertRaises(RuntimeError):
            katastr.assert_redacted({"note": "owner Jana Vzorová"}, katastr.private_tokens(parsed, None))
        with self.assertRaises(RuntimeError):
            katastr.assert_redacted({"note": "Fiktivní banka"}, katastr.private_tokens(parsed, None))

    def test_missing_lv_file_touches_nothing(self):
        backend = FakeBackend()
        code, out = run(["lookup", "--page", PAGE, "--cached-lv", os.path.join(FIX, "nope.xml")], backend)
        self.assertEqual(code, 2)
        self.assertEqual(backend.calls, [])


def soap(body):
    return ('<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body><r xmlns="urn:x">'
            '<zprava kod="0" uroven="INFORMACE">ok</zprava>%s</r></S:Body></S:Envelope>' % body).encode("utf-8")


class LiveLookupTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(katastr, "settings", lambda names: {n: LIVE.get(n, "") for n in names}),
            mock.patch.object(katastr, "BILLING_FILE", os.path.join(self.dir.name, "billed.json")),
            mock.patch.object(katastr, "REPORT_POLL_SECONDS", 0),
            mock.patch.object(katastr, "resolve_address", lambda a: {"address_point": 1, "building_code": 2}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)
        self.wsdp_ops = []

    def fake_api_kn(self, units):
        def api(path, key):
            if path.startswith("/Stavby/"):
                return {"id": 9, "jednotky": [{"id": 100 + n, "cisloJednotky": n} for n in units],
                        "rizeniPlomby": [], "lv": {"cislo": 5, "katastralniUzemi": {"kod": 999901}}}
            return {"cisloJednotky": 12, "rizeniPlomby": [{"typRizeni": "V", "poradoveCislo": 77, "rok": 2026,
                                                           "kodPracoviste": 101}],
                    "lv": {"cislo": 90001, "katastralniUzemi": {"kod": 999901}}}
        return api

    def fake_wsdp(self, creds, service, operation, body):
        self.wsdp_ops.append(operation)
        if operation == "generujLVZjednodusene":
            return soap("<reportList><report><id>42</id><stav>čeká</stav></report></reportList>")
        if operation == "seznamSestav":
            return soap("<reportList><report><id>42</id><stav>zpracován</stav></report></reportList>")
        if operation == "vratSestavu":
            with open(MORTGAGE, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            return soap("<reportList><report><id>42</id><souborSestavy>%s</souborSestavy></report></reportList>" % data)
        return soap("")

    def test_live_lookup_bills_once_and_appends(self):
        backend = FakeBackend("- Asked: What is the unit number? Answer: 12")
        with mock.patch.object(katastr, "api_kn", self.fake_api_kn([11, 12])), \
                mock.patch.object(katastr, "wsdp_call", self.fake_wsdp):
            code, out = run(["lookup", "--page", PAGE], backend)
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        self.assertEqual(data["result"]["source"], "wsdp")
        self.assertEqual(data["billing"], {"billed_today": 1, "cap": 10})
        self.assertEqual(self.wsdp_ops, ["generujLVZjednodusene", "seznamSestav", "vratSestavu", "smazSestavu"])
        self.assertTrue(data["result"]["pending_change"])            # plomba from API KN
        self.assertIn("V-77/2026-101", data["result"]["pending_proceedings"])
        self.assertEqual(leaked_names(out), [])
        self.assertIn("Source: live WSDP LV extract", backend.calls[-1][2])

    def test_ambiguous_unit_bills_nothing(self):
        backend = FakeBackend()
        with mock.patch.object(katastr, "api_kn", self.fake_api_kn([11, 12])), \
                mock.patch.object(katastr, "wsdp_call", self.fake_wsdp):
            code, out = run(["lookup", "--page", PAGE], backend)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["unit_candidates"], ["11", "12"])
        self.assertEqual(self.wsdp_ops, [])
        self.assertFalse([c for c in backend.calls if c[0] == "append"])
        self.assertFalse(os.path.exists(katastr.BILLING_FILE))

    def test_cap_reached_refuses_before_wsdp(self):
        with open(katastr.BILLING_FILE, "w") as f:
            json.dump({katastr.datetime.datetime.now(katastr.PRAGUE).date().isoformat(): 10}, f)
        backend = FakeBackend("- Asked: What is the unit number? Answer: 12")
        with mock.patch.object(katastr, "api_kn", self.fake_api_kn([11, 12])), \
                mock.patch.object(katastr, "wsdp_call", self.fake_wsdp):
            code, out = run(["lookup", "--page", PAGE], backend)
        self.assertEqual(code, 2)
        self.assertIn("10 of 10", json.loads(out)["refused"])
        self.assertEqual(self.wsdp_ops, [])


class CredentialsTest(unittest.TestCase):
    def test_missing_credentials_touch_nothing(self):
        def boom(*args, **kwargs):
            raise AssertionError("network used")
        loaded = []
        with mock.patch.object(katastr, "settings", lambda names: {n: "" for n in names}), \
                mock.patch.object(katastr.urllib.request, "urlopen", boom), \
                mock.patch.object(katastr.subprocess, "run", boom):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = katastr.main(["lookup", "--page", PAGE], backend_loader=lambda: loaded.append(1))
        self.assertEqual(code, 2)
        message = json.loads(out.getvalue())["refused"]
        for name in ("CUZK_API_KN_KEY", "WSDP_USERNAME", "WSDP_PASSWORD", "WSDP_ENV"):
            self.assertIn(name, message)
        self.assertIn("Nothing was read or changed", message)
        self.assertEqual(loaded, [])

    def test_one_missing_credential_is_named(self):
        with mock.patch.object(katastr, "settings", lambda names: {n: LIVE.get(n, "") if n != "WSDP_PASSWORD" else ""
                                                                     for n in names}):
            with self.assertRaises(katastr.Refusal) as e:
                katastr.require_live_credentials()
        self.assertIn("WSDP_PASSWORD", str(e.exception))
        self.assertNotIn("CUZK_API_KN_KEY", str(e.exception))


if __name__ == "__main__":
    unittest.main()
