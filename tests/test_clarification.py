import io
import json
import time
from unittest.mock import patch

import pytest

from wenlint.agent import AgentConfig, AgentProtocolError, OpenAICompatibleAgent
from wenlint.clarification import clarification_target, clarify, _minimal_patch
from wenlint.desktop import DesktopApi


SOURCE = '😀项目说明。\n请相关同事尽快处理这个问题。\n其他说明保持不变。'
ASK = dict(action='ASK', before='请相关同事尽快处理这个问题。', reason='谁负责，何时完成？', rule='A001', origin='static', finding_index=1)


def agent_for(response, requests=None):
    def opener(request, **kwargs):
        if requests is not None:
            requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(response, ensure_ascii=False)}}]}).encode())
    return OpenAICompatibleAgent(AgentConfig('https://api.deepseek.com', 'test-secret', 'deepseek-v4-flash'), opener=opener)


def response(action='REWRITE', before=ASK['before'], after='由李明于周五完成问题修复。'):
    return dict(summary='已根据作者信息补充。', decisions=[dict(action=action, before=before, after=after, reason='明确责任人和期限。', rule='SEMANTIC_CLARIFICATION', finding_index=None, related_finding_indexes=[])])


def test_clarification_sends_only_bounded_target_and_returns_unapplied_patch():
    requests, events = [], []
    result = clarify(agent_for(response(), requests), SOURCE, ASK, '由李明于周五完成问题修复。', on_event=events.append)
    sent = requests[0]['messages'][1]['content']
    assert '😀项目说明' not in sent and '其他说明' not in sent
    assert result['decision']['source_start'] == 7
    assert result['decision']['action'] == 'REWRITE'
    assert 'revisedText' not in result
    assert len(requests) == 1 and requests[0]['thinking'] == {'type': 'disabled'}
    assert any(e['kind'] == 'decision' for e in events)


@pytest.mark.parametrize('output', [response(before='其他说明保持不变。'), response(after=ASK['before']), response(action='ASK'), response(action='KEEP')])
def test_clarification_rejects_wrong_span_noop_and_invalid_action(output):
    with pytest.raises(AgentProtocolError):
        clarify(agent_for(output), SOURCE, ASK, '作者补充')


def test_insufficient_answer_keeps_question_without_patch():
    result = clarify(agent_for(response(action='ASK', after='')), SOURCE, ASK, '还没有确定负责人')
    assert result['decision']['action'] == 'ASK' and result['decision']['after'] == ''


def test_followup_includes_previous_author_facts_and_bounds_history():
    requests = []
    item = {**ASK, 'author_information': '负责人是李明'}
    result = clarify(agent_for(response(), requests), SOURCE, item, '周五完成')
    sent = json.loads(requests[0]['messages'][1]['content'])
    assert sent['author_information'] == result['author_information'] == '负责人是李明\n周五完成'
    with pytest.raises(ValueError, match='累计'):
        clarify(agent_for(response()), SOURCE, {**ASK, 'author_information': 'x' * 4000}, '新增')


def test_real_clarification_window_shrinks_to_date_change_on_shared_line():
    source = '登录超时原先为 30 秒，经过讨论改为 20 秒。计划大概于 2026 年 10 月 15 日发布。'
    question = {**ASK, 'before': '计划大概于 2026 年 10 月 15 日发布。'}
    # Replay the actual Windows model's output from the 0.6.2 smoke test.
    output = response(before=source, after=source.replace('大概', ''))
    item = clarify(agent_for(output), source, question, '发布日期已确定')['decision']
    assert item['before'] == '大概' and item['after'] == ''
    assert item['source_start'] == source.index('大概')
    assert item['source_start'] > source.index('20 秒')


@pytest.mark.parametrize('before,after', [('a😀b','a👩b'), ('a👍🏻b','a👍🏽b'), ('aéb','aèb'), ('a👩‍🔬b','a👩‍💻b'), ('a🇨🇳b','a🇨🇦b')])
def test_minimized_unicode_patch_preserves_clusters_and_reconstructs(before, after):
    start, old, new = _minimal_patch(before, after)
    assert start == 1
    assert before[:start] + new + before[start + len(old):] == after


def test_ambiguous_stale_and_long_targets_fail_closed():
    for source, item in [(SOURCE * 2, ASK), (SOURCE, {**ASK, 'source_start': 2}), (SOURCE, {**ASK, 'before': 'x' * 2001})]:
        with pytest.raises(ValueError):
            clarification_target(source, item)
    source = 'x' * 100000 + ASK['before'] + 'y' * 90000
    _, target = clarification_target(source, ASK)
    assert len(target) <= 2000


def test_desktop_clarification_uses_real_job_and_safe_error_recovery():
    api = DesktopApi()
    payload = dict(text=SOURCE, decision=ASK, answer='李明周五完成', baseUrl='https://api.deepseek.com', apiKey='test-secret', model='deepseek-v4-flash')
    def wait(job):
        for _ in range(100):
            status = api.agent_review_status(job)
            if status['state'] != 'running':
                return status
            time.sleep(.01)
        pytest.fail('job did not complete')
    with patch('wenlint.desktop.OpenAICompatibleAgent', return_value=agent_for(response(before='越界'))):
        failed = wait(api.start_clarification(payload))
    assert failed['state'] == 'error'
    with patch('wenlint.desktop.OpenAICompatibleAgent', return_value=agent_for(response())):
        success = wait(api.start_clarification(payload))
    assert success['state'] == 'complete' and success['result']['ok']
    assert 'test-secret' not in json.dumps(success)
