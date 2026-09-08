"""Repeatable latency gates; optional paid smoke reads credentials from environment."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wenlint.desktop import DesktopApi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Use configured model; makes 1-5 paid requests')
    parser.add_argument('--knowledge', action='store_true', help='Also verify read-only evidence tools against the fictional demo workspace')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    api = DesktopApi()
    source = '总而言之，我们对方案进行分析。'
    scans = []
    for _ in range(30):
        start = time.perf_counter()
        assert api.static_scan({'text': source})['ok']
        scans.append((time.perf_counter() - start) * 1000)
    payload = {'text': source, 'demo': not args.live}
    if args.knowledge:
        if not args.live:
            parser.error('--knowledge requires --live')
        from wenlint.workspace import WorkspaceSession
        api._workspace = WorkspaceSession(Path(__file__).resolve().parents[1] / 'demo' / 'workspace')
        payload.update(text='Aurora Desktop 2.4.0 的登录超时为 30 秒，最低支持 Windows 10。',
                       workspacePath='review-me.md', use_workspace_tools=True)
    if args.live:
        payload.update(baseUrl=os.environ['WENLINT_BASE_URL'], apiKey=os.environ['WENLINT_API_KEY'], model=os.environ['WENLINT_MODEL'])
    started = time.perf_counter()
    job = api.start_agent_review(payload)
    assert job['ok'], job
    start_ms = (time.perf_counter() - started) * 1000
    first_event_ms = None
    first_model_ms = None
    event_count = 0
    tool_calls = []
    cursor = 0
    while time.perf_counter() - started < 125:
        status = api.agent_review_status({'job_id': job['job_id'], 'after': cursor})
        for event in status['events']:
            cursor = event['sequence']
            event_count += 1
            if event.get('kind') == 'tool_start':
                tool_calls.append(event.get('tool'))
            if first_event_ms is None:
                first_event_ms = (time.perf_counter() - started) * 1000
            if '输出字符' in event.get('message', '') and first_model_ms is None:
                first_model_ms = event['elapsed_ms']
        if status['state'] != 'running':
            break
        time.sleep(0.01)
    elapsed_ms = (time.perf_counter() - started) * 1000
    result = status.get('result', {})
    report = {'mode': 'live' if args.live else 'offline-simulation',
              'static_median_ms': round(statistics.median(scans), 2),
              'static_p95_ms': round(sorted(scans)[28], 2),
              'start_ms': round(start_ms, 2), 'first_event_ms': round(first_event_ms or 0, 2),
              'first_model_output_ms': first_model_ms, 'complete_ms': round(elapsed_ms, 2),
              'state': status['state'], 'model_calls': result.get('modelCalls'),
              'decisions': len(result.get('decisions', [])), 'events': event_count,
              'error': status.get('error'),
              'tools': tool_calls,
              'thresholds': {'static_p95_ms': 100, 'start_ms': 200, 'first_event_ms': 250,
                             'complete_ms': 30000 if args.live else 1000}}
    report['passed'] = (status['state'] == 'complete' and all(report[key] < limit for key, limit in report['thresholds'].items()))
    if args.knowledge:
        report['review_decisions'] = result.get('decisions', [])
        report['passed'] = report['passed'] and bool(tool_calls) and any(
            'product-baseline.md' in item.get('reason', '') for item in result.get('decisions', [])
        )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n', encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
