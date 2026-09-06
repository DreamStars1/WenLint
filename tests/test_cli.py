"""回归测试：CLI（exit code / fail-level / JSON）。"""
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


def test_json_output_shape(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("总而言之，方案。\n", encoding="utf-8")
    r = run_cli([str(p), "--json"])
    data = json.loads(r.stdout)
    assert data and data[0]["rule_id"] == "C001"
    assert data[0]["line"] == 1 and data[0]["col"] == 1


def test_fix_apply_creates_backup(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("总而言之，方案。\n", encoding="utf-8")
    r = run_cli([str(p), "--fix", "--apply"])
    assert r.returncode == 0
    assert "已写回" in r.stdout
    assert (tmp_path / "x.md.bak").exists()
    assert p.read_text(encoding="utf-8") == "方案。\n"
