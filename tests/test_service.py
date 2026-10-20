import json
import os
import asyncio
from pathlib import Path

import pytest
import httpx


class Client:
    """Synchronous facade over HTTPX ASGI transport for deterministic in-process API tests."""
    def __init__(self, app): self.app = app
    def request(self, method, path, **kwargs):
        async def send():
            transport=httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport,base_url="http://test") as client:
                return await client.request(method,path,**kwargs)
        return asyncio.run(send())
    def get(self,path,**kwargs): return self.request("GET",path,**kwargs)
    def post(self,path,**kwargs): return self.request("POST",path,**kwargs)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("DESTINATIONS_FILE", str(Path(__file__).parents[1] / "config" / "destinations.yaml"))
    from app import core, main
    core.DB_PATH = tmp_path / "test.sqlite3"
    main.load_destinations()
    # Avoid test client transport differences on Windows while still exercising
    # FastAPI routing, validation, persistence, and response serialization.
    main.app.user_middleware.clear()
    main.app.middleware_stack = None
    yield Client(main.app)


def test_health_readiness_and_manifests(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["status"] == "ready"
    assert {m["key"] for m in client.get("/api/v1/connectors").json()} == {"discourse","lemmy","devto","ghost","signed_webhook","assisted"}


def test_rules_block_self_promo_links_disclosure_and_limits(client):
    destination={"id":"strict","name":"Strict","platform_key":"discourse","url":"https://x.invalid","title_max_chars":3,"body_max_chars":6,"self_promo_allowed":False,"link_policy":"prohibited","disclosure_required":True}
    rendition={"title":"Too long","text":"https://example.com and long","is_promotional":True,"is_ai_generated":True}
    result=client.post("/connector/v1/discourse/validate",json={"destination":destination,"rendition":rendition}).json()
    assert result["ok"] is False
    assert {x["field"] for x in result["violations"]} >= {"title","text","is_promotional","url","ai_disclosure"}


def test_publish_idempotency_and_payload_conflict(client):
    payload={"destination_id":"discourse-local","rendition":{"title":"Hello","text":"A useful post"}}
    first=client.post("/api/v1/publish",json=payload,headers={"Idempotency-Key":"same"})
    second=client.post("/api/v1/publish",json=payload,headers={"Idempotency-Key":"same"})
    assert first.status_code == second.status_code == 200
    assert first.json()["platform_post_id"] == second.json()["platform_post_id"]
    changed={**payload,"rendition":{"title":"Different"}}
    conflict=client.post("/api/v1/publish",json=changed,headers={"Idempotency-Key":"same"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_capability_errors_and_assisted_pack(client):
    r=client.post("/connector/v1/assisted/build_assist_pack",json={"destination":{"id":"manual","name":"Manual","platform_key":"assisted","url":"https://x.invalid","automation_allowed":False,"connection":{"submit_url":"https://x.invalid/new"}},"rendition":{"title":"Title","text":"Body","media":["https://cdn.invalid/image.png"]}})
    assert r.status_code == 200 and "manually" in " ".join(r.json()["checklist"])
    post=client.post("/connector/v1/assisted/publish",json={"destination_id":"assisted-community","rendition":{"text":"hello"},"idempotency_key":"manual"})
    assert post.status_code == 409
    assert post.json()["error"]["code"] == "CONNECTOR_ASSISTED_ONLY"


def test_certification_job_and_evidence(client):
    start=client.post("/api/v1/certifications",json={"destination_id":"lemmy-local"},headers={"Idempotency-Key":"cert-job"})
    assert start.status_code == 202
    job=client.get(start.json()["result_url"]).json()
    assert job["status"] == "succeeded" and job["progress"] == 100
    evidence=client.get(f"/api/v1/certifications/{start.json()['job_id']}").json()
    assert evidence["certified"] is False
    assert evidence["workflow_passed"] is True
    assert evidence["certification_level"] == "simulation_workflow"
    assert evidence["checks"]["cleanup"]["deleted"] is True
    assert evidence["simulation"] is True


def test_config_adds_second_platform_instance(client):
    d={"id":"discourse-second","name":"Second forum","platform_key":"discourse","url":"https://forum2.invalid","frequency_cap":4}
    assert client.post("/api/v1/destinations",json=d).status_code == 200
    assert any(x["id"]==d["id"] for x in client.get("/api/v1/destinations").json())
