"""Per-wording limits: policy.wording_uin picks <rules_dir>/<UIN>.json; uploads and unknown wordings use the
standard limits and say so."""

import asyncio
import json
from decimal import Decimal

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from engine import default_rules  # noqa: E402
from engine.dataset import load_case, load_letter  # noqa: E402
from mcp_server import create_server  # noqa: E402
from mcp_server.app import RulesProvider, default_rules_dir  # noqa: E402
from mcp_server.convert import case_payload, letter_payload  # noqa: E402

UIN = "GODHLIP24179V022324"


def call(server, tool, args):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def set01(dataset_dir, wording_uin="", source=""):
    case = case_payload(load_case("SET-01", dataset_dir))
    case["policy"].update(wording_uin=wording_uin, wording_source=source)
    return case


@pytest.fixture
def rules_dir(tmp_path):
    raw = json.loads((default_rules_dir() / f"{UIN}.json").read_text(encoding="utf-8"))
    (tmp_path / f"{UIN}.json").write_text(json.dumps(raw), encoding="utf-8")
    ten = {**raw, "copay_pct": 10}                                     # a made-up wording with a 10% co-pay
    (tmp_path / "TESTHLP00000V000001.json").write_text(json.dumps(ten), encoding="utf-8")
    return tmp_path


def test_the_go_digit_rules_file_has_the_checked_limits():
    raw = json.loads((default_rules_dir() / f"{UIN}.json").read_text(encoding="utf-8"))
    assert raw["room_rent_per_day"] == {"pct_of_sum_insured": 2, "max_inr": 5000}
    assert raw["cataract_per_eye"] == {"pct_of_sum_insured": 25, "max_inr": 40000} and raw["copay_pct"] == 5


def test_catalogue_wording_uses_its_own_rules(dataset_dir, rules_dir):
    srv = create_server(rules_dir=rules_dir)
    s = call(srv, "expected_settlement", {"case": set01(dataset_dir, "TESTHLP00000V000001", "catalogue")})
    assert s.structured_content["copay_amount"] == 10065.0 and s.structured_content["warnings"] == []
    s = call(srv, "expected_settlement", {"case": set01(dataset_dir, UIN, "catalogue")})
    assert s.structured_content["payable_amount"] == 95617.5


def test_uploaded_wording_uses_standard_rules_and_warns(dataset_dir, rules_dir):
    srv = create_server(rules_dir=rules_dir)
    case = set01(dataset_dir, "upload:doc_0123456789abcdef", "uploaded")
    s = call(srv, "expected_settlement", {"case": case}).structured_content
    assert s["payable_amount"] == 95617.5 and "Uploaded policy wording" in s["warnings"][-1]
    letter = letter_payload(load_letter("SET-01", dataset_dir))
    a = call(srv, "audit_settlement_letter", {"case": case, "letter": letter}).structured_content
    assert a["disputable_amount"] == 8522.86 and "Uploaded policy wording" in a["warnings"][-1]


def test_unknown_wording_warns(dataset_dir, rules_dir):
    s = call(create_server(rules_dir=rules_dir), "expected_settlement",
             {"case": set01(dataset_dir, "ZZZZZZZ00000V000000", "catalogue")}).structured_content
    assert "No reviewed limits" in s["warnings"][-1]


def test_no_wording_keeps_the_default_rules(dataset_dir, rules_dir):
    s = call(create_server(rules_dir=rules_dir), "expected_settlement", {"case": set01(dataset_dir)})
    assert s.structured_content["warnings"] == [] and s.structured_content["payable_amount"] == 95617.5


def test_fixed_rules_ignore_the_wording():
    rules = default_rules()
    p = RulesProvider(rules, fixed=True)
    assert p.for_policy("upload:doc_0123456789abcdef") == (rules, None)


@pytest.mark.parametrize("bad", ["godigit", "upload:../../etc", "GODHLIP24179V02232"])
def test_wording_uin_is_validated(dataset_dir, bad):
    r = call(create_server(default_rules()), "expected_settlement", {"case": set01(dataset_dir, bad)})
    assert r.is_error
