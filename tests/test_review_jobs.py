import threading
import time

from wenlint.desktop import DesktopApi


def test_start_returns_before_model_and_cancel_is_immediate(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    api = DesktopApi()

    def slow_review(payload, **kwargs):
        entered.set()
        release.wait(2)
        return {"ok": True, "summary": "late"}

    monkeypatch.setattr(api, "agent_review", slow_review)
    started = time.perf_counter()
    job = api.start_agent_review({"text": "测试正文"})
    try:
        assert time.perf_counter() - started < 0.2
        assert entered.wait(0.5)
        status = api.agent_review_status({"job_id": job["job_id"]})
        assert status["state"] == "running"
        assert status["events"][0]["elapsed_ms"] < 200
        assert api.cancel_agent_review({"job_id": job["job_id"]})["ok"]
        assert api.agent_review_status({"job_id": job["job_id"]})["state"] == "cancelled"
        replacement = api.start_agent_review({"text": "再次审查"})
        assert replacement['ok']
        assert replacement['job_id'] != job['job_id']
        api.cancel_agent_review({'job_id': replacement['job_id']})
        assert not api.start_agent_review({'text': '限制挂起任务'})['ok']
    finally:
        release.set()


def test_demo_runs_without_credentials_and_reports_zero_model_calls():
    api = DesktopApi()
    job = api.start_agent_review({"demo": True, "text": "总而言之，我们对方案进行分析。"})
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = api.agent_review_status({"job_id": job["job_id"]})
        if status["state"] != "running":
            break
        time.sleep(0.02)
    assert status["state"] == "complete"
    assert status["result"]["modelCalls"] == 0
    assert status["result"]["decisions"]
    assert status['result']['semanticIssueCount'] == 0
    assert all(item['origin'] == 'demo' for item in status['result']['decisions'])
    assert any(event["kind"] == "tool_result" for event in status["events"])


def test_cancelled_demo_without_matches_does_not_succeed():
    from wenlint.offline_demo import review_demo
    cancel = threading.Event()
    cancel.set()
    assert not review_demo('无演示样例', 'general', 'x.md', cancel=cancel)['ok']
