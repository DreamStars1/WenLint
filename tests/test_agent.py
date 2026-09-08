from __future__ import annotations

import json

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
    captured: dict[str, object] = {}

    def opener(request: object, *, timeout: float) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
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
            "revised_text": "该结论需要复核。",
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

    request = captured["request"]
    assert request.full_url == "https://api.example.com/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer top-secret-key"
    request_body = request.data.decode("utf-8")
    assert "top-secret-key" not in request_body
    assert "仍然需要复核。" in request_body
    assert captured["timeout"] == 12
    assert result.revised_text == "该结论需要复核。"
    assert result.decisions[0].action == "REWRITE"
    assert result.decisions[0].finding_index == 1


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


def test_review_rejects_changes_not_declared_by_rewrite_decisions() -> None:
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
    with pytest.raises(AgentProtocolError, match="未由 REWRITE"):
        agent.review("原文保持不变。")


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
