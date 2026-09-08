from __future__ import annotations

import re
import json
import threading
from dataclasses import replace

import pytest

from wenlint.agent import AgentConfig, AgentProtocolError, AgentReview, ReviewDecision
from wenlint.segmented_review import SegmentedReviews, split_segments
import wenlint.segmented_review as module


CONFIG = AgentConfig("https://example.invalid/v1", "not-a-real-key", "test-model")
TEXT = ("a" * 3_900 + "\n\n") * 5


class FakeFactory:
    def __init__(self, *, fail_at=None, requests=2, cancel_at=None):
        self.inputs = []
        self.fail_at = fail_at
        self.requests = requests
        self.cancel_at = cancel_at

    def __call__(self, config, *, opener):
        parent = self

        class FakeAgent:
            def review(self, chunk, **options):
                parent.inputs.append((chunk, options))
                for _ in range(parent.requests):
                    opener(object(), timeout=config.timeout)
                if len(parent.inputs) == parent.fail_at:
                    raise AgentProtocolError("模拟第二路失败")
                core_start, core_end = map(int, re.search(r"从字符 (\d+) 到 (\d+)", options["workspace_context"]).groups())
                decisions = [ReviewDecision(index, item["rule_id"], "KEEP", "合理用法", item["match"], "", "static", ())
                             for index, item in enumerate(options["precomputed_findings"], 1)]
                decisions.append(ReviewDecision(None, "SEMANTIC_TEST", "REWRITE", "局部建议",
                    chunk[core_start:core_start + 5], "修改", "semantic", (), source_start=core_start))
                if core_start:
                    decisions.append(ReviewDecision(None, "SEMANTIC_CONTEXT", "VERIFY", "仅前文问题",
                        chunk[:2], "", "semantic", (), source_start=0))
                if len(parent.inputs) == parent.cancel_at:
                    options["cancel_event"].set()
                return AgentReview("测试", tuple(decisions), chunk, parent.requests, 1)

        return FakeAgent()


def coordinator(factory=None, **kwargs):
    return SegmentedReviews(agent_factory=factory or FakeFactory(), opener=lambda *args, **kw: None, **kwargs)


def test_single_long_line_is_bounded_and_covers_every_character():
    text = "a" * 19_999
    segments = split_segments(text)
    assert len(segments) == 5
    assert "".join(text[item.start:item.end] for item in segments) == text
    assert all(item.end - item.start <= 4_000 for item in segments)
    assert all(item.start - item.context_start <= 300 for item in segments)
    assert all(item.context_end - item.end <= 300 for item in segments)
    assert segments[0].start == 0 and segments[-1].end == len(text)


def test_dense_static_candidates_also_bound_each_segment():
    text = "a" * 9000
    offsets = list(range(0, len(text), 30))
    segments = split_segments(text, offsets)
    assert "".join(text[s.start:s.end] for s in segments) == text
    assert all(sum(s.start <= offset < s.end for offset in offsets) <= 24 for s in segments)


def test_batches_resume_cumulatively_with_stable_ids_and_repeated_text_anchors():
    factory = FakeFactory()
    reviews = coordinator(factory)
    session_id = reviews.prepare(TEXT, CONFIG)
    first = reviews.run(TEXT, CONFIG, session_id=session_id)
    assert first["reviewStatus"] == "partial" and first["canContinue"]
    assert first["coverage"]["completed_segments"] == 2
    assert first["modelCalls"] == 4
    assert first["semanticIssueCount"] == 2  # overlapping context reports excluded
    assert first["revisedText"].count("修改") == 2
    first_ids = [item["id"] for item in first["decisions"]]
    second = reviews.run(TEXT, CONFIG, session_id=session_id)
    assert second["coverage"]["completed_segments"] == 4
    assert [item["id"] for item in second["decisions"]][:2] == first_ids
    final = reviews.run(TEXT, CONFIG, session_id=session_id)
    assert final["reviewStatus"] == "completed" and not final["canContinue"]
    assert final["coverage"]["status"] == "complete"
    assert final["modelCalls"] == 10 and final["coverage"]["reviewed_chars"] == len(TEXT)
    assert final["revisedText"].count("修改") == 5
    assert all(len(chunk) <= 4_600 for chunk, _ in factory.inputs)
    assert all(TEXT != chunk for chunk, _ in factory.inputs)


def test_global_scan_once_and_finding_indexes_survive_local_numbering(monkeypatch):
    calls = []

    def scan(text, **kwargs):
        calls.append(text)
        return [{"line": line, "col": 1, "rule_id": "H001", "match": "a",
                 "sentence": "a" * 20_000} for line in (1, 5, 9)]

    monkeypatch.setattr(module, "scan_text", scan)
    factory = FakeFactory()
    reviews = coordinator(factory)
    result = reviews.run(TEXT, CONFIG)
    while result["canContinue"]:
        result = reviews.run(TEXT, CONFIG, session_id=result["reviewSessionId"])
    assert calls == [TEXT]
    static = [item for item in result["decisions"] if item["finding_index"] is not None]
    assert [item["finding_index"] for item in static] == [1, 2, 3]
    assert [item["id"] for item in static] == ["static-1", "static-2", "static-3"]
    for chunk, options in factory.inputs:
        for finding in options["precomputed_findings"]:
            assert len(finding["sentence"]) <= 300
            assert finding["line"] <= len(chunk.splitlines())


@pytest.mark.parametrize("changed", ["text", "profile", "filename", "model", "base_url", "workspace_key"])
def test_continuation_rejects_changed_identity(changed):
    reviews = coordinator()
    session_id = reviews.prepare(TEXT, CONFIG)
    kwargs = {"text": TEXT, "config": CONFIG, "session_id": session_id}
    if changed in {"model", "base_url"}:
        kwargs["config"] = replace(CONFIG, **{changed: "different" if changed == "model" else "https://other.invalid"})
    elif changed == "text":
        kwargs["text"] += "x"
    else:
        kwargs[changed] = "different"
    result = reviews.run(**kwargs)
    assert not result["ok"] and "改变" in result["error"]


def test_second_lane_failure_keeps_only_committed_segment_and_can_retry():
    factory = FakeFactory(fail_at=2)
    reviews = coordinator(factory)
    result = reviews.run(TEXT, CONFIG)
    assert result["reviewStatus"] == "partial"
    assert result["coverage"]["completed_segments"] == 1
    assert result["modelCalls"] == 4  # Includes unsuccessful HTTP attempts.
    assert "模拟第二路失败" in result["warning"]
    assert result["revisedText"].count("修改") == 1
    resumed = reviews.run(TEXT, CONFIG, session_id=result["reviewSessionId"])
    assert resumed["coverage"]["completed_segments"] == 3
    assert resumed["decisions"][0]["id"] == result["decisions"][0]["id"]


def test_first_failure_returns_explicit_zero_coverage_partial():
    result = coordinator(FakeFactory(fail_at=1)).run(TEXT, CONFIG)
    assert result["ok"] and result["canContinue"]
    assert result["reviewStatus"] == "partial" and result["warning"]
    assert result["coverage"]["reviewed_chars"] == 0
    assert result["decisions"] == [] and result["revisedText"] == TEXT


def test_actual_http_budget_caps_calls_even_on_failure(monkeypatch):
    attempts = []
    reviews = SegmentedReviews(agent_factory=FakeFactory(requests=13), opener=lambda *a, **k: attempts.append(1))
    result = reviews.run(TEXT, CONFIG)
    assert len(attempts) == result["modelCalls"] == 12
    assert result["coverage"]["completed_segments"] == 0
    assert result["canContinue"]
    monkeypatch.setattr(module, "MAX_SESSION_CALLS", 15)
    result = reviews.run(TEXT, CONFIG, session_id=result["reviewSessionId"])
    assert len(attempts) == result["modelCalls"] == 15
    assert not result["canContinue"]


def test_cancellation_preserves_completed_core_and_prepared_id_can_resume():
    reviews = coordinator(FakeFactory(cancel_at=2))
    session_id = reviews.prepare(TEXT, CONFIG)
    result = reviews.run(TEXT, CONFIG, session_id=session_id, cancel_event=threading.Event())
    assert result["coverage"]["completed_segments"] == 1
    assert result["canContinue"] and result["reviewSessionId"] == session_id
    resumed = reviews.run(TEXT, CONFIG, session_id=session_id)
    assert resumed["coverage"]["completed_segments"] == 3


def test_batch_deadline_cannot_start_more_http_after_120_seconds():
    clock = [0.0]
    attempts = []

    def opener(*args, **kwargs):
        attempts.append(kwargs["timeout"])
        clock[0] += 70

    reviews = SegmentedReviews(agent_factory=FakeFactory(requests=3), opener=opener, clock=lambda: clock[0])
    result = reviews.run(TEXT, CONFIG)
    assert attempts == [90.0, 50.0]
    assert result["coverage"]["completed_segments"] == 0
    assert "120 秒" in result["warning"]


def test_oldest_idle_session_evicted_after_three_preparations():
    reviews = coordinator()
    ids = [reviews.prepare(TEXT + str(index), CONFIG) for index in range(4)]
    assert len(reviews._sessions) == 3
    result = reviews.run(TEXT + "0", CONFIG, session_id=ids[0])
    assert not result["ok"] and "失效" in result["error"]


def test_workspace_observations_reused_without_unbounded_reads():
    class Access:
        context = {}
        tool_definitions = ()
        needs_reference_observation = False

        def __init__(self):
            self.calls = 0

        def execute(self, name, arguments):
            self.calls += 1
            return '{"ok":true,"content":"参考依据"}'

    access = Access()
    budget = module._WorkspaceBudget(access)
    first = budget.execute("read_workspace_file", '{"path":"ref.md"}')
    assert budget.execute("read_workspace_file", '{"path":"ref.md"}') == first
    for index in range(20):
        budget.execute("read_workspace_file", f'{{"path":"ref{index}.md"}}')
    assert access.calls == budget.calls == 8
    assert "参考依据" in budget.reused_context()
    assert len(budget.reused_context()) <= 6_000


def test_workspace_output_budget_does_not_cache_oversized_observation():
    class Access:
        def execute(self, *args):
            return "x" * 48_001

    budget = module._WorkspaceBudget(Access())
    result = budget.execute("read_workspace_file", "{}")
    assert "预算" in result and budget.chars == 48_000
    assert not budget.observations


def test_unanchored_question_is_kept_as_non_editing_core_question():
    segment = split_segments(TEXT)[1]
    question = ReviewDecision(None, "SEMANTIC_GAP", "ASK", "缺少结论依据", "", "", "semantic", ())
    mapped = module._map_decisions([question], segment, [], TEXT[segment.context_start:segment.context_end])
    assert len(mapped) == 1 and mapped[0].action == "ASK"
    assert mapped[0].source_start == segment.start
    assert mapped[0].before and "本段整体待确认" in mapped[0].reason


def test_boundary_crossing_edit_becomes_question_without_rewriting_adjacent_core():
    segment = split_segments(TEXT)[0]
    offset = segment.end - 3
    chunk = TEXT[segment.context_start:segment.context_end]
    item = ReviewDecision(None, "SEMANTIC_CROSS", "REWRITE", "跨段建议", chunk[offset:offset + 8],
                          "更改", "semantic", (), source_start=offset)
    mapped = module._map_decisions([item], segment, [], chunk)
    assert mapped[0].action == "ASK" and mapped[0].after == ""
    assert "跨越分段边界" in mapped[0].reason


def test_real_agent_transport_receives_only_segments_and_supplied_findings(monkeypatch):
    received = []
    scan_calls = []

    def scan(text, **kwargs):
        scan_calls.append(text)
        return []

    def forbidden_scan(*args, **kwargs):
        raise AssertionError("segment must use precomputed findings")

    monkeypatch.setattr(module, "scan_text", scan)
    monkeypatch.setattr("wenlint.agent.scan_text", forbidden_scan)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            return json.dumps({"choices": [{"message": {"content": '{"summary":"本段无额外问题","decisions":[]}'}}]}).encode()

    def opener(request, **kwargs):
        payload = json.loads(request.data)
        task = json.loads(payload["messages"][1]["content"].split("\n", 1)[1])
        received.append(task)
        return Response()

    reviews = SegmentedReviews(opener=opener)
    result = reviews.run(TEXT, CONFIG)
    assert result["coverage"]["completed_segments"] == 2
    assert result["modelCalls"] == len(received) == 2
    assert scan_calls == [TEXT]
    assert all(len(task["document"]) <= 4_600 for task in received)
    assert all(task["covered_static_findings"] == [] for task in received)


def test_same_session_cannot_start_a_second_worker():
    reviews = coordinator()
    session_id = reviews.prepare(TEXT, CONFIG)
    session = reviews._sessions[session_id]
    with session.lock:
        result = reviews.run(TEXT, CONFIG, session_id=session_id)
    assert not result["ok"] and "仍在运行" in result["error"]
