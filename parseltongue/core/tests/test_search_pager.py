"""Search terminal paging and pipe compatibility."""

import json
import os
import sys

import pytest
from click.testing import CliRunner

from parseltongue.core.inspect import bench_cli


@pytest.mark.parametrize("fmt", ["grouped", "grep", "json"])
@pytest.mark.parametrize("terminal,no_pager", [(True, False), (True, True), (False, False)])
def test_search_output(monkeypatch, fmt, terminal, no_pager):
    reply = {
        "ok": True,
        "lines": [{"document": "a.py", "line": n, "context": "café", "callers": []} for n in range(1, 2001)],
        "total": 2000,
        "warnings": ["test warning"],
    }
    calls = []

    def query(cmd):
        assert cmd == {"action": "search", "limit": 0, "query": "café"}
        monkeypatch.setattr(sys.stdout, "isatty", lambda: terminal)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: terminal)
        return reply

    def pager(chunks):
        assert not isinstance(chunks, str)
        assert os.environ["LESS"] == "-FRX"
        calls.append("".join(chunks))

    monkeypatch.delenv("LESS", raising=False)
    monkeypatch.setattr(bench_cli, "_query", query)
    monkeypatch.setattr(bench_cli.click, "echo_via_pager", pager)
    args = ["search", "café", "-o", fmt] + (["--no-pager"] if no_pager else [])
    result = CliRunner().invoke(bench_cli.cli, args)
    assert result.exit_code == 0, result.output
    expected = bench_cli._render_search(reply, fmt, json)
    if terminal and not no_pager:
        assert calls == [expected]
        assert "café" not in result.stdout
    else:
        assert not calls
        assert result.stdout == expected
    assert "test warning" in result.stderr
    assert "LESS" not in os.environ


def test_pager_can_stop_rendering_early(monkeypatch):
    def rows():
        yield {"document": "a.py", "line": 1, "context": "first"}
        raise AssertionError("the rest of the reply must not be rendered after quit")

    def query(cmd):
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        return {"ok": True, "lines": rows()}

    def pager(chunks):
        assert os.environ["LESS"] == "-S"
        assert next(chunks) == "a.py:1:first\n"

    monkeypatch.setenv("LESS", "-S")
    monkeypatch.setattr(bench_cli, "_query", query)
    monkeypatch.setattr(bench_cli.click, "echo_via_pager", pager)
    result = CliRunner().invoke(bench_cli.cli, ["search", "first", "-o", "grep"])
    assert result.exit_code == 0, result.output
    assert os.environ["LESS"] == "-S"


@pytest.mark.parametrize(
    'flags,enabled', [([], False), (['--highlights'], True), (['--highlights', '--no-highlights'], False)]
)
def test_highlights_are_explicit(monkeypatch, flags, enabled):
    calls = []

    def query(cmd):
        calls.append(cmd)
        return {'ok': True, 'lines': []}

    monkeypatch.setattr(bench_cli, '_query', query)
    result = CliRunner().invoke(bench_cli.cli, ['search', 'azure', '-o', 'json', *flags])
    assert result.exit_code == 0, result.output
    assert calls[0].get('highlights', False) is enabled
