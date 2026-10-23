"""Owns bounded action subprocess trees, never user supplied commands."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import threading
import time

from gamebuild.runner import run_process
from gamebuild.worker import NodeLock
from .store import Journal


class LabService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = NodeLock(self.root/'service-lock')
        self.lock.__enter__()
        self.journal = Journal(root)
        self.journal.recover()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='forgerail-lab')
        self.active = {}
        self.mutex = threading.Lock()
        self.closed = False

    def submit(self, run_id, kind, request_key):
        with self.mutex:
            if self.closed: raise ValueError('service is stopping')
            action, created = self.journal.admit(run_id, kind, request_key)
            if created:
                stop = threading.Event()
                self.active[action['id']] = stop
                self.pool.submit(self._execute, action, stop)
            return action

    def _execute(self, action, stop):
        aid, rid = action['id'], action['run_id']
        log = self.journal.run_root(rid)/'output'/aid/'executor.log'
        requested_at = None
        started = time.monotonic()
        deadline_expired = False
        def force_stop():
            nonlocal requested_at, deadline_expired
            if time.monotonic()-started >= 86 and not stop.is_set():
                deadline_expired = True
                self._request_cancel(rid,aid,stop)
            if not stop.is_set(): return False
            if requested_at is None: requested_at = time.monotonic()
            return time.monotonic()-requested_at >= 3
        try:
            result = run_process([sys.executable, '-m', 'gamebuild.lab.runner', '--root', str(self.root), '--action', aid,
                                  '--parent', str(os.getpid())],
                                 Path(__file__).resolve().parents[3], log, timeout=90, cancel=force_stop)
            self.journal.register_evidence(rid, aid)
            if stop.is_set(): self.journal.finish(aid, 'FAILED' if deadline_expired else 'CANCELLED',
                                                  error='操作超过时限，已清理执行进程' if deadline_expired else '用户停止了本次操作；证据已保留，可重试当前步骤')
            elif result['exit_code'] != 0 or result['timed_out']:
                self.journal.finish(aid, 'FAILED', error='执行进程异常或超过 90 秒限制；请查看 executor.log')
            else:
                outcome_path = log.parent/'outcome.json'
                if outcome_path.is_file():
                    outcome = json.loads(outcome_path.read_text(encoding='utf-8'))
                    self.journal.finish(aid, outcome['state'], outcome.get('result'), outcome.get('error'))
                else:
                    self.journal.finish(aid, 'FAILED', error='执行进程未写入完成回执')
        except Exception as exc:
            self.journal.finish(aid, 'FAILED', error=type(exc).__name__+': '+str(exc)[:800])
        finally:
            self.journal.register_evidence(rid, aid)
            with self.mutex: self.active.pop(aid, None)

    def cancel(self, rid):
        run = self.journal.snapshot(rid)
        with self.mutex:
            stop = self.active.get(run['busy_action'])
            if stop:
                self._request_cancel(rid,run['busy_action'],stop)
        return {'requested': bool(stop), 'run_id': rid}

    def close(self):
        with self.mutex:
            self.closed = True
            for aid,stop in self.active.items():
                self._request_cancel(self.journal.action(aid)['run_id'],aid,stop)
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.lock.__exit__(None, None, None)

    def _request_cancel(self,rid,aid,stop):
        marker = self.journal.run_root(rid)/'output'/aid/'cancel.requested'
        marker.parent.mkdir(parents=True,exist_ok=True)
        marker.touch()
        stop.set()
