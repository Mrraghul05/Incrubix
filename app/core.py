from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
import httpx


DB_PATH = Path(os.getenv("DATABASE_PATH", "./data/incubrix.sqlite3"))
SIMULATION = os.getenv("SIMULATION_MODE", "true").lower() == "true"
LOCK = threading.RLock()
MOCK_POSTS: dict[str, dict[str, Any]] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS destinations(id TEXT PRIMARY KEY, config TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, destination_id TEXT NOT NULL, idem_key TEXT NOT NULL UNIQUE, post_json TEXT NOT NULL, created_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL, result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS certifications(id TEXT PRIMARY KEY, destination_id TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    return db


@contextmanager
def db_session():
    db = connect_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class Rendition(BaseModel):
    title: str = ""
    text: str = ""
    content_type: str = "text"
    media: list[str] = Field(default_factory=list)
    url: str | None = None
    is_promotional: bool = False
    is_ai_generated: bool = False
    ai_disclosure: str | None = None


class Destination(BaseModel):
    id: str
    name: str
    platform_key: str
    url: str
    surface: str = "default"
    category: str = "community"
    language: str = "en"
    automation_allowed: bool = True
    frequency_cap: int = 7
    frequency_window_days: int = 7
    self_promo_allowed: bool = True
    link_policy: str = "allowed"
    disclosure_required: bool = False
    title_max_chars: int = 255
    body_max_chars: int = 32000
    content_types: list[str] = Field(default_factory=lambda: ["text", "image", "video_link"])
    rate_limit_per_minute: int = 60
    connection: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def valid_http_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Destination URL must be an absolute HTTP or HTTPS URL.")
        return value

    @field_validator("frequency_cap", "frequency_window_days", "title_max_chars", "body_max_chars", "rate_limit_per_minute")
    @classmethod
    def positive_limits(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Limit must be at least 1.")
        return value


class ConnectorError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, details: dict[str, Any] | None = None):
        self.code, self.message, self.retryable, self.details = code, message, retryable, details or {}
        super().__init__(message)

    def json(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable, "details": self.details}}


def validate_rules(r: Rendition, d: Destination) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    def add(field: str, code: str, message: str) -> None:
        violations.append({"field": field, "code": code, "message": message})
    if len(r.title) > d.title_max_chars:
        add("title", "DEST_SPEC_VIOLATION", f"Title exceeds {d.title_max_chars} characters.")
    if len(r.text) > d.body_max_chars:
        add("text", "DEST_SPEC_VIOLATION", f"Body exceeds {d.body_max_chars} characters.")
    if r.content_type not in d.content_types:
        add("content_type", "DEST_SPEC_VIOLATION", f"Content type '{r.content_type}' is not supported.")
    if r.is_promotional and not d.self_promo_allowed:
        add("is_promotional", "DEST_RULE_SELF_PROMOTION", "Destination rules prohibit self-promotion.")
    if d.link_policy == "prohibited" and (r.url or "http://" in r.text or "https://" in r.text):
        add("url", "DEST_RULE_LINKS", "Destination rules prohibit external links.")
    if d.disclosure_required and r.is_ai_generated and not (r.ai_disclosure or "").strip():
        add("ai_disclosure", "DEST_RULE_AI_DISCLOSURE", "Add an AI-generated content disclosure before publishing.")
    return violations


def check_frequency(d: Destination) -> None:
    window_start = (datetime.now(timezone.utc) - timedelta(days=d.frequency_window_days)).isoformat()
    with db_session() as db:
        # Certification posts are deleted during cleanup and must not consume
        # the destination's publishing allowance after they have been removed.
        count = db.execute("SELECT COUNT(*) FROM posts WHERE destination_id=? AND created_at>=? AND deleted=0", (d.id, window_start)).fetchone()[0]
    if count >= d.frequency_cap:
        raise ConnectorError("DEST_RULE_FREQUENCY_CAP", "Destination frequency cap reached; retry after the cap window.", True,
                             {"frequency_cap": d.frequency_cap, "window_days": d.frequency_window_days, "posts_in_window": count})


class Connector:
    key = "base"
    version = "1.0.0"
    tier = "native"
    auth = "api_key"
    def validate(self, rendition: Rendition, destination: Destination, connection: dict[str, Any]) -> dict[str, Any]:
        return {"ok": not validate_rules(rendition, destination), "violations": validate_rules(rendition, destination)}
    def publish(self, rendition: Rendition, destination: Destination, connection: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        raise NotImplementedError
    def get_status(self, platform_post_id: str, connection: dict[str, Any]) -> dict[str, Any]:
        post = MOCK_POSTS.get(platform_post_id)
        if not post: raise ConnectorError("PLATFORM_CONTENT_REJECTED", "Post was not found.")
        return {"status": "deleted" if post["deleted"] else "published", "live_url": post["live_url"]}
    def delete(self, platform_post_id: str, connection: dict[str, Any]) -> dict[str, Any]:
        if platform_post_id not in MOCK_POSTS: raise ConnectorError("PLATFORM_CONTENT_REJECTED", "Post was not found.")
        MOCK_POSTS[platform_post_id]["deleted"] = True
        return {"deleted": True}
    def fetch_metrics(self, platform_post_id: str, connection: dict[str, Any], since: str) -> dict[str, int]:
        return {"views": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0, "watch_time_s": 0, "clicks": 0}
    def manifest(self) -> dict[str, Any]:
        return {"key": self.key, "version": self.version, "tier": self.tier, "auth": self.auth,
                "surfaces": [{"key": "default", "content_types": ["text", "image", "video_link"], "spec": {"title_max_chars": 255, "body_max_chars": 32000, "links_allowed": True}}],
                "rate_limits": {"per_connection": {"requests": 60, "per_seconds": 60}},
                "capabilities": ["publish", "status", "delete", "metrics"], "error_map": {"429": "PLATFORM_RATE_LIMIT", "422": "PLATFORM_CONTENT_REJECTED", "401": "CONNECTION_AUTH_EXPIRED"}, "instance_param": "base_url"}


class SimulatedConnector(Connector):
    """Deterministic local adapter; its successes are simulation evidence, not native certification."""
    def publish(self, rendition: Rendition, destination: Destination, connection: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        behavior = connection.get("simulate_error")
        if behavior == "timeout": raise ConnectorError("PLATFORM_UNAVAILABLE", "Simulated timeout after request; retry with the same idempotency key.", True)
        if behavior == "429": raise ConnectorError("PLATFORM_RATE_LIMIT", "Platform rate limit reached.", True, {"retry_after": connection.get("retry_after", 60)})
        if behavior == "auth": raise ConnectorError("CONNECTION_AUTH_EXPIRED", "Connection credentials expired; reconnect the destination.")
        if behavior == "rejected": raise ConnectorError("PLATFORM_CONTENT_REJECTED", "Platform rejected the content.")
        post_id = hashlib.sha256(f"{destination.id}:{idempotency_key}".encode()).hexdigest()[:20]
        live_url = f"{destination.url.rstrip('/')}/simulated/{post_id}"
        result = {"platform_post_id": post_id, "live_url": live_url, "status": "published"}
        MOCK_POSTS[post_id] = {**result, "deleted": False}
        return result


class AssistedConnector(SimulatedConnector):
    key = "assisted"
    tier = "assisted"
    auth = "none"
    def publish(self, rendition: Rendition, destination: Destination, connection: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        raise ConnectorError("CONNECTOR_ASSISTED_ONLY", "Assisted destinations require a person to post; no automated publication was attempted.")
    def build_assist_pack(self, rendition: Rendition, destination: Destination) -> dict[str, Any]:
        files = list(rendition.media)
        if rendition.url: files.append(rendition.url)
        return {"files": files, "caption": "\n\n".join(x for x in [rendition.title, rendition.text] if x),
                "deep_link": destination.connection.get("submit_url", destination.url),
                "checklist": ["Review destination rules", "Confirm links and disclosure comply", "Post manually", "Save the live URL as evidence"]}


class SignedWebhookConnector(SimulatedConnector):
    key = "signed_webhook"
    tier = "protocol"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(transport=transport, timeout=10)

    def _request(self, method: str, url: str, connection: dict[str, Any], content: bytes | None = None,
                 idempotency_key: str | None = None) -> httpx.Response:
        secret_name = connection.get("secret_env", "WEBHOOK_SECRET")
        secret = os.getenv(secret_name, "")
        if not secret:
            raise ConnectorError("CONNECTION_AUTH_EXPIRED", f"Signing secret environment variable '{secret_name}' is not configured.")
        signature = "sha256=" + hmac.new(secret.encode(), content or b"", hashlib.sha256).hexdigest()
        try:
            headers={"X-IncuBrix-Signature":signature,"Content-Type":"application/json"}
            if idempotency_key: headers["Idempotency-Key"]=idempotency_key
            response = self.client.request(method, url, content=content, headers=headers)
        except httpx.TimeoutException as exc:
            raise ConnectorError("PLATFORM_UNAVAILABLE", "Signed webhook request timed out.", True) from exc
        except httpx.RequestError as exc:
            raise ConnectorError("PLATFORM_UNAVAILABLE", "Signed webhook endpoint is unavailable.", True) from exc
        if response.status_code == 401:
            raise ConnectorError("CONNECTION_AUTH_EXPIRED", "Partner rejected the signing credentials.")
        if response.status_code == 429:
            reset = (response.headers.get("Retry-After") or
                     response.headers.get("X-RateLimit-Reset") or
                     response.headers.get("RateLimit-Reset"))
            raise ConnectorError("PLATFORM_RATE_LIMIT", "Partner rate limit reached.", True,
                                 {"retry_after":reset})
        if response.status_code == 422:
            raise ConnectorError("PLATFORM_CONTENT_REJECTED", "Partner rejected the content.", False,
                                 {"status":response.status_code})
        if response.status_code >= 500:
            raise ConnectorError("PLATFORM_UNAVAILABLE", "Partner endpoint returned a server error.", True,
                                 {"status":response.status_code})
        if response.is_error:
            raise ConnectorError("PLATFORM_CONTENT_REJECTED", "Partner endpoint rejected the request.", False,
                                 {"status":response.status_code})
        return response

    def publish(self, rendition: Rendition, destination: Destination, connection: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if connection.get("mode", "simulation") == "simulation":
            return super().publish(rendition,destination,connection,idempotency_key)
        url=connection.get("endpoint_url",destination.url)
        content=json.dumps({"destination_id":destination.id,"rendition":rendition.model_dump(),"idempotency_key":idempotency_key},separators=(",", ":")).encode()
        response=self._request("POST",url,connection,content,idempotency_key)
        try: result=response.json()
        except ValueError as exc: raise ConnectorError("PLATFORM_CONTENT_REJECTED","Partner response was not valid JSON.") from exc
        if not result.get("platform_post_id") or not result.get("live_url"):
            raise ConnectorError("PLATFORM_CONTENT_REJECTED","Partner response must contain platform_post_id and live_url.",False,
                                 {"required_fields":["platform_post_id","live_url"]})
        return {"platform_post_id":str(result["platform_post_id"]),"live_url":str(result["live_url"]),"status":result.get("status","published")}

    def get_status(self, platform_post_id: str, connection: dict[str, Any]) -> dict[str, Any]:
        if connection.get("mode", "simulation") == "simulation": return super().get_status(platform_post_id,connection)
        template=connection.get("status_url")
        if not template: raise ConnectorError("DEST_SPEC_VIOLATION","status_url is required for signed webhook status checks.")
        response=self._request("GET",template.format(id=platform_post_id),connection)
        try: result=response.json()
        except ValueError as exc: raise ConnectorError("PLATFORM_CONTENT_REJECTED","Partner status response was not valid JSON.") from exc
        if "status" not in result or "live_url" not in result: raise ConnectorError("PLATFORM_CONTENT_REJECTED","Partner status response must contain status and live_url.")
        return {"status":result["status"],"live_url":result["live_url"]}

    def delete(self, platform_post_id: str, connection: dict[str, Any]) -> dict[str, Any]:
        if connection.get("mode", "simulation") == "simulation": return super().delete(platform_post_id,connection)
        template=connection.get("delete_url")
        if not template: raise ConnectorError("DEST_SPEC_VIOLATION","delete_url is required for signed webhook cleanup.")
        response=self._request("DELETE",template.format(id=platform_post_id),connection)
        try: result=response.json()
        except ValueError as exc: raise ConnectorError("PLATFORM_CONTENT_REJECTED","Partner delete response was not valid JSON.") from exc
        if result.get("deleted") is not True: raise ConnectorError("PLATFORM_CONTENT_REJECTED","Partner did not confirm deletion.")
        return {"deleted":True}


CONNECTORS: dict[str, Connector] = {}
for _key in ("discourse", "lemmy", "devto", "ghost"):
    _c = SimulatedConnector(); _c.key = _key; CONNECTORS[_key] = _c
CONNECTORS["signed_webhook"] = SignedWebhookConnector()
CONNECTORS["assisted"] = AssistedConnector()


def fingerprint(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def perform_publish(connector: Connector, rendition: Rendition, destination: Destination, connection: dict[str, Any], key: str) -> dict[str, Any]:
    violations = connector.validate(rendition, destination, connection)["violations"]
    if violations:
        raise ConnectorError("DEST_SPEC_VIOLATION", "Content does not satisfy destination requirements.", False, {"violations": violations})
    check_frequency(destination)
    return connector.publish(rendition, destination, connection, key)


def make_manifest() -> dict[str, Any]:
    return {"providers": [], "provider_versions": [], "settings": {"simulation_mode": SIMULATION}, "seed": None,
            "timings_ms": {}, "cost_estimate": {"amount": 0, "currency": "USD", "basis": "No AI or paid external provider used."},
            "warnings": ["Simulation does not constitute native destination certification."] if SIMULATION else [],
            "licence_rights": {"generated_media": False, "rights": "Caller must supply content and media they own or may use."}}


def verify_signature(body: bytes, secret: str, signature: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))
