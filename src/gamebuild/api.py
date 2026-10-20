"""Authenticated local control-plane HTTP boundary."""
import hmac
import json
from pathlib import Path
import uuid
import zipfile

from fastapi import FastAPI, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StrictBool

from .store import Store, Conflict
from .artifacts import MAX_BYTES


class StrictBody(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')

class SubmitBody(StrictBody):
    request: dict
    key: StrictStr=Field(min_length=1,max_length=200)

class HeartbeatBody(StrictBody):
    worker: StrictStr=Field(min_length=1,max_length=100)
    capabilities: list[StrictStr]=Field(min_length=1,max_length=100)
    slots: int=Field(default=1,ge=1,le=8)

class ClaimBody(StrictBody):
    worker: StrictStr=Field(min_length=1,max_length=100)
    lease_seconds: int=Field(default=30,ge=1,le=900)

class OwnerBody(StrictBody):
    worker: StrictStr=Field(min_length=1,max_length=100)
    token: StrictStr=Field(min_length=1,max_length=100)

class RenewBody(OwnerBody):
    seconds: int=Field(default=30,ge=1,le=900)

class ReportBody(OwnerBody):
    state: StrictStr
    detail: StrictStr|None=None

class ReleaseBody(StrictBody):
    artifact_id: StrictStr
    channel: StrictStr

class AdvanceBody(StrictBody):
    passed: StrictBool

class ObservationBody(StrictBody):
    worker: StrictStr
    validation_id: StrictStr
    artifact_id: StrictStr
    sha256: StrictStr
    receipt: dict


def create_app(root: Path, token: str) -> FastAPI:
    if not token: raise ValueError("an explicit local API token is required")
    app = FastAPI(title="ForgeRail", docs_url=None, redoc_url=None)
    store = Store(root); app.state.store = store

    @app.exception_handler(Conflict)
    async def conflict(_, exc): return JSONResponse({"error": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(_, exc): return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(zipfile.BadZipFile)
    async def malformed_zip(_, exc): return JSONResponse({'error':'malformed ZIP package'},status_code=400)

    @app.exception_handler(KeyError)
    async def missing(_, exc): return JSONResponse({"error": "record not found"}, status_code=404)

    def auth(request: Request):
        value = request.headers.get("Authorization", "")
        if not hmac.compare_digest(value, "Bearer " + token): raise HTTPException(401, "authentication required")

    @app.get("/health")
    def health(): return {"ok": True, "service": "gamebuild"}

    @app.get("/v1/jobs", dependencies=[Depends(auth)])
    def jobs(): return store.jobs()

    @app.post("/v1/jobs", dependencies=[Depends(auth)])
    def submit(body: SubmitBody): return store.submit(body.request, body.key)

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(auth)])
    def status(job_id: str): return store.get(job_id)

    @app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(auth)])
    def cancel(job_id: str): return store.cancel(job_id)

    @app.post("/v1/workers/heartbeat", dependencies=[Depends(auth)])
    def heartbeat(body: HeartbeatBody): return store.heartbeat(body.worker, body.capabilities, body.slots)

    @app.post("/v1/workers/claim", dependencies=[Depends(auth)])
    def claim(body: ClaimBody): return store.claim(body.worker, body.lease_seconds)

    @app.post("/v1/attempts/{job_id}/renew", dependencies=[Depends(auth)])
    def renew(job_id: str, body: RenewBody): return store.renew(job_id, body.worker, body.token, body.seconds)

    @app.post("/v1/attempts/{job_id}/report", dependencies=[Depends(auth)])
    def report(job_id: str, body: ReportBody): return store.report(job_id, body.worker, body.token, body.state, body.detail)

    @app.post("/v1/attempts/{job_id}/artifact", dependencies=[Depends(auth)])
    async def artifact(job_id: str, file: UploadFile = File(...), manifest: str = Form(...), worker: str = Form(...), token: str = Form(...)):
        if len(manifest) > 4 * 1024 * 1024: raise ValueError("manifest too large")
        path = store.root / "staging" / ("upload-" + uuid.uuid4().hex)
        try:
            total = 0
            with path.open("wb") as f:
                while block := await file.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_BYTES: raise ValueError("upload size limit exceeded")
                    f.write(block)
            result = store.commit_artifact(job_id, worker, token, path, json.loads(manifest))
            return {k: v for k, v in result.items() if k != "path"}
        finally:
            path.unlink(missing_ok=True); await file.close()

    @app.get("/v1/artifacts/{artifact_id}", dependencies=[Depends(auth)])
    def get_artifact(artifact_id: str):
        a = store.artifact(artifact_id)
        return {k: v for k, v in a.items() if k != "path"}

    @app.get("/v1/artifacts/{artifact_id}/download", dependencies=[Depends(auth)])
    def download(artifact_id: str): return FileResponse(store.artifact(artifact_id)["path"], media_type="application/zip")

    @app.post("/v1/releases", dependencies=[Depends(auth)])
    def release(body: ReleaseBody): return store.release(body.artifact_id, body.channel)

    @app.post("/v1/releases/{rid}/advance", dependencies=[Depends(auth)])
    def advance(rid: str, body: AdvanceBody): return store.advance(rid, body.passed)

    @app.post('/v1/releases/{rid}/observations',dependencies=[Depends(auth)])
    def observation(rid: str,body: ObservationBody):
        return store.observe(rid,body.worker,body.validation_id,body.artifact_id,body.sha256,body.receipt)

    @app.post("/v1/releases/{rid}/rollback", dependencies=[Depends(auth)])
    def rollback(rid: str): return store.rollback(rid)

    @app.get("/v1/events", dependencies=[Depends(auth)])
    def events(): return {"valid": store.verify_events(), "events": store.events()}
    return app
