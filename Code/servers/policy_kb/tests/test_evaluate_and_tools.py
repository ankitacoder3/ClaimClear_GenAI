import json

import pytest

from policy_kb.__main__ import main
from policy_kb.evaluate import Query, check_labels, compare, evaluate, format_table, load_queries
from policy_kb.tools import PolicyKBError, clauses_for_rule_result, get_clause_result, search_clauses_result

from conftest import SAMPLE, SAMPLE_QUERIES


# --- evaluation -----------------------------------------------------------------------------


def test_sample_queries_load_and_match_the_wording(kb):
    queries = load_queries(SAMPLE_QUERIES)
    assert len(queries) >= 30
    assert check_labels(kb, queries) == []


def test_metrics_on_a_tiny_set(kb):
    qs = [Query("a", "cataract limit per eye", ("4.3",)), Query("b", "zzz qqq", ("9.4",))]
    r = evaluate(kb, qs, k=5, config="t")
    assert r.queries == 2 and r.hit == 0.5 and r.misses == ["b"] and 0 < r.mrr <= 0.5


def test_label_errors_are_reported(kb):
    assert check_labels(kb, [Query("x", "q", ("5.2", "42.7"))]) == ["42.7"]


def test_queries_need_labels(tmp_path):
    p = tmp_path / "q.jsonl"
    p.write_text('{"id": "1", "query": "x", "relevant": []}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_queries(p)


def test_compare_grid_and_rewriting_effect(kb):
    rows = compare(kb, load_queries(SAMPLE_QUERIES))
    assert [r.config for r in rows] == ["bm25, no rewrite", "vector, no rewrite", "hybrid, no rewrite",
                                        "bm25, rewrite:glossary", "vector, rewrite:glossary", "hybrid, rewrite:glossary"]
    by = {r.config: r for r in rows}
    # On this synthetic set rewriting helps; real numbers come from Member 1's labels on the real wording.
    assert by["hybrid, rewrite:glossary"].recall >= by["hybrid, no rewrite"].recall
    assert "| Configuration | Recall@5 |" in format_table(rows)


# --- tool functions (no LangChain needed) ------------------------------------------------------


def test_search_clauses_result(kb):
    result = search_clauses_result(kb, "why did they cut my medicine bill", k=3)
    hits = result["hits"]
    assert len(hits) == 3 and hits[0]["clause_id"] == "5.2"
    assert hits[0]["citation"] == "Aarohan General Insurance Ltd. Arogya Sanjeevani Policy (SYNHLIP00000V000000), clause 5.2"
    assert result["synthetic"] is True and result["wording"]["uin"] == "SYNHLIP00000V000000"
    assert len(search_clauses_result(kb, "room", k=50)["hits"]) == 10         # capped
    with pytest.raises(PolicyKBError):
        search_clauses_result(kb, "   ")


def test_get_clause_result(kb):
    found = get_clause_result(kb, "5.2")
    assert found["found"] and found["title"] == "Items not reduced" and found["codes"] == []
    missing = get_clause_result(kb, "99")
    assert missing["found"] is False and missing["clause_id"] == "99" and missing["synthetic"] is True
    assert missing["citation"] is None and missing["text"] == ""


def test_clauses_for_rule_result(kb):
    with pytest.raises(PolicyKBError) as exc:
        clauses_for_rule_result(kb, "copay")                       # the synthetic wording has no rule map
    assert exc.value.code == "NO_RULE_MAP"


def test_langchain_tools(kb):
    pytest.importorskip("langchain_core")
    from policy_kb.tools import make_tools
    tools = make_tools(kb)
    assert set(tools) == {"search_clauses", "get_clause", "clauses_for_rule", "list_policies"}
    assert tools["get_clause"].invoke({"clause_id": "4.3"})["title"] == "Cataract treatment"
    assert tools["search_clauses"].invoke({"query": "complaint", "k": 2})["hits"][0]["clause_id"].startswith("10.")
    err = tools["clauses_for_rule"].invoke({"rule_ref": "copay"})       # same error text as an MCP tool
    assert err.startswith("Error executing tool clauses_for_rule: ") and '"code": "NO_RULE_MAP"' in err


# --- command line --------------------------------------------------------------------------------


def test_cli_build_search_clause_evaluate(tmp_path, capsys):
    idx = str(tmp_path / "idx.json")
    assert main(["--index", idx, "build", "--wording", str(SAMPLE), "--insurer", "Aarohan", "--uin", "SYN",
                 "--synthetic"]) == 0
    assert main(["--index", idx, "search", "cataract limit", "-k", "1", "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out[out.index("["):])[0]["clause_id"] == "4.3"
    assert main(["--index", idx, "clause", "5.2"]) == 0 and "Items not reduced" in capsys.readouterr().out
    assert main(["--index", idx, "clause", "88"]) == 1
    assert main(["--index", idx, "evaluate", str(SAMPLE_QUERIES)]) == 0
    assert "SYNTHETIC wording" in capsys.readouterr().out


def test_cli_build_reads_a_source_file(tmp_path, capsys):
    wording = tmp_path / "w.txt"
    wording.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "w.source.json").write_text(json.dumps({"insurer": "From Source", "uin": "SRC1",
                                                        "source_url": "https://example.invalid/w.pdf",
                                                        "downloaded_on": "2026-11-09"}), encoding="utf-8")
    idx = str(tmp_path / "idx.json")
    assert main(["--index", idx, "build", "--wording", str(wording)]) == 0
    from policy_kb import PolicyKB
    info = PolicyKB.load(idx).info
    assert (info.insurer, info.uin, info.source_url, info.synthetic) == ("From Source", "SRC1",
                                                                         "https://example.invalid/w.pdf", False)
    assert len(info.sha256) == 64
