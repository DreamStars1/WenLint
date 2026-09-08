"""Regression checks for slow proxy/model connections, without real requests."""
import io
import json
import socket
import ssl
import threading
import time
from types import SimpleNamespace
import pytest
from urllib.error import URLError

from wenlint.agent import AgentConfig, AgentConnectionError, OpenAICompatibleAgent, _summary_preview


def test_slow_headers_do_not_hit_an_undocumented_15_second_limit():
    def opener(request, *, timeout):
        # Deterministic transport simulation: headers arrive after 20 seconds.
        if timeout < 20:
            raise URLError(socket.timeout('private proxy address'))
        return io.BytesIO(json.dumps({'choices': [{'message': {
            'content': '{"summary":"已完成","decisions":[]}'}}]}).encode())

    agent = OpenAICompatibleAgent(AgentConfig('https://api.deepseek.com', 'test-key', 'deepseek-v4-flash'), opener=opener)
    result = agent.review('文档正文。', on_event=lambda _: None)
    assert result.model_calls == 1


@pytest.mark.parametrize('reason,expected', [
    (socket.timeout('private'), '超时'), (ssl.SSLCertVerificationError('private'), '证书'),
    (socket.gaierror('private'), '解析'), (ConnectionRefusedError('private'), '拒绝连接'),
])
def test_network_errors_are_actionable_and_redacted(reason, expected):
    def opener(*args, **kwargs):
        raise URLError(reason)
    with pytest.raises(AgentConnectionError, match=expected) as error:
        OpenAICompatibleAgent(AgentConfig('https://example.com', 'secret', 'model'), opener=opener).review('文档正文。', on_event=lambda _: None)
    assert 'private' not in str(error.value) and 'secret' not in str(error.value)


def test_active_stream_lasts_longer_than_idle_timeout_and_previews_summary():
    class Stream(io.BytesIO):
        headers = {'Content-Type': 'text/event-stream'}
        def readline(self, size=-1):
            time.sleep(0.15)
            return super().readline(size)
    data = b': heartbeat\n\n' * 3
    for text in ['{"summary":"', '有明确建议', '","decisions":[]}']:
        data += ('data: ' + json.dumps({'choices': [{'delta': {'content': text}}]}) + '\n\n').encode()
    data += b'data: [DONE]\n\n'
    events = []
    agent = OpenAICompatibleAgent(AgentConfig('https://example.com', 'secret', 'model', timeout=1), opener=lambda *a, **k: Stream(data))
    result = agent.review('文档正文。', on_event=events.append)
    assert result.summary == '有明确建议'
    assert any(e['kind'] == 'preview' and e['message'] == '有明确建议' for e in events)


def test_idle_stream_times_out_without_waiting_for_overall_cap():
    released = threading.Event()
    class Stalled(io.BytesIO):
        headers = {'Content-Type': 'text/event-stream'}
        def readline(self, size=-1):
            released.wait(4)
            return b''
    agent = OpenAICompatibleAgent(AgentConfig('https://example.com', 'secret', 'model', timeout=1), opener=lambda *a, **k: Stalled())
    started = time.monotonic()
    try:
        with pytest.raises(AgentConnectionError, match='未收到模型数据'):
            agent.review('文档正文。', on_event=lambda _: None)
        assert time.monotonic() - started < 2
    finally:
        released.set()


def test_preview_hides_incomplete_escapes_and_does_not_parse_decisions():
    assert _summary_preview('{"summary":"中文\\u4e') == '中文'
    assert _summary_preview('{"decisions": [{"reason":"private"}]}') == ''


def test_idle_timeout_closes_socket_and_releases_transport_permit(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr('wenlint.agent._TRANSPORT_SLOTS', slots)
    connected, provider = socket.socketpair()
    # Windows shutdown does not wake select() immediately. Respect the actual
    # transport's finite read timeout, with a small margin after the idle timer.
    connected.settimeout(1.5)
    closed = threading.Event()
    interrupted = threading.Event()
    external_cancel = threading.Event()

    class ObservedSocket:
        def shutdown(self, how):
            interrupted.set()
            connected.shutdown(how)

    class SocketResponse:
        headers = {'Content-Type': 'text/event-stream'}
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=ObservedSocket()))
        def __enter__(self):
            self.reader = connected.makefile('rb')
            return self
        def readline(self, size):
            return self.reader.readline(size)
        def __exit__(self, *args):
            self.reader.close()
            closed.set()

    agent = OpenAICompatibleAgent(AgentConfig('https://example.com', 'secret', 'model', timeout=1), opener=lambda *a, **k: SocketResponse())
    try:
        with pytest.raises(AgentConnectionError, match='未收到模型数据'):
            agent.review('文档正文。', on_event=lambda _: None, cancel_event=external_cancel)
        assert interrupted.wait(0.3), 'idle timeout must notify the socket watcher'
        assert closed.wait(1), 'transport must exit within its finite read timeout'
        assert not external_cancel.is_set(), 'request timeout must not masquerade as user cancellation'
        assert slots.acquire(timeout=1), 'permit must be released when the socket exits'
        slots.release()
    finally:
        provider.close()
        connected.close()
