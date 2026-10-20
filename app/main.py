from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import BackgroundTasks, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .core import (CONNECTORS, DB_PATH, Destination, ConnectorError, Rendition, connect_db, db_session,
                   fingerprint, make_manifest, now, perform_publish, verify_signature)

app = FastAPI(title="IncuBrix Long-Tail Connector Service", version="0.1.0")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
logger = logging.getLogger("incubrix")
PUBLISH_LOCK = threading.RLock()

SAMPLES = [
    {"id":"discourse-local","name":"Local Discourse simulation","platform_key":"discourse","url":"http://discourse.local","frequency_cap":5,"self_promo_allowed":True,"link_policy":"allowed","connection":{"mode":"simulation"}},
    {"id":"lemmy-local","name":"Local Lemmy simulation","platform_key":"lemmy","url":"http://lemmy.local","frequency_cap":5,"connection":{"mode":"simulation"}},
    {"id":"devto-sandbox","name":"Dev.to sandbox simulation","platform_key":"devto","url":"https://dev.to","frequency_cap":5,"connection":{"mode":"simulation"}},
    {"id":"ghost-local","name":"Local Ghost simulation","platform_key":"ghost","url":"http://ghost.local","frequency_cap":5,"connection":{"mode":"simulation"}},
    {"id":"partner-webhook","name":"Partner webhook simulation","platform_key":"signed_webhook","url":"https://partner.invalid","frequency_cap":5,"connection":{"mode":"simulation","secret_env":"WEBHOOK_SECRET"}},
    {"id":"assisted-community","name":"Manual community","platform_key":"assisted","url":"https://community.invalid/submit","automation_allowed":False,"frequency_cap":5,"connection":{"mode":"assisted","submit_url":"https://community.invalid/submit"}},
]


def load_destinations() -> None:
    source = Path(os.getenv("DESTINATIONS_FILE", "config/destinations.yaml"))
    values = yaml.safe_load(source.read_text(encoding="utf-8")) if source.exists() else SAMPLES
    with db_session() as db:
        for item in values:
            d = Destination.model_validate(item)
            db.execute("INSERT INTO destinations(id,config) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config", (d.id, d.model_dump_json()))


@app.on_event("startup")
def startup() -> None:
    load_destinations()


class CorrelationMiddleware:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        correlation = headers.get(b"x-correlation-id", str(uuid.uuid4()).encode()).decode(errors="replace")
        async def send_with_correlation(message):
            if message["type"] == "http.response.start":
                message["headers"].append((b"x-correlation-id", correlation.encode()))
                logger.info(json.dumps({"timestamp":now(),"level":"INFO","job_id":None,"correlation_id":correlation,"path":scope.get("path"),"status":message.get("status")}))
            await send(message)
        return await self.app(scope, receive, send_with_correlation)


app.add_middleware(CorrelationMiddleware)


@app.exception_handler(ConnectorError)
async def connector_error_handler(request: Request, exc: ConnectorError):
    codes = {"DEST_SPEC_VIOLATION":422,"DEST_RULE_FREQUENCY_CAP":429,"PLATFORM_RATE_LIMIT":429,"CONNECTION_AUTH_EXPIRED":401,
             "PLATFORM_CONTENT_REJECTED":422,"PLATFORM_QUOTA_EXHAUSTED":429,"PLATFORM_UNAVAILABLE":503,"CONNECTOR_DISABLED":409,
             "CONNECTOR_ASSISTED_ONLY":409,"IDEMPOTENCY_KEY_REUSED":409}
    return JSONResponse(exc.json(), status_code=codes.get(exc.code, 400))


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    violations = [{"field":".".join(str(part) for part in error["loc"]),"message":error["msg"]} for error in exc.errors()]
    return JSONResponse({"error":{"code":"DEST_SPEC_VIOLATION","message":"Request validation failed.","retryable":False,"details":{"violations":violations}}},status_code=422)


@app.exception_handler(ValidationError)
async def model_validation_handler(request: Request, exc: ValidationError):
    violations = [{"field":".".join(str(part) for part in error["loc"]),"message":error["msg"]} for error in exc.errors()]
    return JSONResponse({"error":{"code":"DEST_SPEC_VIOLATION","message":"Request validation failed.","retryable":False,"details":{"violations":violations}}},status_code=422)


def destination(destination_id: str) -> Destination:
    with db_session() as db:
        row = db.execute("SELECT config FROM destinations WHERE id=?", (destination_id,)).fetchone()
    if not row: raise ConnectorError("DEST_SPEC_VIOLATION", f"Unknown destination '{destination_id}'.", False, {"destination_id":destination_id})
    return Destination.model_validate_json(row["config"])


def connector(key: str):
    if key not in CONNECTORS: raise ConnectorError("DEST_SPEC_VIOLATION", f"Unknown connector '{key}'.")
    return CONNECTORS[key]


@app.get("/health")
@app.get("/api/v1/health")
def health(): return {"status":"ok"}


@app.get("/ready")
@app.get("/api/v1/ready")
def ready():
    with db_session() as db: db.execute("SELECT 1")
    return {"status":"ready"}


@app.get("/api/v1/connectors")
def list_connectors(): return [c.manifest() for c in CONNECTORS.values()]


@app.get("/api/v1/connectors/{connector_key}/manifest")
def get_manifest(connector_key: str): return connector(connector_key).manifest()


@app.get("/api/v1/destinations")
def list_destinations():
    with db_session() as db: rows = db.execute("SELECT config FROM destinations ORDER BY id").fetchall()
    return [json.loads(r["config"]) for r in rows]


@app.post("/api/v1/destinations")
def add_destination(payload: dict[str, Any]):
    d = Destination.model_validate(payload)
    connector(d.platform_key)
    with db_session() as db: db.execute("INSERT INTO destinations(id,config) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config", (d.id,d.model_dump_json()))
    return d.model_dump()


@app.post("/connector/v1/{connector_key}/{method}")
def connector_method(connector_key: str, method: str, body: dict[str, Any]):
    c = connector(connector_key)
    try:
        if method == "build_assist_pack":
            if not hasattr(c,"build_assist_pack"): raise ConnectorError("DEST_SPEC_VIOLATION", "This connector does not support assisted packs.")
            return c.build_assist_pack(Rendition.model_validate(body["rendition"]), Destination.model_validate(body["destination"]))
        d = Destination.model_validate(body["destination"]) if isinstance(body.get("destination"), dict) else destination(body["destination_id"])
        connection = body.get("connection", d.connection)
        if method in ("validate", "publish"):
            r = Rendition.model_validate(body["rendition"])
            if method == "validate": return c.validate(r,d,connection)
            key = body.get("idempotency_key")
            if not key: raise ConnectorError("DEST_SPEC_VIOLATION", "idempotency_key is required.")
            result = c.validate(r,d,connection)
            if not result["ok"]: raise ConnectorError("DEST_SPEC_VIOLATION","Content does not satisfy destination requirements.",False,{"violations":result["violations"]})
            return c.publish(r,d,connection,key)
        if method == "get_status": return c.get_status(body["platform_post_id"],connection)
        if method == "delete": return c.delete(body["platform_post_id"],connection)
        if method == "fetch_metrics": return c.fetch_metrics(body["platform_post_id"],connection,body["since"])
        raise ConnectorError("DEST_SPEC_VIOLATION", f"Unsupported connector method '{method}'.")
    except ValidationError as exc:
        raise ConnectorError("DEST_SPEC_VIOLATION", "Request validation failed.", False, {"violations":[{"field":".".join(map(str,e['loc'])),"message":e['msg']} for e in exc.errors()]})


@app.post("/api/v1/publish")
def publish(payload: dict[str, Any], idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if not idempotency_key: raise ConnectorError("DEST_SPEC_VIOLATION", "Idempotency-Key header is required.")
    d = destination(payload.get("destination_id", "")); c = connector(d.platform_key)
    r = Rendition.model_validate(payload.get("rendition", {})); connection = payload.get("connection", d.connection)
    request_fp = fingerprint({"destination":d.id,"rendition":r.model_dump(),"connection":connection})
    with PUBLISH_LOCK:
        with db_session() as db:
            prior = db.execute("SELECT fingerprint,result FROM idempotency WHERE key=?", (idempotency_key,)).fetchone()
            if prior:
                if prior["fingerprint"] != request_fp: raise ConnectorError("IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used for a different request.", False)
                return json.loads(prior["result"])
        result = perform_publish(c,r,d,connection,idempotency_key)
        result = {**result,"destination_id":d.id,"connector":c.key,"simulation":connection.get("mode", "simulation")=="simulation","manifest":make_manifest()}
        with db_session() as db:
            db.execute("INSERT OR IGNORE INTO posts(id,destination_id,idem_key,post_json,created_at) VALUES(?,?,?,?,?)",
                       (result["platform_post_id"], d.id, idempotency_key, json.dumps(result), now()))
            db.execute("INSERT INTO idempotency(key,fingerprint,result,created_at) VALUES(?,?,?,?)", (idempotency_key,request_fp,json.dumps(result),now()))
        return result


def job_update(job_id: str, status: str, progress: int, result: dict | None = None, error: dict | None = None) -> None:
    with db_session() as db:
        db.execute("UPDATE jobs SET status=?,progress=?,result=?,error=?,updated_at=? WHERE id=?",(status,progress,json.dumps(result) if result else None,json.dumps(error) if error else None,now(),job_id))


def certify(job_id: str, destination_id: str) -> None:
    job_update(job_id,"running",10)
    record: dict[str, Any] = {"destination_id":destination_id,"started_at":now(),"checks":{},"simulation":True,"manifest":make_manifest()}
    try:
        d = destination(destination_id); c=connector(d.platform_key)
        simulated = d.connection.get("mode", "simulation") == "simulation"
        record["simulation"] = simulated
        if not simulated and not d.connection.get("sandbox_approved", False):
            raise ConnectorError("DEST_SPEC_VIOLATION", "Native certification requires an explicitly approved owned test instance or sandbox.")
        r=Rendition(title="Certification check",text="Automated certification test post.",content_type="text")
        record["checks"]["configuration"]={"ok":True}
        v=c.validate(r,d,d.connection); record["checks"]["validate"]={"ok":v["ok"],"violations":v["violations"]}
        if not v["ok"]: raise ConnectorError("DEST_SPEC_VIOLATION","Certification rendition did not validate.",False,{"violations":v["violations"]})
        job_update(job_id,"running",30)
        key=f"cert-{job_id}"; p=perform_publish(c,r,d,d.connection,key)
        with db_session() as db:
            db.execute("INSERT OR IGNORE INTO posts(id,destination_id,idem_key,post_json,created_at) VALUES(?,?,?,?,?)",
                       (p["platform_post_id"],d.id,key,json.dumps(p),now()))
        record["checks"]["publish"]={"ok":True,"platform_post_id":p["platform_post_id"],"live_url":p["live_url"],"status":p["status"]}
        job_update(job_id,"running",60)
        s=c.get_status(p["platform_post_id"],d.connection); record["checks"]["status"]={"ok":s["status"]=="published","result":s}
        deleted=c.delete(p["platform_post_id"],d.connection); record["checks"]["cleanup"]={"ok":deleted["deleted"],"deleted":deleted["deleted"],"timestamp":now()}
        with db_session() as db: db.execute("UPDATE posts SET deleted=1 WHERE id=?",(p["platform_post_id"],))
        workflow_passed=all(x.get("ok") for x in record["checks"].values())
        record.update({"finished_at":now(),"workflow_passed":workflow_passed,"certified":workflow_passed and not simulated,
                       "certification_level":"simulation_workflow" if simulated else "native_sandbox","evidence_reference":f"certification:{job_id}"})
        job_update(job_id,"running",90)
        with db_session() as db: db.execute("INSERT INTO certifications(id,destination_id,result,created_at) VALUES(?,?,?,?)",(job_id,destination_id,json.dumps(record),now()))
        job_update(job_id,"succeeded",100,{"certification":record})
    except Exception as exc:
        error=exc.json() if isinstance(exc,ConnectorError) else {"error":{"code":"PLATFORM_UNAVAILABLE","message":str(exc),"retryable":False,"details":{}}}
        record.update({"finished_at":now(),"certified":False,"error":error})
        with db_session() as db: db.execute("INSERT OR REPLACE INTO certifications(id,destination_id,result,created_at) VALUES(?,?,?,?)",(job_id,destination_id,json.dumps(record),now()))
        job_update(job_id,"failed",100,{"certification":record},error)


@app.post("/api/v1/certifications",status_code=202)
def start_certification(payload: dict[str,str], background_tasks: BackgroundTasks, idempotency_key: str | None=Header(None,alias="Idempotency-Key")):
    if not idempotency_key: raise ConnectorError("DEST_SPEC_VIOLATION","Idempotency-Key header is required.")
    destination_id=payload.get("destination_id",""); d=destination(destination_id)
    fp=fingerprint({"destination_id":destination_id})
    with db_session() as db:
        prior=db.execute("SELECT fingerprint,result FROM idempotency WHERE key=?",(idempotency_key,)).fetchone()
        if prior:
            if prior["fingerprint"] != fp: raise ConnectorError("IDEMPOTENCY_KEY_REUSED","Idempotency-Key was already used for a different request.")
            return json.loads(prior["result"])
        job_id=str(uuid.uuid4()); response={"job_id":job_id,"status":"queued","progress":0,"result_url":f"/api/v1/jobs/{job_id}"}
        db.execute("INSERT INTO jobs(id,kind,status,progress,created_at,updated_at) VALUES(?,?,?,?,?,?)",(job_id,"certification","queued",0,now(),now()))
        db.execute("INSERT INTO idempotency(key,fingerprint,result,created_at) VALUES(?,?,?,?)",(idempotency_key,fp,json.dumps(response),now()))
    background_tasks.add_task(certify,job_id,destination_id)
    return response


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    with db_session() as db: row=db.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
    if not row: raise ConnectorError("DEST_SPEC_VIOLATION","Job not found.")
    return {"job_id":row["id"],"status":row["status"],"progress":row["progress"],"result":json.loads(row["result"]) if row["result"] else None,
            "error":json.loads(row["error"]) if row["error"] else None,"result_links":{"certification":f"/api/v1/certifications/{job_id}"} if row["result"] else {}}


@app.get("/api/v1/certifications/{certification_id}")
def get_certification(certification_id: str):
    with db_session() as db: row=db.execute("SELECT result FROM certifications WHERE id=?",(certification_id,)).fetchone()
    if not row: raise ConnectorError("DEST_SPEC_VIOLATION","Certification evidence not found.")
    return json.loads(row["result"])


@app.post("/api/v1/webhook/verify")
async def webhook_verify(request: Request, x_in_cubrix_signature: str = Header("", alias="X-IncuBrix-Signature")):
    body=await request.body(); secret=os.getenv("WEBHOOK_SECRET","")
    if not secret: raise ConnectorError("CONNECTION_AUTH_EXPIRED","WEBHOOK_SECRET is not configured.")
    if not verify_signature(body,secret,x_in_cubrix_signature): raise ConnectorError("CONNECTION_AUTH_EXPIRED","Webhook signature is invalid.")
    return {"ok":True}
