"""Offline protocol checks for streamed review and bounded evidence lookup."""

from __future__ import annotations

import io
import json
import threading
import socket
import time
from types import SimpleNamespace

import pytest

from wenlint.agent import (
    AgentCancelledError, AgentConfig, AgentConnectionError, AgentProtocolError, OpenAICompatibleAgent,
)
from wenlint.workspace import WorkspaceSession
from wenlint.workspace_agent import WorkspaceAgentAccess


class Response(io.BytesIO):
    def __init__(self, data: bytes, content_type: str = "text/event-stream"):
        super().__init__(data)
        self.headers = {"Content-Type": content_type}


def event(delta: dict, finish=None) -> bytes:
    return ("data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}, ensure_ascii=False) + "\n\n").encode()


def final_stream() -> bytes:
    return event({"content": '{"summary":"已完成","decisions":[]}'}, "stop") + b"data: [DONE]\n\n"


def client(opener, base="https://api.example.com/v1", model="review-model"):
    return OpenAICompatibleAgent(AgentConfig(base, "private-key", model), opener=opener)


def access_for(tmp_path):
    (tmp_path / "draft.md").write_text("文档正文。", encoding="utf-8")
    (tmp_path / "facts.md").write_text("产品上线日期：五月一日。", encoding="utf-8")
    return WorkspaceAgentAccess(WorkspaceSession(tmp_path), "draft.md")


def test_stream_progress_is_incremental_and_never_exposes_reasoning():
    events = []
    first_seen = threading.Event()

    class Observed(Response):
        def readline(self, size=-1):
            if self.tell() >= prefix_size:
                assert first_seen.is_set(), "progress must arrive before the final JSON"
            return super().readline(size)

    prefix = event({"reasoning_content": "PRIVATE CHAIN"}) + event({"content": '{"summary":'})
    prefix_size = len(prefix)

    def opener(request, *, timeout):
        assert json.loads(request.data)["stream"] is True
        assert timeout <= 15
        return Observed(prefix + event({"content": '"已完成","decisions":[]}'}, "stop") + b"data: [DONE]\n\n")

    def receive(item):
        events.append(item)
        if item.get("output_chars"):
            first_seen.set()

    result = client(opener).review("文档正文。", on_event=receive)
    assert result.model_calls == 1
    assert "PRIVATE CHAIN" not in json.dumps(events)
    assert {item["kind"] for item in events} >= {"plan", "progress", "lane_complete"}


def test_stream_request_accepts_provider_json_fallback():
    def opener(request, *, timeout):
        body = {"choices": [{"message": {"content": '{"summary":"已完成","decisions":[]}'}}]}
        return Response(json.dumps(body).encode(), "application/json")
    assert client(opener).review("文档正文。", on_event=lambda _: None).model_calls == 1


@pytest.mark.parametrize("data", [
    b"data: not-json\n\n", event({"content": "partial"}),
    event({"content": "partial"}, "length"),
    b'data: {"choices":null}\n\n',
])
def test_invalid_or_truncated_stream_is_rejected(data):
    with pytest.raises(AgentProtocolError):
        client(lambda *args, **kwargs: Response(data)).review("文档正文。", on_event=lambda _: None)


def test_split_tool_arguments_are_assembled_and_evidence_is_returned(tmp_path):
    access = access_for(tmp_path)
    requests = []
    events = []

    def opener(request, *, timeout):
        payload = json.loads(request.data)
        requests.append(payload)
        if len(requests) == 1:
            return Response(
                event({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "read_workspace_file", "arguments": '{"path":'}}]})
                + event({"tool_calls": [{"index": 0, "function": {"arguments": '"facts.md"}'}}]}, "tool_calls")
                + b"data: [DONE]\n\n"
            )
        assert payload["messages"][-1]["role"] == "tool"
        assert "五月一日" in payload["messages"][-1]["content"]
        return Response(final_stream())

    result = client(opener).review("文档正文。", workspace_access=access, on_event=events.append)
    assert result.model_calls == 2
    assert access.files_read == ("facts.md",)
    assert [item["kind"] for item in events].count("tool_result") == 1


def test_tool_rounds_and_total_calls_are_bounded(tmp_path):
    access = access_for(tmp_path)
    requests = []
    events = []

    def opener(request, *, timeout):
        payload = json.loads(request.data)
        requests.append(payload)
        if "tools" not in payload:
            return Response(final_stream())
        calls = [{"index": index, "id": f"round{len(requests)}_{index}", "function": {"name": "list_workspace_files", "arguments": "{}"}} for index in range(3)]
        return Response(event({"tool_calls": calls}, "tool_calls") + b"data: [DONE]\n\n")

    result = client(opener).review("文档正文。", workspace_access=access, on_event=events.append)
    assert result.model_calls == 4
    assert len([item for item in events if item["kind"] == "tool_start"]) == 8
    assert "tools" not in requests[-1]
    assert "reasoning_content" not in json.dumps(requests)


def test_cancel_before_tool_start_prevents_tools_and_followup_model(tmp_path):
    access = access_for(tmp_path)
    cancelled = threading.Event()
    calls = []

    def opener(request, *, timeout):
        calls.append(request)
        return Response(event({"tool_calls": [{"index": 0, "id": "id1", "function": {"name": "read_workspace_file", "arguments": '{"path":"facts.md"}'}}]}, "tool_calls") + b"data: [DONE]\n\n")

    def receive(item):
        if item["kind"] == "tool_start":
            cancelled.set()

    with pytest.raises(AgentCancelledError):
        client(opener).review("文档正文。", workspace_access=access, on_event=receive, cancel_event=cancelled)
    assert len(calls) == 1
    assert access.files_read == ()


def test_already_cancelled_review_does_not_call_provider():
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(AgentCancelledError):
        client(lambda *args, **kwargs: pytest.fail("provider should not run")).review("文档正文。", cancel_event=cancelled)


def test_cancellation_interrupts_a_blocked_stream_socket():
    cancelled = threading.Event()
    connected, provider = socket.socketpair()
    connected.settimeout(5)
    errors = []

    class SocketResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self):
            self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=connected))
            self.reader = connected.makefile("rb")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.reader.close()

        def readline(self, size):
            return self.reader.readline(size)

    def run():
        try:
            client(lambda *args, **kwargs: SocketResponse()).review("文档正文。", on_event=lambda _: None, cancel_event=cancelled)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    try:
        worker.start()
        time.sleep(0.05)
        cancelled.set()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], AgentCancelledError)
    finally:
        provider.close()
        connected.close()
        worker.join(timeout=2)


def test_json_fallback_obeys_hard_deadline_during_blocked_read(monkeypatch):
    monkeypatch.setattr("wenlint.agent.MAX_REVIEW_SECONDS", 0.1)
    released = threading.Event()

    class BlockedJson(Response):
        def read(self, size=-1):
            assert size == 4 * 1024 * 1024 + 1
            released.wait(2)
            return super().read(size)

    start = time.monotonic()
    try:
        with pytest.raises(AgentConnectionError, match="时间上限"):
            client(lambda *args, **kwargs: BlockedJson(b"{}", "application/json")).review("文档正文。", on_event=lambda _: None)
        assert time.monotonic() - start < 0.5
    finally:
        released.set()


def test_static_overlapping_rewrites_become_reviewable_questions():
    source = "总而言之，我们对方案进行分析。"

    def opener(request, *, timeout):
        task = json.loads(json.loads(request.data)["messages"][1]["content"].split("\n", 1)[1])
        decisions = []
        if task["review_lane"] == "static":
            assert len(task["static_findings"]) >= 2
            for index, finding in enumerate(task["static_findings"], 1):
                decisions.append({"finding_index": index, "rule": finding["rule_id"], "action": "REWRITE", "reason": "简化句子。", "before": source, "after": "我们分析方案。"})
        return Response(event({"content": json.dumps({"summary": "已完成", "decisions": decisions}, ensure_ascii=False)}, "stop") + b"data: [DONE]\n\n")

    result = client(opener).review(source, on_event=lambda _: None)
    assert result.revised_text == "我们分析方案。"
    assert result.decisions[0].action == "REWRITE"
    assert all(item.action == "ASK" for item in result.decisions[1:])
    assert result.decisions[1].finding_index == 2


@pytest.mark.parametrize("base,model,disabled", [
    ("https://api.deepseek.com", "deepseek-v4-flash", True),
    ("https://api.deepseek.com/v1", "deepseek-v4-pro", True),
    ("https://api.example.com", "deepseek-v4-flash", False),
    ("https://api.deepseek.com", "other-model", False),
])
def test_deepseek_latency_option_is_host_and_model_specific(base, model, disabled):
    def opener(request, *, timeout):
        payload = json.loads(request.data)
        assert (payload.get("thinking") == {"type": "disabled"}) is disabled
        return Response(final_stream())
    client(opener, base, model).review("文档正文。", on_event=lambda _: None)
