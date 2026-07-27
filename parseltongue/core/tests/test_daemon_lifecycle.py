"""Daemon lifecycle — singleton guard, liveness probe, shutdown, registry.

pg start must never stack a second daemon onto a live socket: probe first,
refuse (or terminate with --replace), and only ever unlink sockets that are
provably stale. The registry under ~/.parseltongue/daemons.json lets
`pg status --all` enumerate every daemon regardless of socket path.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
import unittest
from pathlib import Path

import click

from ..inspect import bench_cli
from ..inspect.bench_cli import (
    _ensure_socket_free,
    _pid_alive,
    _probe_daemon,
    _recv,
    _registry_add,
    _registry_load,
    _registry_remove,
    _send,
    _terminate_daemon,
)


class _FakeDaemon:
    """Minimal socket server speaking the bench wire protocol."""

    def __init__(self, sock_path: Path, pid: int | None = 4242, pltg: str = "fake.pltg"):
        self.sock_path = sock_path
        self.pid = pid
        self.pltg = pltg
        self.got_shutdown = threading.Event()
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(str(sock_path))
        self._srv.listen(4)
        self._srv.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                cmd = _recv(conn)
                action = cmd.get("action")
                if action == "ping":
                    resp = {"ok": True, "text": "pong", "pltg": self.pltg}
                    if self.pid is not None:
                        resp["pid"] = self.pid
                    _send(conn, resp)
                elif action == "shutdown":
                    _send(conn, {"ok": True, "text": "shutting down"})
                    self.got_shutdown.set()
                    self.close()  # release socket like the real _cleanup
                else:
                    _send(conn, {"ok": False, "error": f"unknown action: {action}"})
            except (ConnectionError, OSError):
                pass
            finally:
                conn.close()

    def close(self):
        self._stop.set()
        self._srv.close()
        self.sock_path.unlink(missing_ok=True)

    def join(self):
        self._thread.join(timeout=2)


class DaemonLifecycleBase(unittest.TestCase):
    def setUp(self):
        # Short prefix — AF_UNIX socket paths are length-limited (~104 bytes)
        self.dir = Path(tempfile.mkdtemp(prefix="pgb", dir="/tmp"))
        self.sock_path = self.dir / "bench.sock"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestProbeDaemon(DaemonLifecycleBase):
    def test_absent_socket_is_none(self):
        self.assertIsNone(_probe_daemon(self.sock_path))

    def test_stale_socket_is_none(self):
        # Bind then close: the socket file remains but nothing listens
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.sock_path))
        srv.close()
        self.assertTrue(self.sock_path.exists())
        self.assertIsNone(_probe_daemon(self.sock_path))

    def test_live_daemon_answers_with_pid(self):
        daemon = _FakeDaemon(self.sock_path)
        try:
            info = _probe_daemon(self.sock_path)
            self.assertIsNotNone(info)
            self.assertEqual(info["pid"], 4242)
            self.assertEqual(info["pltg"], "fake.pltg")
        finally:
            daemon.close()
            daemon.join()


class TestEnsureSocketFree(DaemonLifecycleBase):
    def test_refuses_when_daemon_lives(self):
        daemon = _FakeDaemon(self.sock_path)
        try:
            with self.assertRaises(click.ClickException) as ctx:
                _ensure_socket_free(self.sock_path, replace=False)
            self.assertIn("already running", str(ctx.exception.message))
            self.assertIn("4242", str(ctx.exception.message))
            self.assertIn("--replace", str(ctx.exception.message))
        finally:
            daemon.close()
            daemon.join()

    def test_removes_stale_socket(self):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.sock_path))
        srv.close()
        _ensure_socket_free(self.sock_path, replace=False)
        self.assertFalse(self.sock_path.exists())

    def test_noop_when_no_socket(self):
        _ensure_socket_free(self.sock_path, replace=False)

    def test_replace_terminates_live_daemon(self):
        daemon = _FakeDaemon(self.sock_path, pid=None)
        try:
            _ensure_socket_free(self.sock_path, replace=True)
            self.assertTrue(daemon.got_shutdown.is_set())
            self.assertFalse(self.sock_path.exists())
        finally:
            daemon.close()
            daemon.join()


class TestTerminateDaemon(DaemonLifecycleBase):
    def test_shutdown_via_socket(self):
        daemon = _FakeDaemon(self.sock_path, pid=None)
        try:
            _terminate_daemon(self.sock_path, pid=None, timeout_s=5)
            self.assertTrue(daemon.got_shutdown.is_set())
            self.assertFalse(self.sock_path.exists())
        finally:
            daemon.close()
            daemon.join()

    def test_dead_pid_with_stale_socket_is_cleaned(self):
        # No listener; pid that cannot exist → treat as already-dead, unlink
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.sock_path))
        srv.close()
        dead_pid = 2**22 + 1  # beyond default pid_max on target platforms
        _terminate_daemon(self.sock_path, pid=dead_pid, timeout_s=5)
        self.assertFalse(self.sock_path.exists())


class TestShutdownAction(unittest.TestCase):
    def test_dispatch_shutdown_acks_then_signals(self):
        server = bench_cli.BenchServer("unused.pltg", background=True)
        signalled = threading.Event()
        server._request_shutdown = signalled.set
        result = server.dispatch({"action": "shutdown"})
        self.assertTrue(result["ok"])
        self.assertIn("shutting down", result["text"])
        # The ack must come back before the signal fires (Timer delay)
        self.assertTrue(signalled.wait(timeout=2))

    def test_ping_reports_pid_and_pltg(self):
        server = bench_cli.BenchServer("some.pltg", background=True)
        result = server.dispatch({"action": "ping"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], os.getpid())
        self.assertEqual(result["pltg"], "some.pltg")


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pgreg"))
        self._orig = bench_cli.REGISTRY_PATH
        bench_cli.REGISTRY_PATH = self.dir / "daemons.json"

    def tearDown(self):
        bench_cli.REGISTRY_PATH = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_add_load_remove_roundtrip(self):
        _registry_add("/tmp/a.sock", 111, "/w/a.pltg")
        _registry_add("/tmp/b.sock", 222, "/w/b.pltg")
        entries = _registry_load()
        self.assertEqual(len(entries), 2)
        self.assertEqual({e["pid"] for e in entries}, {111, 222})
        _registry_remove("/tmp/a.sock")
        entries = _registry_load()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["sock"], "/tmp/b.sock")

    def test_re_add_same_socket_replaces(self):
        _registry_add("/tmp/a.sock", 111, "/w/a.pltg")
        _registry_add("/tmp/a.sock", 333, "/w/a.pltg")
        entries = _registry_load()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["pid"], 333)

    def test_missing_or_corrupt_registry_is_empty(self):
        self.assertEqual(_registry_load(), [])
        bench_cli.REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        bench_cli.REGISTRY_PATH.write_text("{not json")
        self.assertEqual(_registry_load(), [])


class TestPidAlive(unittest.TestCase):
    def test_own_pid_is_alive(self):
        self.assertTrue(_pid_alive(os.getpid()))

    def test_impossible_pid_is_dead(self):
        self.assertFalse(_pid_alive(2**22 + 1))


if __name__ == "__main__":
    unittest.main()
