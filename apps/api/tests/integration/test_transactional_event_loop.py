"""Real ASGI concurrency must not block provider deadlines behind PostgreSQL locks."""

import asyncio
import hashlib
import json
import threading

import httpx
import pytest
from anyio import CancelScope, create_task_group, to_thread
from app.core.auth import mint_dev_token
from app.db.models import AuditEvent, Candidate, CandidateSkill, IdempotencyRecord, OutboxEvent, RateBucket
from app.schemas.onboarding import OnboardingDraft
from pydantic import SecretStr
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency]


def provider_response():
    generated = {
        "reply": "Let's explore the kind of work you enjoy.",
        "question": {
            "field": "role_families",
            "kind": "preference",
            "skill": None,
            "prompt": "Do you prefer building tools or analyzing data?",
            "choices": [],
        },
        "draft": OnboardingDraft().model_dump(mode="json"),
    }
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(generated)}]}}]}


@pytest.mark.parametrize("first_fails", [False, True])
def test_same_actor_waiter_keeps_heartbeat_health_and_provider_responsive(market, monkeypatch, first_fails):
    """A duplicate waits off-loop; a failed first call leaves no partial operation."""
    app = market.client.app
    actor = market.users[0]
    identity_key = f"identity:{actor.issuer}:{actor.subject}"
    identity_lock = int.from_bytes(hashlib.sha256(identity_key.encode()).digest()[:8], "big", signed=True)
    second_waiting = threading.Event()
    lock_attempts = 0

    def before_execute(_connection, _cursor, statement, parameters, _context, _many):
        nonlocal lock_attempts
        if "pg_advisory_xact_lock" in statement and parameters.get("key") == identity_lock:
            lock_attempts += 1
            if lock_attempts == 2:
                second_waiting.set()

    def bounded_regression_wait(connection, _record, _proxy):
        # Bound a pre-fix regression failure: this is not a production workaround.
        # The fixed implementation completes before this PostgreSQL timeout.
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '1500ms'")

    event.listen(market.engine, "before_cursor_execute", before_execute)
    event.listen(market.engine, "checkout", bounded_regression_wait)
    monkeypatch.setattr(app.state.settings, "gemini_api_key", SecretStr("fictional-concurrency-key"))
    original_client = httpx.AsyncClient
    with Session(market.engine) as db:
        before_candidate = dict(db.execute(select(Candidate.__table__)).mappings().one())
        before_skills = list(db.execute(select(CandidateSkill.__table__)).mappings())

    async def scenario():
        provider_entered = asyncio.Event()
        release_provider = asyncio.Event()
        stop_heartbeat = asyncio.Event()
        heartbeat_started = asyncio.Event()
        ticks = []
        phases = {"start": asyncio.get_running_loop().time()}
        provider_calls = 0

        async def slow_provider(_request):
            nonlocal provider_calls
            provider_calls += 1
            if provider_calls == 1:
                provider_entered.set()
                await release_provider.wait()
                if first_fails:
                    return httpx.Response(503, json={"error": "fictional transient provider failure"})
            return httpx.Response(200, json=provider_response())

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: original_client(
                **kwargs,
                transport=httpx.MockTransport(slow_provider),
            ),
        )
        limiter = to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        # If transaction workers use the default limiter, their callback into
        # FastAPI cannot acquire this one token for its sync dependencies.
        limiter.total_tokens = 1
        heartbeat = None
        requests = []

        async def beat():
            while not stop_heartbeat.is_set():
                ticks.append(asyncio.get_running_loop().time())
                heartbeat_started.set()
                await asyncio.sleep(0.01)

        try:
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 11223))
            async with original_client(transport=transport, base_url="http://testserver") as client:
                # Warm health response validation before measuring lock
                # contention; coverage magnifies unrelated cold-schema CPU.
                baseline_health = await client.get("/v1/health")
                assert baseline_health.status_code == 200
                headers = {
                    "Authorization": "Bearer " + mint_dev_token(actor.id, email=actor.verified_email),
                    "Idempotency-Key": "fictional-concurrent-onboarding",
                }
                body = {"message": "I enjoy building useful tools.", "consent_to_gemini": True}
                first = asyncio.create_task(
                    client.post("/v1/navigation/onboarding", headers=headers, json=body)
                )
                requests.append(first)
                await asyncio.wait_for(provider_entered.wait(), 3)
                phases["provider_wait"] = asyncio.get_running_loop().time()
                # The regression window starts only once the first request is
                # actually awaiting the provider, before the lock waiter starts.
                heartbeat = asyncio.create_task(beat())
                await heartbeat_started.wait()
                second = asyncio.create_task(
                    client.post("/v1/navigation/onboarding", headers=headers, json=body)
                )
                requests.append(second)
                async with asyncio.timeout(3):
                    while not second_waiting.is_set():
                        await asyncio.sleep(0.01)
                await asyncio.sleep(0.06)
                health = await asyncio.wait_for(client.get("/v1/health"), 1)
                phases["release"] = asyncio.get_running_loop().time()
                # Include the closing interval, then stop before provider
                # completion/response serialization, which are not lock waits.
                ticks.append(phases["release"])
                stop_heartbeat.set()
                await heartbeat
                release_provider.set()
                responses = await asyncio.wait_for(asyncio.gather(*requests), 5)
                phases["finished"] = asyncio.get_running_loop().time()
                assert health.status_code == 200
                assert responses[1].status_code == 200, responses[1].text
                if first_fails:
                    assert responses[0].status_code == 503
                    assert provider_calls == 2
                    assert "Idempotency-Replayed" not in responses[1].headers
                else:
                    assert responses[0].status_code == 200, responses[0].text
                    assert responses[1].headers["Idempotency-Replayed"] == "true"
                    assert responses[1].json() == responses[0].json()
                    assert provider_calls == 1
                assert len(ticks) >= 3
                gap = max(zip(ticks, ticks[1:], strict=False), key=lambda pair: pair[1] - pair[0])
                offsets = {key: round(value - phases["start"], 3) for key, value in phases.items()}
                assert gap[1] - gap[0] < 0.5, (
                    f"gap_offsets={tuple(round(value - phases['start'], 3) for value in gap)}; phases={offsets}"
                )
        finally:
            release_provider.set()
            stop_heartbeat.set()
            if heartbeat:
                await heartbeat
            for task in requests:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*requests, return_exceptions=True)
            limiter.total_tokens = original_tokens

    try:
        asyncio.run(scenario())
    finally:
        event.remove(market.engine, "before_cursor_execute", before_execute)
        event.remove(market.engine, "checkout", bounded_regression_wait)
    with Session(market.engine) as db:
        assert dict(db.execute(select(Candidate.__table__)).mappings().one()) == before_candidate
        assert list(db.execute(select(CandidateSkill.__table__)).mappings()) == before_skills
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "ONBOARDING_ASSISTED")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.kind == "ONBOARDING_ASSISTED")
            )
            == 1
        )
        assert db.get(RateBucket, f"write:{actor.id}").count == 1


def test_cancelled_async_handler_rolls_back_and_releases_same_actor_for_retry(market, monkeypatch):
    """Cancellation crosses the worker bridge and closes the whole transaction."""
    app = market.client.app
    actor = market.users[0]
    monkeypatch.setattr(app.state.settings, "gemini_api_key", SecretStr("fictional-concurrency-key"))
    original_client = httpx.AsyncClient

    def count_operations():
        with Session(market.engine) as db:
            return db.scalar(select(func.count()).select_from(IdempotencyRecord)), db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "ONBOARDING_ASSISTED")
            )

    async def scenario():
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        force_release = asyncio.Event()
        finished = asyncio.Event()
        scopes = []
        attempts = 0

        async def provider(_request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                entered.set()
                try:
                    await force_release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return httpx.Response(200, json=provider_response())

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: original_client(
                **kwargs,
                transport=httpx.MockTransport(provider),
            ),
        )
        async with original_client(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 11224)),
            base_url="http://testserver",
        ) as client:
            headers = {
                "Authorization": "Bearer " + mint_dev_token(actor.id, email=actor.verified_email),
                "Idempotency-Key": "fictional-cancelled-onboarding",
            }
            body = {"message": "I enjoy building useful tools.", "consent_to_gemini": True}

            async def first_request():
                try:
                    with CancelScope() as scope:
                        scopes.append(scope)
                        await client.post("/v1/navigation/onboarding", headers=headers, json=body)
                finally:
                    finished.set()

            async with create_task_group() as group:
                group.start_soon(first_request)
                try:
                    await asyncio.wait_for(entered.wait(), 3)
                    scopes[0].cancel()
                    await asyncio.wait_for(finished.wait(), 3)
                    assert cancelled.is_set()
                    assert await to_thread.run_sync(count_operations) == (0, 0)
                finally:
                    force_release.set()
            retry = await asyncio.wait_for(
                client.post("/v1/navigation/onboarding", headers=headers, json=body), 3
            )
            assert retry.status_code == 200, retry.text
            assert "Idempotency-Replayed" not in retry.headers
            assert attempts == 2

    asyncio.run(scenario())
    assert count_operations() == (1, 1)
