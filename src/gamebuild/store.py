"""SQLite is the single authority for ownership, publication and audit."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid
import zipfile

from .artifacts import verify_package, digest

ACTIVE = ("leased", "building", "verifying")
TERMINAL = ("succeeded", "failed", "cancelled")


class Conflict(RuntimeError):
    pass


def encoded(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class Store:
    def __init__(self, root: Path, clock=time.time):
        self.root = Path(root).resolve(); self.clock = clock
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        (self.root / "staging").mkdir(exist_ok=True)
        self.db = self.root / "state.sqlite3"
        with self._connect() as c:
            c.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, idem TEXT UNIQUE, request TEXT,
                state TEXT, attempt INTEGER, worker TEXT, token TEXT, expiry REAL, artifact TEXT,
                detail TEXT, created REAL);
              CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY, capabilities TEXT, slots INTEGER, seen REAL);
              CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, job TEXT UNIQUE, path TEXT, manifest TEXT);
              CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY, artifact TEXT, channel TEXT,
                phase TEXT, previous TEXT, windows INTEGER);
              CREATE TABLE IF NOT EXISTS channels(name TEXT PRIMARY KEY, artifact TEXT);
              CREATE TABLE IF NOT EXISTS observations(release TEXT,phase TEXT,validation TEXT,worker TEXT,
                artifact TEXT,digest TEXT,passed INTEGER,observed REAL,receipt TEXT,
                PRIMARY KEY(release,phase,validation));
              CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT,
                kind TEXT, payload TEXT, previous TEXT, checksum TEXT);
            """)

    def _connection(self):
        c = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        return c

    @contextmanager
    def _connect(self):
        c=self._connection()
        try: yield c
        finally: c.close()

    @contextmanager
    def _tx(self):
        c = self._connection()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback(); raise
        finally: c.close()

    def _event(self, c, job, kind, payload=None):
        prev = c.execute("SELECT checksum FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        prev = prev[0] if prev else "0" * 64
        data = encoded({"at": self.clock(), "detail": payload or {}})
        checksum = hashlib.sha256(encoded([job, kind, data, prev]).encode()).hexdigest()
        c.execute("INSERT INTO events(job,kind,payload,previous,checksum) VALUES(?,?,?,?,?)", (job, kind, data, prev, checksum))

    @staticmethod
    def _job(row):
        if row is None: raise KeyError("job not found")
        d = dict(row); d["job_id"] = d.pop("id"); d["request"] = json.loads(d["request"])
        d["artifact_id"] = d.pop("artifact")
        return d

    def _recover(self, c):
        rows = c.execute("SELECT * FROM jobs WHERE state IN ('leased','building','verifying') AND expiry<=?", (self.clock(),)).fetchall()
        for row in rows:
            state = "failed" if row["attempt"] >= 2 else "queued"
            c.execute("UPDATE jobs SET state=?,token=NULL,worker=NULL,expiry=NULL,detail=? WHERE id=?", (state, "lease_expired", row["id"]))
            self._event(c, row["id"], "lease_expired", {"state": state, "attempt": row["attempt"]})

    def _owner(self, c, job_id, worker, token):
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if (not row or row["state"] not in ACTIVE or row["worker"] != worker
                or row["token"] != token or row["expiry"] <= self.clock()):
            raise Conflict("stale, expired or cancelled execution")
        return row

    def submit(self, request: dict, key: str) -> dict:
        if not isinstance(request,dict) or any(not isinstance(request.get(k),str) for k in ('project_id','commit_sha','input_digest','adapter','target','branch')):
            raise ValueError('build identity fields must be strings')
        if (not isinstance(key, str) or not 1 <= len(key) <= 200
                or not re.fullmatch(r"[a-f0-9]{40}", request.get("commit_sha", ""))
                or not re.fullmatch(r"[a-f0-9]{64}", request.get("input_digest", ""))
                or request.get("adapter") not in ("lab", "unity")
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request.get("project_id", ""))):
            raise ValueError("invalid immutable build inputs")
        value = encoded(request)
        if request['adapter'] == 'unity' and (not isinstance(request.get('unity_version'),str) or not re.fullmatch(r'\d+\.\d+\.\d+[abfp]\d+', request.get('unity_version','')) or request.get('target') != 'StandaloneWindows64'):
            raise ValueError('Unity input must pin an exact Editor version and supported target')
        with self._tx() as c:
            old = c.execute("SELECT * FROM jobs WHERE idem=?", (key,)).fetchone()
            if old:
                if old["request"] != value: raise Conflict("idempotency key conflicts with immutable input")
                return self._job(old)
            job = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self.clock())) + "-" + request["commit_sha"][:8] + "-" + uuid.uuid4().hex[:10]
            c.execute("INSERT INTO jobs VALUES(?,?,?,'queued',0,NULL,NULL,NULL,NULL,NULL,?)", (job, key, value, self.clock()))
            self._event(c, job, "submitted", {"input_digest": request["input_digest"]})
            return self._job(c.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone())

    def get(self, job_id):
        with self._tx() as c:
            self._recover(c)
            return self._job(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def jobs(self):
        with self._tx() as c:
            self._recover(c)
            return [self._job(r) for r in c.execute("SELECT * FROM jobs ORDER BY created")]

    def heartbeat(self, worker: str, capabilities: list[str], slots=1):
        if (not isinstance(worker,str) or not worker or len(worker) > 100 or type(slots) is not int or not 1 <= slots <= 8
                or not isinstance(capabilities,list) or not capabilities or any(not isinstance(x,str) or not 1<=len(x)<=150 for x in capabilities)):
            raise ValueError("invalid worker")
        with self._tx() as c:
            c.execute("INSERT INTO workers VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET capabilities=excluded.capabilities,slots=excluded.slots,seen=excluded.seen",
                      (worker, encoded(capabilities), slots, self.clock()))
        return {"worker_id": worker, "slots": slots, "capabilities": capabilities}

    def claim(self, worker: str, lease_seconds=30):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 900: raise ValueError("invalid lease duration")
        with self._tx() as c:
            self._recover(c)
            w = c.execute("SELECT * FROM workers WHERE id=?", (worker,)).fetchone()
            if not w or w["seen"] + 90 < self.clock(): return None
            count = c.execute("SELECT count(*) FROM jobs WHERE worker=? AND state IN ('leased','building','verifying')", (worker,)).fetchone()[0]
            if count >= w["slots"]: return None
            caps = json.loads(w["capabilities"])
            for r in c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created,id").fetchall():
                request=json.loads(r["request"])
                if request["adapter"] not in caps: continue
                if any(x.startswith('project:') for x in caps) and ('project:'+request['project_id']) not in caps: continue
                if request['adapter']=='unity' and (('unity:'+request['unity_version']) not in caps or ('target:'+request['target']) not in caps): continue
                token = uuid.uuid4().hex
                c.execute("UPDATE jobs SET state='leased',attempt=attempt+1,worker=?,token=?,expiry=? WHERE id=?", (worker, token, self.clock() + lease_seconds, r["id"]))
                self._event(c, r["id"], "claimed", {"worker": worker, "attempt": r["attempt"] + 1})
                return self._job(c.execute("SELECT * FROM jobs WHERE id=?", (r["id"],)).fetchone())
            return None

    def renew(self, job_id, worker, token, seconds=30):
        if not 1 <= seconds <= 900: raise ValueError("invalid renewal")
        with self._tx() as c:
            self._owner(c, job_id, worker, token)
            c.execute("UPDATE jobs SET expiry=? WHERE id=?", (self.clock() + seconds, job_id))
            return {"renewed": True}

    def report(self, job_id, worker, token, state, detail=None):
        with self._tx() as c:
            old = self._owner(c, job_id, worker, token)
            allowed = {"leased": ("building", "failed"), "building": ("verifying", "failed"), "verifying": ("failed",)}
            if state not in allowed[old["state"]]: raise Conflict("illegal state transition")
            c.execute("UPDATE jobs SET state=?,detail=? WHERE id=?", (state, str(detail or "")[:4000], job_id))
            self._event(c, job_id, state)
            return self._job(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def cancel(self, job_id):
        with self._tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row: raise KeyError("job not found")
            if row["state"] not in TERMINAL:
                c.execute("UPDATE jobs SET state='cancelled',token=NULL WHERE id=?", (job_id,))
                self._event(c, job_id, "cancelled")
            return self._job(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def commit_artifact(self, job_id, worker, token, package: Path, manifest: dict):
        with self._tx() as c:
            row = self._owner(c, job_id, worker, token)
            if row["state"] != "verifying": raise Conflict("artifact requires verification stage")
            request = json.loads(row["request"])
        # Copy into our staging area before validating, so caller mutations cannot change admitted bytes.
        stage = self.root / "staging" / (uuid.uuid4().hex + ".zip")
        try:
            shutil.copyfile(package, stage)
            verify_package(stage, manifest)
            expected = {"build_id": job_id, "commit_sha": request["commit_sha"], "input_digest": request["input_digest"], "adapter": request["adapter"]}
            if any(manifest.get(k) != v for k, v in expected.items()): raise ValueError("manifest job identity mismatch")
            with zipfile.ZipFile(stage) as z:
                for name in ("build-info.json", "smoke.json", "build-report.json"):
                    if name not in z.namelist() or z.getinfo(name).file_size > 1024 * 1024: raise ValueError("missing or oversized verification report")
                smoke = json.loads(z.read("smoke.json")); report = json.loads(z.read("build-report.json"))
                if not isinstance(smoke,dict) or not isinstance(report,dict): raise ValueError('malformed verification reports')
                if any(smoke.get(k) != v for k, v in expected.items()) or smoke.get("asset_loaded") is not True:
                    raise ValueError("runtime receipt mismatch")
                if report.get("result") != "Succeeded" or report.get("adapter") != request["adapter"]: raise ValueError("build report failed")
                if request['adapter']=='unity':
                    info=json.loads(z.read('build-info.json'))
                    pinned={**expected,'target':request['target'],'configuration':request.get('configuration','Development'),'unity_version':request['unity_version']}
                    for obj in (info,smoke,report):
                        if any(obj.get(k)!=v for k,v in pinned.items()): raise ValueError('Unity report or receipt identity mismatch')
                    if smoke.get('status')!='passed' or report.get('status')!='passed': raise ValueError('Unity verification status failed')
                    inventory={f['path']:f for f in manifest['files']}
                    required=('player/GameBuildLab.exe','bundles/demo','player/GameBuildLab_Data/StreamingAssets/GameBuild/demo','player/GameBuildLab_Data/StreamingAssets/GameBuild/build-info.json')
                    if any(name not in inventory or not inventory[name]['size'] for name in required): raise ValueError('Unity Player or bundle missing')
                    for name in ('bundles/demo','player/GameBuildLab_Data/StreamingAssets/GameBuild/demo'):
                        if inventory[name]['sha256']!=info.get('bundle_sha256'): raise ValueError('Unity bundle digest mismatch')
                    for obj in (smoke,report):
                        if obj.get('bundle_sha256')!=info.get('bundle_sha256'): raise ValueError('Unity reported bundle digest mismatch')
                    if smoke.get('config_sha256')!=info.get('config_sha256') or not re.fullmatch('[a-f0-9]{64}',info.get('config_sha256','')):
                        raise ValueError('Unity config digest mismatch')
                    embedded=json.loads(z.read(required[-1]))
                    if embedded!=info: raise ValueError('embedded Player build identity mismatch')
            blob = self.root / "blobs" / (manifest["sha256"] + ".zip")
            with self._tx() as c:
                self._owner(c, job_id, worker, token)
                if blob.exists() and digest(blob) != manifest["sha256"]: raise ValueError("existing blob corrupted")
                if not blob.exists(): os.replace(stage, blob)
                aid = "artifact-" + uuid.uuid4().hex
                c.execute("INSERT INTO artifacts VALUES(?,?,?,?)", (aid, job_id, str(blob), encoded(manifest)))
                c.execute("UPDATE jobs SET state='succeeded',artifact=?,token=NULL,expiry=NULL WHERE id=?", (aid, job_id))
                self._event(c, job_id, "succeeded", {"artifact_id": aid, "sha256": manifest["sha256"]})
                return {"artifact_id": aid, "path": str(blob), "manifest": manifest, "job_id": job_id}
        finally: stage.unlink(missing_ok=True)

    def artifacts(self):
        with self._connect() as c: return [{**dict(r), "artifact_id": r["id"], "manifest": json.loads(r["manifest"])} for r in c.execute("SELECT * FROM artifacts")]

    def artifact(self, artifact_id):
        for a in self.artifacts():
            if a["artifact_id"] == artifact_id: return a
        raise KeyError("artifact not found")

    def events(self, job_id=None):
        with self._connect() as c:
            rows = c.execute("SELECT * FROM events" + (" WHERE job=?" if job_id else "") + " ORDER BY seq", (job_id,) if job_id else ())
            return [dict(r) for r in rows]

    def verify_events(self):
        previous = "0" * 64
        for e in self.events():
            want = hashlib.sha256(encoded([e["job"], e["kind"], e["payload"], previous]).encode()).hexdigest()
            if e["previous"] != previous or e["checksum"] != want: return False
            previous = want
        return True

    def release(self, artifact_id, channel):
        if not isinstance(channel,str) or not re.fullmatch(r"[a-z0-9_-]{1,50}", channel): raise ValueError("invalid channel")
        a = self.artifact(artifact_id); verify_package(Path(a["path"]), a["manifest"])
        rid = "release-" + uuid.uuid4().hex
        with self._tx() as c:
            old = c.execute("SELECT artifact FROM channels WHERE name=?", (channel,)).fetchone()
            c.execute("INSERT INTO releases VALUES(?,?,?,'shadow',?,0)", (rid, artifact_id, channel, old[0] if old else None))
            self._event(c, a["job"], "release_shadow", {"release_id": rid})
            return dict(c.execute("SELECT *,id AS release_id FROM releases WHERE id=?", (rid,)).fetchone())

    def advance(self, release_id, passed: bool):
        with self._tx() as c:
            r = c.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
            if not r: raise KeyError("release not found")
            if not passed or r["phase"] not in ("shadow", "canary"): raise Conflict("release validation window failed or already terminal")
            observations=c.execute('SELECT * FROM observations WHERE release=? AND phase=?',(release_id,r['phase'])).fetchall()
            if (len(observations)<2 or len({x['worker'] for x in observations})<2 or any(not x['passed'] for x in observations)
                    or max(x['observed'] for x in observations)-min(x['observed'] for x in observations)<1.0):
                raise Conflict('release requires two distinct validation nodes over at least one second')
            phase = "canary" if r["phase"] == "shadow" else "stable"
            if phase == "stable":
                current = c.execute("SELECT artifact FROM channels WHERE name=?", (r["channel"],)).fetchone()
                current = current[0] if current else None
                if current != r["previous"]: raise Conflict("channel changed since release proposal")
                a = c.execute("SELECT * FROM artifacts WHERE id=?", (r["artifact"],)).fetchone()
                verify_package(Path(a["path"]), json.loads(a["manifest"]))
                c.execute("INSERT INTO channels VALUES(?,?) ON CONFLICT(name) DO UPDATE SET artifact=excluded.artifact", (r["channel"], r["artifact"]))
            c.execute("UPDATE releases SET phase=?,windows=windows+1 WHERE id=?", (phase, release_id))
            self._event(c, None, "release_" + phase, {"release_id": release_id})
            return {"release_id": release_id, "phase": phase}

    def observe(self, release_id, worker, validation_id, artifact_id, sha256, receipt):
        if not isinstance(validation_id,str) or not 1<=len(validation_id)<=100 or not isinstance(receipt,dict): raise ValueError('invalid validation observation')
        with self._tx() as c:
            r=c.execute('SELECT * FROM releases WHERE id=?',(release_id,)).fetchone()
            if not r: raise KeyError('release not found')
            if r['phase'] not in ('shadow','canary'): raise Conflict('release is not observing')
            w=c.execute('SELECT * FROM workers WHERE id=?',(worker,)).fetchone()
            if not w or w['seen']+90<self.clock() or 'validate' not in json.loads(w['capabilities']): raise Conflict('validation node is not live or capable')
            a=c.execute('SELECT * FROM artifacts WHERE id=?',(r['artifact'],)).fetchone()
            manifest=json.loads(a['manifest'])
            if artifact_id!=r['artifact'] or sha256!=manifest['sha256']: raise ValueError('validation is bound to another artifact')
            previous=c.execute('SELECT * FROM observations WHERE release=? AND phase=? AND validation=?',(release_id,r['phase'],validation_id)).fetchone()
            if previous:
                if previous['worker']!=worker or previous['receipt']!=encoded(receipt): raise Conflict('validation id reused with different evidence')
                return {'passed':bool(previous['passed']),'idempotent':True}
            with zipfile.ZipFile(a['path']) as z: expected=json.loads(z.read('smoke.json'))
            keys=('build_id','commit_sha','input_digest','adapter','target','configuration','unity_version','bundle_sha256','config_sha256')
            valid=receipt.get('asset_loaded') is True and all(receipt.get(k)==expected.get(k) for k in keys)
            if manifest['adapter']=='unity': valid=valid and receipt.get('status')=='passed'
            c.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)',(release_id,r['phase'],validation_id,worker,artifact_id,sha256,int(valid),self.clock(),encoded(receipt)))
            self._event(c,a['job'],'release_validation_passed' if valid else 'release_validation_failed',{'release_id':release_id,'phase':r['phase'],'worker':worker,'validation_id':validation_id,'sha256':sha256})
            if not valid: c.execute("UPDATE releases SET phase='rejected' WHERE id=?",(release_id,))
            return {'passed':valid,'validation_id':validation_id,'phase':r['phase'] if valid else 'rejected'}

    def channel(self, name):
        with self._connect() as c:
            r = c.execute("SELECT artifact AS artifact_id FROM channels WHERE name=?", (name,)).fetchone()
            return dict(r) if r else {"artifact_id": None}

    def rollback(self, release_id):
        with self._tx() as c:
            r = c.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
            if not r: raise KeyError("release not found")
            if r["phase"] == "rolled_back": return {"release_id": release_id, "phase": "rolled_back"}
            current = c.execute("SELECT artifact FROM channels WHERE name=?", (r["channel"],)).fetchone()
            if r["phase"] == "stable" and (not current or current[0] != r["artifact"]): raise Conflict("cannot rollback a superseded release")
            if r["phase"] == "stable":
                if r["previous"]:
                    a = c.execute("SELECT * FROM artifacts WHERE id=?", (r["previous"],)).fetchone()
                    verify_package(Path(a["path"]), json.loads(a["manifest"]))
                    c.execute("UPDATE channels SET artifact=? WHERE name=?", (r["previous"], r["channel"]))
                else: c.execute("DELETE FROM channels WHERE name=?", (r["channel"],))
            c.execute("UPDATE releases SET phase='rolled_back' WHERE id=?", (release_id,))
            self._event(c, None, "rolled_back", {"release_id": release_id})
            return {"release_id": release_id, "phase": "rolled_back"}
