"""Bounded in-memory review jobs; UI never waits for a model request."""
from __future__ import annotations

from threading import Event, Lock, Thread
from time import perf_counter
from uuid import uuid4


class ReviewJobs:
    def __init__(self):
        self._lock = Lock()
        self._jobs = {}

    def start(self, run):
        with self._lock:
            if any(job['state'] == 'running' for job in self._jobs.values()):
                return {'ok': False, 'error': '已有审查正在运行，请先取消'}
            if sum(job['worker_active'] for job in self._jobs.values()) >= 2:
                return {'ok': False, 'error': '上次审查正在收尾，请稍后重试'}
            job_id = uuid4().hex
            job = {'state': 'running', 'events': [], 'cancel': Event(),
                   'started': perf_counter(), 'worker_active': True}
            # One cancelled worker may wind down while a replacement starts.
            # Retain tokens until exit to bound repeated cancellation/restart.
            self._jobs = {key: value for key, value in self._jobs.items() if value['worker_active']}
            self._jobs[job_id] = job

        def emit(event):
            with self._lock:
                if job['state'] != 'running':
                    return
                clean = {key: event[key] for key in ('kind', 'lane', 'message', 'tool', 'arguments', 'args', 'result', 'model_call', 'output_chars') if key in event}
                clean.update(sequence=len(job['events']) + 1,
                             elapsed_ms=round((perf_counter() - job['started']) * 1000))
                if len(job['events']) < 2000:
                    job['events'].append(clean)

        emit({'kind': 'plan', 'message': '已开始：本地检查 → 语义复核与按需查证 → 逐项确认修改'})

        def worker():
            try:
                result = run(emit, job['cancel'])
            except Exception:
                result = {'ok': False, 'error': '审查未完成，请检查配置后重试'}
            with self._lock:
                job['worker_active'] = False
                if job['state'] == 'cancelled':
                    return
                job['state'] = 'complete' if result.get('ok') else 'error'
                job['result'] = result
                if not result.get('ok'):
                    job['error'] = result.get('error', '审查未完成')

        Thread(target=worker, daemon=True, name='wenlint-review').start()
        return {'ok': True, 'job_id': job_id}

    def status(self, payload):
        if not isinstance(payload, dict):
            return {'ok': False, 'error': '请求格式无效'}
        with self._lock:
            job = self._jobs.get(str(payload.get('job_id', '')))
            if job is None:
                return {'ok': False, 'error': '审查任务不存在或已过期'}
            after = payload.get('after', 0)
            if not isinstance(after, int) or isinstance(after, bool) or after < 0:
                return {'ok': False, 'error': '事件游标无效'}
            return {'ok': True, 'state': job['state'],
                    'events': [dict(e) for e in job['events'] if e['sequence'] > after],
                    **{key: job[key] for key in ('result', 'error') if key in job}}

    def cancel(self, payload):
        if not isinstance(payload, dict):
            return {'ok': False, 'error': '请求格式无效'}
        with self._lock:
            job = self._jobs.get(str(payload.get('job_id', '')))
            if job is None:
                return {'ok': False, 'error': '审查任务不存在或已过期'}
            if job['state'] == 'running':
                job['cancel'].set()
                job['state'] = 'cancelled'
            return {'ok': True, 'state': job['state']}
