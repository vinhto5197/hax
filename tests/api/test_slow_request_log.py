"""SlowRequestLog: a request slower than SLOW_REQUEST_MS leaves one WARNING
naming the route template — never the raw path, query string or headers."""

import asyncio
import logging

import httpx
from fastapi import FastAPI

import apps.api.main as main

LOGGER = "apps.api.main"


def _app() -> FastAPI:
    # A standalone app, so no test routes leak onto the real one.
    app = FastAPI()
    app.add_middleware(main.SlowRequestLog)

    @app.get("/items/{item_id}")
    async def slow_item(item_id: str) -> dict:
        await asyncio.sleep(0.2)
        return {"ok": True}

    @app.get("/fast")
    async def fast() -> dict:
        return {"ok": True}

    return app


async def _get(app: FastAPI, url: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(url, **kwargs)


def _slow_records(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == LOGGER and "slow request" in r.getMessage()
    ]


def test_installed_on_the_api_app():
    assert any(m.cls is main.SlowRequestLog for m in main.app.user_middleware)


async def test_slow_request_logs_one_line_with_the_route_template(monkeypatch, caplog):
    monkeypatch.setattr(main, "SLOW_REQUEST_MS", 50)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    resp = await _get(
        _app(),
        "/items/123?secret=xyz",
        headers={"Authorization": "Bearer hunter2"},
    )

    assert resp.status_code == 200
    records = _slow_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    for expected in ("GET", "/items/{item_id}", "200", "ms"):
        assert expected in message
    for leaked in ("123", "secret", "xyz", "hunter2", "Bearer"):
        assert leaked not in message


async def test_fast_request_logs_nothing(caplog):
    # The default threshold: a route that returns at once never trips it.
    assert main.SLOW_REQUEST_MS == 2000
    caplog.set_level(logging.WARNING, logger=LOGGER)

    resp = await _get(_app(), "/fast")

    assert resp.status_code == 200
    assert _slow_records(caplog) == []


async def test_unmatched_path_is_logged_without_the_raw_path(monkeypatch, caplog):
    # A negative threshold makes every request "slow", so the unmatched branch
    # is reached without a slow 404 handler.
    monkeypatch.setattr(main, "SLOW_REQUEST_MS", -1)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    resp = await _get(_app(), "/no-such/987?token=abc")

    assert resp.status_code == 404
    records = _slow_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "<unmatched>" in message and "404" in message
    for leaked in ("no-such", "987", "token", "abc"):
        assert leaked not in message
