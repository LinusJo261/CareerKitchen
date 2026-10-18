"""Concurrent HTTP requests must leave the event loop and lock finalizers runnable."""

import asyncio
from threading import Event, Lock, get_ident

import httpx
import pytest
from app.core.auth import mint_dev_token
from app.db.models import Candidate
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api import deps

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency]


def bounded_database_lock_waits(dbapi_connection, connection_record, connection_proxy):
    # A broken event loop must fail this regression rather than hang the runner.
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SET lock_timeout = '1500ms'")
        cursor.execute("SET statement_timeout = '5000ms'")


def authorization(market):
    return {
        "Authorization": "Bearer " + mint_dev_token(market.users[0].id, email=market.users[0].verified_email)
    }


def test_three_same_user_writes_keep_event_loop_and_commits_runnable(market, monkeypatch):
    first_prepared, release_first = Event(), Event()
    guard = Lock()
    rate_calls = 0
    original_rate_limit = deps._rate_limit
    commit_threads = []

    def pause_first_rate_limit(db, actor, settings):
        nonlocal rate_calls
        original_rate_limit(db, actor, settings)
        with guard:
            rate_calls += 1
            first = rate_calls == 1
        if first:
            first_prepared.set()
            assert release_first.wait(3), "The event loop could not release the blocked database prelude"

    def record_commit_thread(db):
        if db.get_bind() is market.engine:
            commit_threads.append(get_ident())

    monkeypatch.setattr(deps, "_rate_limit", pause_first_rate_limit)
    event.listen(market.engine, "checkout", bounded_database_lock_waits)
    event.listen(Session, "before_commit", record_commit_thread)

    async def scenario():
        loop_thread = get_ident()

        async def heartbeat():
            while not first_prepared.is_set():
                await asyncio.sleep(0.005)
            # Give the other requests time to wait for the same identity lock.
            await asyncio.sleep(0.05)
            release_first.set()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=market.client.app),
            base_url="http://testserver",
            headers=authorization(market),
        ) as client:
            beating = asyncio.create_task(heartbeat())
            try:
                responses = await asyncio.wait_for(
                    asyncio.gather(
                        *(
                            client.put(
                                "/v1/candidates/me/learning-consent",
                                headers={"Idempotency-Key": f"fictional-concurrent-http-{index}"},
                                json={"enabled": True, "expected_version": 1},
                            )
                            for index in range(3)
                        )
                    ),
                    timeout=10,
                )
                await beating
                assert sorted(response.status_code for response in responses) == [200, 412, 412]
                assert commit_threads and loop_thread not in commit_threads
            finally:
                release_first.set()
                beating.cancel()
                await asyncio.gather(beating, return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        release_first.set()
        event.remove(market.engine, "checkout", bounded_database_lock_waits)
        event.remove(Session, "before_commit", record_commit_thread)
    with Session(market.engine) as db:
        candidate = db.get(Candidate, market.candidate.id)
        assert candidate.matching_learning_opt_in is True
        assert candidate.version == 2


def test_authentication_waiters_cannot_exhaust_endpoint_thread_capacity(market):
    event.listen(market.engine, "checkout", bounded_database_lock_waits)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=market.client.app),
            base_url="http://testserver",
            headers=authorization(market),
        ) as client:
            # Exceed AnyIO's usual 40 endpoint workers. Pending authentication
            # requests must leave capacity for the lock holder's endpoint/commit.
            responses = await asyncio.wait_for(
                asyncio.gather(*(client.get("/v1/candidates/me") for _ in range(48))), timeout=15
            )
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json()["data"]["id"] == market.candidate.id for response in responses)

    try:
        asyncio.run(scenario())
    finally:
        event.remove(market.engine, "checkout", bounded_database_lock_waits)
