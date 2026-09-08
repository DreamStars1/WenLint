from __future__ import annotations

import json
import threading

import pytest

from wenlint.agent import (
    AgentConfig,
    AgentProtocolError,
    OpenAICompatibleAgent,
    build_chat_completions_url,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _response(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}


def _request_lane(request: object) -> str:
    payload = json.loads(request.data.decode("utf-8"))
    user_content = payload["messages"][1]["content"]
    task = json.loads(user_content.split("\n", 1)[1])
    return task["review_lane"]


def test_build_chat_completions_url_accepts_base_or_full_endpoint() -> None:
    assert (
        build_chat_completions_url("https://api.example.com/v1/")
        == "https://api.example.com/v1/chat/completions"
    )
    assert (
        build_chat_completions_url("https://api.example.com/v1/chat/completions")
        == "https://api.example.com/v1/chat/completions"
    )


@pytest.mark.parametrize("value", ["", "api.example.com/v1", "file:///tmp/model"])
def test_build_chat_completions_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        build_chat_completions_url(value)


def test_review_sends_key_only_in_authorization_header_and_parses_fenced_json() -> None:
    captured: list[tuple[object, float]] = []

    def opener(request: object, *, timeout: float) -> FakeResponse:
        captured.append((request, timeout))
        if _request_lane(request) == "semantic":
            body = {"summary": "未发现额外问题。", "decisions": []}
            return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))
        body = {
            "summary": "发现一处依赖旧上下文的表达。",
            "decisions": [
                {
                    "finding_index": 1,
                    "rule": "M002",
                    "action": "REWRITE",
                    "reason": "脱离讨论记录后指代不清。",
                    "before": "仍然需要复核。",
                    "after": "该结论需要复核。",
                }
            ],
        }
        return FakeResponse(_response(f"```json\n{json.dumps(body, ensure_ascii=False)}\n```"))

    config = AgentConfig(
        base_url="https://api.example.com/v1",
        api_key="top-secret-key",
        model="review-model",
        timeout=12,
    )
    result = OpenAICompatibleAgent(config, opener=opener).review(
        "仍然需要复核。", profile="general", filename="draft.md"
    )

    assert len(captured) == 2
    for request, timeout in captured:
        assert request.full_url == "https://api.example.com/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer top-secret-key"
        request_body = request.data.decode("utf-8")
        assert "top-secret-key" not in request_body
        assert "仍然需要复核。" in request_body
        assert timeout == 12
    assert result.revised_text == "该结论需要复核。"
    assert result.decisions[0].action == "REWRITE"
    assert result.decisions[0].finding_index == 1
    assert result.model_calls == 2
    assert result.semantic_issue_count == 0


def test_review_rejects_an_unknown_action() -> None:
    body = {
        "summary": "ok",
        "decisions": [
            {
                "finding_index": None,
                "rule": "CTX001",
                "action": "DELETE_EVERYTHING",
                "reason": "bad",
                "before": "a",
                "after": "",
            }
        ],
        "revised_text": "a",
    }

    def opener(request: object, *, timeout: float) -> FakeResponse:
        return FakeResponse(_response(json.dumps(body)))

    agent = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    )
    with pytest.raises(AgentProtocolError, match="action"):
        agent.review("a")


def test_review_requires_a_decision_for_every_static_finding() -> None:
    body = {"summary": "漏审", "decisions": [], "revised_text": "仍然保留。"}

    def opener(request: object, *, timeout: float) -> FakeResponse:
        return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))

    agent = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    )
    with pytest.raises(AgentProtocolError, match="每条静态 finding"):
        agent.review("仍然保留。")


def test_review_ignores_provider_revision_and_derives_text_from_decisions() -> None:
    body = {
        "summary": "无命中",
        "decisions": [],
        "revised_text": "模型擅自改写。",
    }

    def opener(request: object, *, timeout: float) -> FakeResponse:
        return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))

    agent = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    )
    result = agent.review("原文保持不变。")
    assert result.revised_text == "原文保持不变。"


def test_review_reports_and_applies_new_semantic_issue_without_static_match() -> None:
    body = {
        "summary": "发现一处模型独立识别的问题。",
        "decisions": [
            {
                "finding_index": None,
                "related_finding_indexes": [],
                "rule": "SEMANTIC_CLARITY",
                "action": "REWRITE",
                "reason": "主语缺失。",
                "before": "完成后提交。",
                "after": "负责人完成检查后提交报告。",
            }
        ],
    }

    def opener(request: object, *, timeout: float) -> FakeResponse:
        return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))

    result = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    ).review("完成后提交。")

    assert result.revised_text == "负责人完成检查后提交报告。"
    assert result.semantic_issue_count == 1
    assert result.decisions[0].origin == "semantic"


def test_review_uses_parallel_static_and_semantic_lanes() -> None:
    barrier = threading.Barrier(2, timeout=2)

    def opener(request: object, *, timeout: float) -> FakeResponse:
        barrier.wait()
        if _request_lane(request) == "static":
            body = {
                "summary": "静态候选已裁决。",
                "decisions": [
                    {
                        "finding_index": 1,
                        "rule": "M002",
                        "action": "KEEP",
                        "reason": "上下文清楚。",
                        "before": "仍然需要复核。",
                        "after": "",
                    }
                ],
            }
        else:
            body = {"summary": "未发现额外问题。", "decisions": []}
        return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))

    result = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    ).review("仍然需要复核。")

    assert result.model_calls == 2
    assert result.revised_text == "仍然需要复核。"


def test_review_without_static_findings_still_runs_semantic_lane() -> None:
    calls = 0

    def opener(request: object, *, timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        assert _request_lane(request) == "semantic"
        body = {"summary": "全文语义复核完成，未发现问题。", "decisions": []}
        return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))

    result = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    ).review("这是一段表述清楚的正文。")

    assert calls == 1
    assert result.decisions == ()
    assert result.revised_text == "这是一段表述清楚的正文。"
    assert result.semantic_issue_count == 0


def test_review_drops_semantic_issue_that_duplicates_a_static_match() -> None:
    def opener(request: object, *, timeout: float) -> FakeResponse:
        if _request_lane(request) == "static":
            body = {
                "summary": "静态候选已裁决。",
                "decisions": [
                    {
                        "finding_index": 1,
                        "rule": "M002",
                        "action": "KEEP",
                        "reason": "上下文清楚。",
                        "before": "仍然",
                        "after": "",
                    }
                ],
            }
        else:
            body = {
                "summary": "发现问题。",
                "decisions": [
                    {
                        "finding_index": None,
                        "related_finding_indexes": [1],
                        "rule": "SEMANTIC_CONTEXT",
                        "action": "ASK",
                        "reason": "重复报告静态候选。",
                        "before": "仍然",
                        "after": "",
                    }
                ],
            }
        return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))

    result = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    ).review("仍然需要复核。")

    assert len(result.decisions) == 1
    assert result.decisions[0].origin == "static"
    assert result.semantic_issue_count == 0


def test_review_drops_larger_semantic_span_overlapping_static_match() -> None:
    def opener(request: object, *, timeout: float) -> FakeResponse:
        if _request_lane(request) == "static":
            body = {
                "summary": "静态候选已裁决。",
                "decisions": [
                    {
                        "finding_index": 1,
                        "rule": "M002",
                        "action": "KEEP",
                        "reason": "上下文清楚。",
                        "before": "仍然",
                        "after": "",
                    }
                ],
            }
        else:
            body = {
                "summary": "发现问题。",
                "decisions": [
                    {
                        "finding_index": None,
                        "related_finding_indexes": [1],
                        "rule": "SEMANTIC_CONTEXT",
                        "action": "ASK",
                        "reason": "重复报告静态候选。",
                        "before": "系统仍然保留旧值",
                        "after": "",
                    }
                ],
            }
        return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))

    result = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    ).review("系统仍然保留旧值。")

    assert result.semantic_issue_count == 0


def test_review_keeps_distinct_semantic_span_in_same_sentence() -> None:
    source = "系统仍然保留旧值，但负责人未定义。"

    def opener(request: object, *, timeout: float) -> FakeResponse:
        if _request_lane(request) == "static":
            body = {
                "summary": "静态候选已裁决。",
                "decisions": [
                    {
                        "finding_index": 1,
                        "rule": "M002",
                        "action": "KEEP",
                        "reason": "上下文清楚。",
                        "before": "仍然",
                        "after": "",
                    }
                ],
            }
        else:
            body = {
                "summary": "发现另一处问题。",
                "decisions": [
                    {
                        "finding_index": None,
                        "related_finding_indexes": [],
                        "rule": "SEMANTIC_MISSING_SUBJECT",
                        "action": "ASK",
                        "reason": "负责人没有定义。",
                        "before": "负责人未定义",
                        "after": "",
                    }
                ],
            }
        return FakeResponse(_response(json.dumps(body, ensure_ascii=False)))

    result = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    ).review(source)

    assert result.semantic_issue_count == 1
    assert result.decisions[-1].rule == "SEMANTIC_MISSING_SUBJECT"


def test_review_rejects_malformed_provider_response_without_echoing_source() -> None:
    source = "这段原文不应出现在异常消息里"

    def opener(request: object, *, timeout: float) -> FakeResponse:
        return FakeResponse({"unexpected": source})

    agent = OpenAICompatibleAgent(
        AgentConfig("https://api.example.com/v1", "key", "model"), opener=opener
    )
    with pytest.raises(AgentProtocolError) as exc:
        agent.review(source)
    assert source not in str(exc.value)


def test_review_requires_nonempty_credentials_and_model() -> None:
    with pytest.raises(ValueError, match="API Key"):
        AgentConfig("https://api.example.com/v1", "", "model").validate()
    with pytest.raises(ValueError, match="模型"):
        AgentConfig("https://api.example.com/v1", "key", "").validate()
