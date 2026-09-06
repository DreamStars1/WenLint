"""回归测试：CLI（exit code / fail-level / JSON schema）。"""
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")


def run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "wenlint.cli"] + args,
        capture_output=True, text=True,
        cwd=cwd or ROOT,
    )


def test_clean_file_exit_zero():
    r = run_cli(["tests/fixtures/smoke.md"])
    assert r.returncode == 0


def test_fail_level_warning_exits_1(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("总而言之，套话在这里。\n", encoding="utf-8")
    r = run_cli([str(p), "--fail-level", "warning"])
    assert r.returncode == 1
    assert "C001" in r.stdout


def test_fail_level_error_ignores_warning(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("总而言之，套话在这里。\n", encoding="utf-8")
    r = run_cli([str(p), "--fail-level", "error"])
    assert r.returncode == 0, "只有 warning 不应触发 error 级失败"


def test_json_schema_has_review_fields(tmp_path):
    """JSON 输出须含 Skill 消费所需字段：rule/type/column/text/sentence/review_hint。"""
    p = tmp_path / "x.md"
    p.write_text("系统目前可能支持 Excel 批量导入。\n", encoding="utf-8")
    r = run_cli([str(p), "--json"])
    data = json.loads(r.stdout)
    assert data, "应有命中"
    f = data[0]
    assert f["rule"] == "H002"
    assert f["type"] == "candidate"          # semantic 规则 → candidate
    assert "column" in f and f["column"] >= 1
    assert f["text"] == "可能"
    assert "可能" in f["sentence"]            # 命中句包含命中词
    assert f["review_hint"], "应携带规则审查提示"
    assert "replacement" not in f, "WenLint 不输出替换建议（不负责 fix）"


def test_json_lint_rule_type(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("总而言之，方案。\n", encoding="utf-8")
    r = run_cli([str(p), "--json"])
    data = json.loads(r.stdout)
    assert data[0]["rule"] == "C001"
    assert data[0]["type"] == "lint"


def test_no_fix_flag(tmp_path):
    """v0.1 定案：WenLint 不提供 --fix/--apply（fix 归 Skill 的 LLM）。"""
    p = tmp_path / "x.md"
    p.write_text("总而言之，方案。\n", encoding="utf-8")
    r = run_cli([str(p), "--fix"])
    assert r.returncode == 2, "未知参数应报错退出"
