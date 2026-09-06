"""回归测试：CLI（exit code / fail-level / JSON schema）。"""
import json
import os
import subprocess
import sys

from wenlint.cli import main

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_local_cli_still_accepts_path_named_feishu(tmp_path, monkeypatch):
    target = tmp_path / "feishu"
    target.write_text("这是普通正文。", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["feishu"]) == 0


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


def test_wenlintignore_trailing_slash_works(tmp_path, monkeypatch):
    """.wenlintignore 的 tests/ 目录语义应排除 tests/fixtures/*.md"""
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "smoke.md").write_text(
        "总而言之，故意坏味。\n", encoding="utf-8")
    (tmp_path / "doc.md").write_text("正文没问题。\n", encoding="utf-8")
    (tmp_path / ".wenlintignore").write_text("tests/\n", encoding="utf-8")
    r = run_cli(["--json", str(tmp_path)])
    data = json.loads(r.stdout)
    assert all("tests/" not in d["file"] for d in data), \
        "tests/ 目录应被忽略"


def test_wenlintignore_relative_to_project_root(tmp_path):
    """.wenlintignore 相对项目根加载（从其他 cwd 运行也生效）"""
    proj = tmp_path / "proj"
    (proj / "sub").mkdir(parents=True)
    (proj / "sub" / "x.md").write_text("总而言之。\n", encoding="utf-8")
    (proj / "doc.md").write_text("正文没问题。\n", encoding="utf-8")
    (proj / ".wenlintignore").write_text("sub/\n", encoding="utf-8")
    r = run_cli(["--json", str(proj)], cwd=ROOT)
    data = json.loads(r.stdout)
    assert data == [] or all("sub/" not in d["file"] for d in data), \
        "sub/ 应被忽略（相对项目根），doc.md 可保留"


def test_cliche_in_fenced_code_comment_ok(tmp_path):
    """代码块内的 <!-- 不破坏注释状态机（后续正文照常检查）"""
    p = tmp_path / "x.md"
    p.write_text("```html\n<!-- 示例代码\n```\n正文总而言之，很重要。\n",
                 encoding="utf-8")
    r = run_cli([str(p), "--json"])
    data = json.loads(r.stdout)
    assert any("C001" in d["rule"] for d in data), "代码块后的正文应被检查"


def test_inline_code_comment_marker_ok(tmp_path):
    """行内代码 `<!--` 不触发注释状态（后半句照常检查）"""
    p = tmp_path / "x.md"
    p.write_text("正文用 `<!--` 表示注释，总而言之，后面该查。\n",
                 encoding="utf-8")
    r = run_cli([str(p), "--json"])
    data = json.loads(r.stdout)
    assert any("C001" in d["rule"] for d in data), "行内代码后的正文应被检查"
