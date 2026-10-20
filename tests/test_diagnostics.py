import http.server
import socket
import threading
import time

import pytest


@pytest.mark.parametrize("log,category", [
    ("Unity executable not found", "tool_missing"),
    ("missing_meta Assets/foo.png", "asset_check"),
    ("error CS1002: ; expected", "compilation"),
    ("No valid Unity license found", "license"),
    ("process timed out", "timeout"),
    ("No space left on device", "disk"),
    ("Connection refused", "network"),
    ("artifact SHA256 mismatch", "artifact_integrity"),
    ("unrecognized failure", "unknown"),
])
def test_diagnostics_extract_evidence_and_action(log, category):
    from gamebuild.diagnostics import diagnose
    result = diagnose(log)
    assert result["category"] == category
    assert result["evidence"]
    assert result["next_steps"]
    assert result["uncertainty"]


def test_diagnostics_redact_credentials(tmp_path):
    from gamebuild.diagnostics import diagnose
    result = str(diagnose("Connection refused token=very-secret password=also-secret https://user:pass@example.org"))
    assert "very-secret" not in result
    assert "also-secret" not in result
    assert "user:pass" not in result


def test_network_refusal_reports_tcp_after_dns_success():
    from gamebuild.diagnostics import probe_network
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        result = probe_network("127.0.0.1", port, timeout=.2)
    assert result["passed"] is False
    assert result["failed_layer"] == "tcp"
    assert result["dns"]["passed"] is True
    assert result["tcp"]["passed"] is False


@pytest.mark.parametrize("status,delay,layer", [(200, 0, None), (503, 0, "http"), (200, .3, "http")])
def test_network_http_success_status_error_and_response_timeout(status, delay, layer):
    from gamebuild.diagnostics import probe_network
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(delay)
            try:
                self.send_response(status)
                self.end_headers()
            except OSError:
                pass
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        port = server.server_address[1]
        result = probe_network("127.0.0.1", port, f"http://127.0.0.1:{port}/", timeout=.1)
        assert result["failed_layer"] == layer
        assert result["passed"] is (layer is None)
        assert result["duration"] < 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_network_probe_deadline_bounds_slow_trickling_http_headers():
    from gamebuild.diagnostics import probe_network
    class Trickle(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                for byte in b"HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n":
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(.04)
            except OSError:
                pass
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Trickle)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        port = server.server_address[1]
        result = probe_network("127.0.0.1", port, f"http://127.0.0.1:{port}/", timeout=.15)
        assert result["passed"] is False
        assert result["failed_layer"] == "http"
        assert result["duration"] < .6
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_network_http_uses_the_address_family_that_actually_connected():
    from gamebuild.diagnostics import probe_network
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        port = server.server_address[1]
        result = probe_network("localhost", port, f"http://localhost:{port}/", timeout=3)
        assert result["passed"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
