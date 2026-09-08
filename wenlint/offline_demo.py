"""Explicitly simulated, offline walkthrough; never masquerades as LLM review."""
from datetime import datetime, timezone
from time import perf_counter

from .scanner import scan_text


def review_demo(text, profile, filename, emit=None, cancel=None):
    started = perf_counter()
    if cancel is not None and cancel.is_set():
        return {'ok': False, 'error': '审查已取消'}
    def event(kind, message):
        if emit:
            emit({'kind': kind, 'lane': 'demo', 'message': message})
    event('plan', '离线演示（模拟）：展示检查、查证提示和逐项确认，不调用模型。')
    findings = scan_text(text, profile=profile, filename=filename)
    event('tool_start', '运行本地静态扫描 scan_text')
    event('tool_result', f'本地扫描完成，发现 {len(findings)} 条规则候选。')
    decisions = []
    examples = [
        ('总而言之，', '', '删除不承载信息的套话引导词。'),
        ('进行分析', '分析', '删除冗余动词，保留原意。'),
        ('为了更好地提升用户体验，我们将会对系统进行优化。', '我们将优化系统，改善用户体验。', '压缩目的套话，不添加性能承诺。'),
    ]
    for before, after, reason in examples:
        if text.count(before) == 1:
            decisions.append(dict(finding_index=None, rule='SEMANTIC_DEMO', action='REWRITE',
                                  reason=reason, before=before, after=after, origin='demo', related_finding_indexes=[]))
    for before, action, reason in [
        ('所有用户都认为这个功能非常好，效率提升了 80%。', 'VERIFY', '需要用户调研样本与效率测试基线；演示没有这些证据，因此保留原文待核实。'),
        ('请相关同事尽快处理这个问题。', 'ASK', '请作者补充负责人、具体问题和截止时间。'),
    ]:
        if before in text:
            decisions.append(dict(finding_index=None, rule='SEMANTIC_DEMO', action=action,
                                  reason=reason, before=before, after='', origin='demo', related_finding_indexes=[]))
    for decision in decisions:
        if cancel is not None and cancel.is_set():
            return {'ok': False, 'error': '审查已取消'}
        event('decision', f"{decision['action']}：{decision['reason']}")
    event('summary', '演示完成。修改默认为待确认，只有你采纳的内容才进入修改稿。')
    revised = text
    for decision in decisions:
        if decision['action'] == 'REWRITE':
            revised = revised.replace(decision['before'], decision['after'], 1)
    return {'ok': True, 'reviewStatus': 'completed', 'demo': True,
            'reviewedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'durationMs': round((perf_counter() - started) * 1000), 'modelCalls': 0,
            'semanticIssueCount': 0, 'summary': '离线模拟演示已完成；这不是模型对文档的完整语义复核。',
            'decisions': decisions, 'revisedText': revised}
