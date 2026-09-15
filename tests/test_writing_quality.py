import io
import json

import pytest

from wenlint.agent import AgentConfig, OpenAICompatibleAgent
from wenlint.cli import main
from wenlint.rewrite_safety import numeric_literals_changed
from wenlint.scanner import scan_text


@pytest.mark.parametrize("text", [
    "这不仅是一次升级，更是一次全面革新。",
    "不仅支持导出，也支持导入。",
    "不只是改变颜色，而是调整布局。",
])
def test_escalation_is_only_a_candidate(text):
    hits = [item for item in scan_text(text) if item['rule_id'] == 'C004']
    assert len(hits) == 1
    assert hits[0]['severity'] == 'candidate'
    assert text[hits[0]['col'] - 1:].startswith(hits[0]['match'])


@pytest.mark.parametrize("text", [
    "失败原因不是权限不足，而是连接超时。",
    "不仅支持导出。也支持导入。",
    "`不仅支持导出，也支持导入`",
    "```text\n不仅支持导出，也支持导入。\n```",
    "| 功能 | 说明 |\n| --- | --- |\n| 不仅支持导出 | 也支持导入 |",
])
def test_escalation_does_not_cross_boundaries(text):
    assert not any(item['rule_id'] == 'C004' for item in scan_text(text))


def test_escalation_candidate_does_not_fail_ci(tmp_path):
    path = tmp_path / 'draft.md'
    path.write_text('不仅支持导出，也支持导入。', encoding='utf-8')
    assert main([str(path), '--fail-level', 'warning']) == 0


def test_real_added_capability_can_be_kept_by_agent():
    source = '不仅支持导出，也支持导入。'
    def opener(request, **kwargs):
        task = json.loads(json.loads(request.data)['messages'][1]['content'].split('\n', 1)[1])
        decisions = [] if task['review_lane'] == 'semantic' else [dict(
            finding_index=1, rule='C004', action='KEEP', reason='导入是新增能力。',
            before=source, after='', related_finding_indexes=[],
        )]
        body = dict(summary='检查完成', decisions=decisions)
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(body)}}]}).encode())
    agent = OpenAICompatibleAgent(AgentConfig('https://example.com/v1', 'test', 'test'), opener=opener)
    result = agent.review(source)
    assert result.revised_text == source
    assert result.decisions[0].action == 'KEEP'


@pytest.mark.parametrize("before,after", [
    ('效率有所提升。', '效率提升了47%。'),
    ('版本v0.6.3发布。', '版本v0.6.4发布。'),
    ('耗时30秒。', '耗时3秒。'),
    ('温度-3度。', '温度3度。'),
    ('错误率5%。', '错误率5。'),
    ('2026-09-15发布。', '2026-09-16发布。'),
    ('由30秒降到20秒。', '由20秒降到30秒。'),
    ('耗时30秒。', '耗时减少。'),
])
def test_numeric_changes_require_confirmation(before, after):
    assert numeric_literals_changed(before, after)


def test_preserved_numbers_allow_wording_change():
    assert not numeric_literals_changed('耗时大概30秒。', '耗时约30秒。')


@pytest.mark.parametrize('after,action', [('耗时降低47%。', 'ASK'), ('处理耗时降低。', 'REWRITE')])
def test_review_downgrades_numeric_rewrite_without_losing_other_edits(after, action):
    source = '处理耗时有所降低。记录已经保存。'
    def opener(request, **kwargs):
        body = {'summary': '检查完成', 'decisions': [
            dict(finding_index=None, related_finding_indexes=[], rule='SEMANTIC_SPECIFICITY', action='REWRITE',
                 reason='简化表达。', before='处理耗时有所降低。', after=after),
            dict(finding_index=None, related_finding_indexes=[], rule='SEMANTIC_CONCISION', action='REWRITE',
                 reason='简化表达。', before='记录已经保存。', after='记录已保存。'),
        ]}
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(body)}}]}).encode())
    agent = OpenAICompatibleAgent(AgentConfig('https://example.com/v1', 'test', 'test'), opener=opener)
    result = agent.review(source, profile='general', filename='draft.md')
    assert result.decisions[0].action == action
    assert result.decisions[0].after == ('' if action == 'ASK' else after)
    assert result.revised_text == (source.split('。')[0] + '。' if action == 'ASK' else after) + '记录已保存。'
