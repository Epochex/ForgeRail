"""Durable local action journal; admission and state transitions are transactional."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .context import confined
from .sanitize import clean_text

NEXT = {'created': 'prepare', 'prepared': 'inject', 'injected': 'execute',
        'reproduced': 'diagnose', 'diagnosed': 'repair', 'repaired': 'verify'}
PHASE = {'prepare': 'prepared', 'inject': 'injected', 'execute': 'reproduced',
         'diagnose': 'diagnosed', 'repair': 'repaired', 'verify': 'verified'}


class LabConflict(ValueError):
    pass


class Journal:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'lab.sqlite3'
        with self.connection() as c:
            c.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,case_id TEXT,variant TEXT,
                  phase TEXT,status TEXT,busy_action TEXT,created_at REAL,updated_at REAL);
                CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY,run_id TEXT,kind TEXT,
                  request_key TEXT,state TEXT,created_at REAL,finished_at REAL,result TEXT,error TEXT,
                  UNIQUE(run_id,request_key));
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,
                  action_id TEXT,body TEXT);
                CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,run_id TEXT,action_id TEXT,
                  path TEXT,size INTEGER,sha256 TEXT);
            ''')

    @contextmanager
    def connection(self, transaction=False):
        c = sqlite3.connect(self.db, timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            if transaction: c.execute('BEGIN IMMEDIATE')
            yield c
            if transaction: c.commit()
        except BaseException:
            if transaction: c.rollback()
            raise
        finally:
            c.close()

    def run_root(self, run_id):
        if not isinstance(run_id, str) or len(run_id) != 32 or any(x not in '0123456789abcdef' for x in run_id):
            raise KeyError('unknown run')
        return confined(self.root, 'runs/'+run_id)

    def create(self, case_id, variant):
        rid, now = uuid.uuid4().hex, time.time()
        self.run_root(rid).mkdir(parents=True)
        with self.connection(True) as c:
            c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',
                      (rid, case_id, variant, 'created', 'READY', None, now, now))
        return self.snapshot(rid)

    @staticmethod
    def _action(row):
        a = dict(row)
        a['result'] = json.loads(a['result']) if a['result'] else None
        return a

    def admit(self, rid, kind, request_key):
        if kind not in PHASE or not isinstance(request_key, str) or not 1 <= len(request_key) <= 100:
            raise ValueError('invalid registered action or request key')
        with self.connection(True) as c:
            r = c.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if not r: raise KeyError('unknown run')
            old = c.execute('SELECT * FROM actions WHERE run_id=? AND request_key=?', (rid, request_key)).fetchone()
            if old:
                if old['kind'] != kind: raise LabConflict('request key belongs to a different action')
                return self._action(old), False
            if r['busy_action']: raise LabConflict('this experiment already has an active action')
            if NEXT.get(r['phase']) != kind:
                raise LabConflict('next allowed action: '+str(NEXT.get(r['phase'], 'start a new experiment')))
            if c.execute("SELECT count(*) FROM actions WHERE state='RUNNING'").fetchone()[0] >= 2:
                raise LabConflict('two experiments are running; wait for one to finish')
            aid, now = uuid.uuid4().hex, time.time()
            c.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,NULL,NULL,NULL)',
                      (aid, rid, kind, request_key, 'RUNNING', now))
            c.execute("UPDATE runs SET busy_action=?,status='RUNNING',updated_at=? WHERE id=?", (aid, now, rid))
            return self._action(c.execute('SELECT * FROM actions WHERE id=?', (aid,)).fetchone()), True

    def action(self, aid):
        with self.connection() as c:
            row = c.execute('SELECT * FROM actions WHERE id=?', (aid,)).fetchone()
            if not row: raise KeyError('unknown action')
            return self._action(row)

    def event(self, rid, aid, body):
        with self.connection(True) as c:
            c.execute('INSERT INTO events(run_id,action_id,body) VALUES(?,?,?)',
                      (rid, aid, json.dumps(body, ensure_ascii=False, default=str)))

    def events(self, rid, after=0):
        with self.connection() as c:
            rows = c.execute('SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 1500', (rid, after)).fetchall()
            return [{**json.loads(r['body']), 'seq': r['seq'], 'action_id': r['action_id']} for r in rows]

    def finish(self, aid, state, result=None, error=None):
        with self.connection(True) as c:
            a = c.execute('SELECT * FROM actions WHERE id=?', (aid,)).fetchone()
            if not a: raise KeyError('unknown action')
            if a['state'] != 'RUNNING': return
            r = c.execute('SELECT * FROM runs WHERE id=?', (a['run_id'],)).fetchone()
            phase = PHASE[a['kind']] if state == 'SUCCEEDED' else r['phase']
            status = ('VERIFIED' if phase == 'verified' else 'READY') if state == 'SUCCEEDED' else state
            now = time.time()
            c.execute('UPDATE actions SET state=?,finished_at=?,result=?,error=? WHERE id=?',
                      (state, now, json.dumps(result, ensure_ascii=False, default=str) if result else None, error, aid))
            c.execute('UPDATE runs SET phase=?,status=?,busy_action=NULL,updated_at=? WHERE id=?',
                      (phase, status, now, a['run_id']))

    def snapshot(self, rid):
        self.run_root(rid)
        with self.connection() as c:
            row = c.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if not row: raise KeyError('unknown run')
            r = dict(row)
            r['actions'] = [self._action(x) for x in c.execute('SELECT * FROM actions WHERE run_id=? ORDER BY created_at', (rid,))]
            r['evidence'] = [dict(x) for x in c.execute('SELECT * FROM evidence WHERE run_id=? ORDER BY rowid', (rid,))]
        r['events'] = self.events(rid)
        r['allowed_actions'] = [NEXT[r['phase']]] if not r['busy_action'] and r['phase'] in NEXT else []
        r['execution_mode'] = 'lab'
        return r

    def runs(self):
        with self.connection() as c:
            return [dict(x) for x in c.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT 200')]

    def recover(self):
        with self.connection(True) as c:
            interrupted = [dict(r) for r in c.execute("SELECT * FROM actions WHERE state='RUNNING'")]
            now = time.time()
            c.execute("UPDATE actions SET state='INTERRUPTED',finished_at=?,error='service interrupted; retry this step' WHERE state='RUNNING'", (now,))
            c.execute("UPDATE runs SET busy_action=NULL,status='INTERRUPTED',updated_at=? WHERE busy_action IS NOT NULL", (now,))
        for action in interrupted:
            self.register_evidence(action['run_id'],action['id'])

    def register_evidence(self, rid, aid):
        root = self.run_root(rid)
        folder = confined(root, 'output/'+aid)
        if not folder.exists(): return
        with self.connection(True) as c:
            for p in folder.rglob('*'):
                if not p.is_file() or p.is_symlink() or p.stat().st_size > 8*1024*1024: continue
                if p.suffix.lower() not in ('.json','.log','.txt','.diff','.xml','.csv','.zip'): continue
                if any(x in p.name.lower() for x in ('credential','secret','.env','license')): continue
                relative = p.relative_to(root).as_posix()
                confined(root, relative)
                data = p.read_bytes()
                eid = hashlib.sha256((rid+relative).encode()).hexdigest()[:24]
                if c.execute('SELECT 1 FROM evidence WHERE id=?',(eid,)).fetchone(): continue
                if p.suffix.lower() != '.zip': data=clean_text(data.decode('utf-8',errors='replace'),[self.root]).encode('utf-8')
                public_relative = 'evidence/'+aid+'/'+p.relative_to(folder).as_posix()
                public = confined(root,public_relative)
                public.parent.mkdir(parents=True,exist_ok=True)
                public.write_bytes(data)
                c.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?,?)',
                          (eid, rid, aid, public_relative, len(data), hashlib.sha256(data).hexdigest()))

    def evidence(self, rid, eid):
        with self.connection() as c:
            r = c.execute('SELECT * FROM evidence WHERE run_id=? AND id=?', (rid, eid)).fetchone()
            if not r: raise KeyError('unknown evidence')
            item = dict(r)
        path = confined(self.run_root(rid), item['path'])
        if not path.is_file(): raise KeyError('evidence file missing')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise LabConflict('evidence changed after it was recorded')
        return item, path
