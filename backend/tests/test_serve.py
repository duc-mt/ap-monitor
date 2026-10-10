from __future__ import annotations

import sys

from app import serve


def test_streams_are_redirected_to_a_log_file_when_there_is_no_console(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
    monkeypatch.setattr(sys, "stdout", None)     # what pythonw.exe provides
    monkeypatch.setattr(sys, "stderr", None)
    serve._ensure_streams()
    assert sys.stdout is not None and sys.stderr is not None
    sys.stderr.write("hello\n")
    sys.stderr.flush()
    assert "hello" in (tmp_path / "logs" / "ap-monitor.log").read_text()
    assert not sys.stdout.isatty()               # the call uvicorn makes, which crashes on None


def test_existing_streams_are_left_alone(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
    before = (sys.stdout, sys.stderr)
    serve._ensure_streams()
    assert (sys.stdout, sys.stderr) == before
    assert not (tmp_path / "logs").exists()


def test_main_starts_uvicorn_with_the_configured_host_and_port(monkeypatch):
    calls = {}
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda target, **kw: calls.update(target=target, **kw))
    monkeypatch.setattr("app.config.API_HOST", "127.0.0.1")
    monkeypatch.setattr("app.config.API_PORT", 9999)
    serve.main()
    assert calls == {"target": "app.main:app", "host": "127.0.0.1", "port": 9999}
