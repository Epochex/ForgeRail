"""Deterministic, evidence-bounded diagnostics; no model or command execution."""
from __future__ import annotations

import http.client
import queue
import re
import socket
import threading
import time
from urllib.parse import urlsplit


def _redact(text):
    text = re.sub(r"(?i)\b(token|password|secret|api[_-]?key|authorization)\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+", r"\1=[REDACTED]", text)
    return re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", text)


def diagnose(log: str, stage="build") -> dict:
    rules = [
        ("license", r"licen[cs]e|licensing", "Check local Unity activation with a real preflight build"),
        ("disk", r"no space left|disk full|not enough space|insufficient disk", "Check available workspace and output disk space"),
        ("tool_missing", r"executable not found|no such file|not recognized as|command not found", "Check the configured executable and node capabilities"),
        ("asset_check", r"missing_meta|duplicate_guid|invalid_guid|case_conflict|asset.check.*fail|missing script", "Inspect the resource report and named asset in Unity"),
        ("compilation", r"error CS\d+|compilation failed|compiler error", "Open the first compiler error and its source location"),
        ("timeout", r"timed? out|timeout|deadline exceeded", "Check the last completed phase and process termination evidence"),
        ("artifact_integrity", r"sha256.*mismatch|checksum.*mismatch|artifact.*(?:corrupt|mismatch|invalid)|manifest.*mismatch", "Rebuild and reverify artifact bytes and manifest identity"),
        ("network", r"connection refused|connection reset|name resolution|dns.*fail|network unreachable|HTTP [45]\d\d", "Probe DNS, TCP and HTTP separately from the affected node"),
    ]
    lines = [_redact(line[:2000]) for line in str(log).splitlines()[-500:]]
    for category, pattern, action in rules:
        evidence = [line for line in lines if re.search(pattern, line, re.I)][:10]
        if evidence:
            return {"stage": stage, "category": category, "evidence": evidence,
                    "next_steps": [action], "uncertainty": ["Classification is a log heuristic; verify the original stage report"]}
    return {"stage": stage, "category": "unknown", "evidence": lines[-10:] or ["No log evidence available"],
            "next_steps": ["Inspect the exit code, structured stage report and preceding log context"],
            "uncertainty": ["No supported failure pattern matched"]}


def probe_network(host, port, url=None, timeout=2) -> dict:
    """One shared deadline for DNS/TCP/HTTP; HTTP bypasses ambient proxies.

    The system resolver has no portable timeout. A daemon isolates a blocked
    getaddrinfo so the caller still returns within its deadline.
    """
    if timeout <= 0 or not 0 < int(port) < 65536:
        raise ValueError("positive timeout and valid TCP port required")
    start = time.monotonic()
    result = {"passed": False, "failed_layer": None, "dns": {"passed": None},
              "tcp": {"passed": None}, "http": {"passed": None}, "duration": 0.0}
    def remaining():
        return max(.001, timeout - (time.monotonic() - start))
    def failure(layer, error):
        result[layer] = {"passed": False, "error": _redact(str(error))}
        result["failed_layer"] = layer
        result["duration"] = time.monotonic() - start
        return result
    resolved = queue.Queue(maxsize=1)
    def resolve():
        try:
            resolved.put((socket.getaddrinfo(host, port, type=socket.SOCK_STREAM), None))
        except OSError as error:
            resolved.put((None, error))
    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses, error = resolved.get(timeout=remaining())
    except queue.Empty:
        return failure("dns", "DNS resolution timed out")
    if error:
        return failure("dns", error)
    result["dns"] = {"passed": True, "addresses": sorted({address[4][0] for address in addresses})}
    connected = None
    connected_family = None
    last_error = "No resolved TCP address"
    for family, socktype, proto, _, address in addresses:
        if time.monotonic() - start >= timeout:
            break
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(remaining())
            sock.connect(address)
            connected = address
            connected_family = family
            break
        except OSError as error:
            last_error = error
        finally:
            sock.close()
    if connected is None:
        return failure("tcp", last_error)
    result["tcp"] = {"passed": True, "address": connected[0], "port": int(port)}
    if url:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != host or (parsed.port or (443 if parsed.scheme == "https" else 80)) != int(port) or parsed.username:
            return failure("http", "HTTP URL must match the probed host and port without credentials")
        connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(host, int(port), timeout=remaining())
        expired = threading.Event()
        def interrupt_http():
            expired.set()
            sock = connection.sock
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        watchdog = threading.Timer(remaining(), interrupt_http)
        watchdog.daemon = True
        watchdog.start()
        try:
            # Reuse resolved addresses, avoiding an unbounded second DNS lookup.
            def connect_resolved():
                sock = socket.socket(connected_family, socket.SOCK_STREAM)
                try:
                    sock.settimeout(remaining())
                    sock.connect(connected)
                    return sock
                except BaseException:
                    sock.close()
                    raise
            connection._create_connection = lambda *args, **kwargs: connect_resolved()
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path)
            response = connection.getresponse()
            if expired.is_set():
                return failure("http", "HTTP response deadline exceeded")
            result["http"] = {"passed": 200 <= response.status < 400, "status": response.status}
            if not result["http"]["passed"]:
                result["failed_layer"] = "http"
                result["duration"] = time.monotonic() - start
                return result
        except (OSError, http.client.HTTPException) as error:
            return failure("http", error)
        finally:
            watchdog.cancel()
            connection.close()
    result["passed"] = True
    result["duration"] = time.monotonic() - start
    return result
