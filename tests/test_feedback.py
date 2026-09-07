"""本地四分类反馈记录 CLI 回归测试。"""

import json

from wenlint.feedback import main


def test_record_appends_local_jsonl(tmp_path, capsys):
    output = tmp_path / "feedback" / "records.jsonl"

    code = main([
        "record", "--decision", "KEEP", "--rule", "H002",
        "--file", "docs/prd.md", "--line", "18", "--column", "7",
        "--text", "可能", "--reason", "属于合理的学术审慎",
        "--profile", "academic", "--output", str(output),
    ])

    assert code == 0
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["schema_version"] == 1
    assert records[0]["decision"] == "KEEP"
    assert records[0]["rule"] == "H002"
    assert records[0]["file"] == "docs/prd.md"
    assert records[0]["line"] == 18
    assert records[0]["column"] == 7
    assert records[0]["text"] == "可能"
    assert records[0]["reason"] == "属于合理的学术审慎"
    assert records[0]["profile"] == "academic"
    assert records[0]["recorded_at"].endswith("Z")
    assert json.loads(capsys.readouterr().out)["output"] == str(output)


def test_stats_reports_decisions_and_keep_rate(tmp_path, capsys):
    output = tmp_path / "records.jsonl"
    common = ["--rule", "H002", "--file", "prd.md", "--line", "1",
              "--column", "1", "--output", str(output)]
    assert main(["record", "--decision", "KEEP", *common]) == 0
    assert main(["record", "--decision", "REWRITE", *common]) == 0
    capsys.readouterr()

    assert main(["stats", "--input", str(output), "--json"]) == 0

    stats = json.loads(capsys.readouterr().out)
    assert stats["total"] == 2
    assert stats["by_rule"]["H002"] == {
        "total": 2,
        "decisions": {"KEEP": 1, "REWRITE": 1, "VERIFY": 0, "ASK": 0},
        "keep_rate": 0.5,
    }


def test_record_rejects_unknown_decision(tmp_path):
    code = main([
        "record", "--decision", "DROP", "--rule", "H002",
        "--file", "prd.md", "--line", "1", "--column", "1",
        "--output", str(tmp_path / "records.jsonl"),
    ])
    assert code == 2


def test_record_rejects_blank_required_string(tmp_path, capsys):
    code = main([
        "record", "--decision", "KEEP", "--rule", " ",
        "--file", "prd.md", "--line", "1", "--column", "1",
        "--output", str(tmp_path / "records.jsonl"),
    ])

    assert code == 2
    assert "rule 必须是非空字符串" in capsys.readouterr().err


def test_stats_rejects_malformed_json_instead_of_silently_undercounting(
        tmp_path, capsys):
    output = tmp_path / "records.jsonl"
    valid = {
        "schema_version": 1,
        "decision": "KEEP",
        "rule": "H002",
        "file": "prd.md",
        "line": 1,
        "column": 1,
        "text": "可能",
        "reason": "合理审慎",
        "profile": "general",
        "recorded_at": "2026-09-07T00:00:00Z",
    }
    output.write_text(json.dumps(valid, ensure_ascii=False) + "\nnot-json\n",
                      encoding="utf-8")

    assert main(["stats", "--input", str(output), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{output}:2" in captured.err
    assert "JSON 无效" in captured.err


def test_stats_rejects_non_object_json(tmp_path, capsys):
    output = tmp_path / "records.jsonl"
    output.write_text("[]\n", encoding="utf-8")

    assert main(["stats", "--input", str(output), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "JSON 行必须是对象" in captured.err
