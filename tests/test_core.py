import hashlib
import hmac
import pytest
import httpx

import app.core as core

from app.core import (ConnectorError, Destination, Rendition, SignedWebhookConnector, SimulatedConnector,
                      check_frequency, connect_db, db_session, fingerprint,
                      make_manifest, validate_rules)


def test_field_level_destination_rules():
    destination=Destination(id="strict-unit",name="Strict",platform_key="discourse",url="https://example.invalid",
        title_max_chars=3,body_max_chars=5,self_promo_allowed=False,link_policy="prohibited",disclosure_required=True)
    rendition=Rendition(title="Long title",text="https://example.invalid",is_promotional=True,is_ai_generated=True)
    violations=validate_rules(rendition,destination)
    assert {v["field"] for v in violations} == {"title","text","is_promotional","url","ai_disclosure"}


def test_content_type_blocked():
    d=Destination(id="text-only",name="Text",platform_key="discourse",url="https://example.invalid",content_types=["text"])
    assert validate_rules(Rendition(content_type="video"),d)[0]["code"] == "DEST_SPEC_VIOLATION"


def test_rate_limit_retry_metadata_and_manifest_cost():
    d=Destination(id="rate",name="Rate",platform_key="discourse",url="https://example.invalid",connection={"simulate_error":"429","retry_after":90})
    c=SimulatedConnector()
    with pytest.raises(ConnectorError) as error:
        c.publish(Rendition(text="Hello"),d,d.connection,"retry-key")
    assert error.value.code == "PLATFORM_RATE_LIMIT"
    assert error.value.retryable is True and error.value.details["retry_after"] == 90
    manifest=make_manifest()
    assert manifest["cost_estimate"]["amount"] == 0
    assert manifest["providers"] == []


def test_payload_fingerprint_is_order_independent():
    assert fingerprint({"a":1,"b":2}) == fingerprint({"b":2,"a":1})


def test_destination_url_validation():
    with pytest.raises(ValueError):
        Destination(id="bad-url",name="Bad",platform_key="discourse",url="file:///tmp/a")


def test_persistent_frequency_cap(monkeypatch,tmp_path):
    monkeypatch.setattr(core,"DB_PATH",tmp_path/"caps.sqlite3")
    d=Destination(id="cap",name="Cap",platform_key="discourse",url="https://example.invalid",frequency_cap=1)
    with db_session() as db:
        db.execute("INSERT INTO posts(id,destination_id,idem_key,post_json,created_at) VALUES(?,?,?,?,?)",
                   ("p1",d.id,"k1","{}",core.now()))
    with pytest.raises(ConnectorError) as error:
        check_frequency(d)
    assert error.value.code == "DEST_RULE_FREQUENCY_CAP"
    assert error.value.retryable is True


def test_deleted_certification_post_does_not_consume_frequency_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "cleanup.sqlite3")
    d = Destination(id="cleanup", name="Cleanup", platform_key="discourse",
                    url="https://example.invalid", frequency_cap=1)
    with db_session() as db:
        db.execute("INSERT INTO posts(id,destination_id,idem_key,post_json,created_at,deleted) VALUES(?,?,?,?,?,?)",
                   ("cert-post", d.id, "cert-key", "{}", core.now(), 1))
    # A deleted certification post is no longer a live publication.
    check_frequency(d)


@pytest.mark.parametrize(("simulate_error", "code", "retryable"), [
    ("auth", "CONNECTION_AUTH_EXPIRED", False),
    ("rejected", "PLATFORM_CONTENT_REJECTED", False),
    ("429", "PLATFORM_RATE_LIMIT", True),
    ("timeout", "PLATFORM_UNAVAILABLE", True),
])
def test_simulated_hard_case_error_mapping(simulate_error, code, retryable):
    d = Destination(id="hard-case", name="Hard case", platform_key="discourse",
                    url="https://example.invalid", connection={"simulate_error": simulate_error, "retry_after": 120})
    with pytest.raises(ConnectorError) as error:
        SimulatedConnector().publish(Rendition(text="Test"), d, d.connection, "same-key")
    assert error.value.code == code
    assert error.value.retryable is retryable
    if simulate_error == "429":
        assert error.value.details["retry_after"] == 120


def test_media_and_non_english_ai_disclosure_hard_cases():
    d = Destination(id="disclosure", name="Disclosure", platform_key="discourse",
                    url="https://example.invalid", language="es", content_types=["text"],
                    disclosure_required=True)
    rendition = Rendition(content_type="image", media=["https://cdn.invalid/image.png"],
                          is_ai_generated=True)
    violations = validate_rules(rendition, d)
    assert {v["code"] for v in violations} == {"DEST_SPEC_VIOLATION", "DEST_RULE_AI_DISCLOSURE"}


def test_signed_webhook_publish_status_delete(monkeypatch):
    secret="unit-test-secret"
    monkeypatch.setenv("WEBHOOK_SECRET",secret)
    seen=[]
    def handle(request):
        expected="sha256="+hmac.new(secret.encode(),request.content or b"",hashlib.sha256).hexdigest()
        assert request.headers["X-IncuBrix-Signature"] == expected
        if request.method=="POST": assert request.headers["Idempotency-Key"] == "idem"
        seen.append(request.method)
        if request.method=="POST": return httpx.Response(200,json={"platform_post_id":"abc","live_url":"https://site.invalid/p/abc"})
        if request.method=="GET": return httpx.Response(200,json={"status":"published","live_url":"https://site.invalid/p/abc"})
        return httpx.Response(200,json={"deleted":True})
    connector=SignedWebhookConnector(httpx.MockTransport(handle))
    destination=Destination(id="partner",name="Partner",platform_key="signed_webhook",url="https://site.invalid/publish",
        connection={"mode":"native","secret_env":"WEBHOOK_SECRET","status_url":"https://site.invalid/posts/{id}","delete_url":"https://site.invalid/posts/{id}"})
    result=connector.publish(Rendition(text="Hello"),destination,destination.connection,"idem")
    assert result["platform_post_id"]=="abc"
    assert connector.get_status("abc",destination.connection)["status"]=="published"
    assert connector.delete("abc",destination.connection)=={"deleted":True}
    assert seen==["POST","GET","DELETE"]


@pytest.mark.parametrize(("status", "headers", "code", "retryable"), [
    (401, {}, "CONNECTION_AUTH_EXPIRED", False),
    (429, {"X-RateLimit-Reset": "2026-10-20T12:05:00Z"}, "PLATFORM_RATE_LIMIT", True),
    (422, {}, "PLATFORM_CONTENT_REJECTED", False),
    (503, {}, "PLATFORM_UNAVAILABLE", True),
])
def test_signed_webhook_maps_partner_hard_case_errors(monkeypatch, status, headers, code, retryable):
    monkeypatch.setenv("WEBHOOK_SECRET", "unit-test-secret")
    connector = SignedWebhookConnector(httpx.MockTransport(
        lambda request: httpx.Response(status, headers=headers, json={"error": "test"})))
    with pytest.raises(ConnectorError) as error:
        connector._request("GET", "https://partner.invalid/status", {}, b"{}")
    assert error.value.code == code
    assert error.value.retryable is retryable
    if status == 429:
        assert error.value.details["retry_after"] == headers["X-RateLimit-Reset"]


def test_signed_webhook_retry_after_timeout_uses_same_idempotency_key(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "unit-test-secret")
    accepted = {}
    post_attempts = []

    def handle(request):
        key = request.headers["Idempotency-Key"]
        post_attempts.append(key)
        if key not in accepted:
            # The partner accepted the first request, but the response was lost.
            accepted[key] = {"platform_post_id": "one-post", "live_url": "https://site.invalid/p/one-post"}
            raise httpx.ReadTimeout("response lost")
        return httpx.Response(200, json=accepted[key])

    connector = SignedWebhookConnector(httpx.MockTransport(handle))
    destination = Destination(id="partner-timeout", name="Partner", platform_key="signed_webhook",
                              url="https://partner.invalid/publish", connection={
                                  "mode": "native", "secret_env": "WEBHOOK_SECRET"})
    with pytest.raises(ConnectorError) as first:
        connector.publish(Rendition(text="Hello"), destination, destination.connection, "retry-same")
    assert first.value.code == "PLATFORM_UNAVAILABLE"
    result = connector.publish(Rendition(text="Hello"), destination, destination.connection, "retry-same")
    assert result["platform_post_id"] == "one-post"
    assert post_attempts == ["retry-same", "retry-same"]
    assert len(accepted) == 1
