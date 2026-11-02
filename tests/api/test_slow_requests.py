import asyncio
import logging

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from apps.api.watchdog import SlowRequestWatchdog

THRESHOLD = 0.05


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/fast")
    async def fast():
        return {"ok": True}

    @app.get("/slow/{item_id}")
    async def slow(item_id: str):
        await asyncio.sleep(THRESHOLD * 3)
        return {"ok": True}

    @app.get("/stream")
    async def stream():
        async def body():
            yield b"first"
            await asyncio.sleep(THRESHOLD * 3)
            yield b"last"

        return StreamingResponse(body())

    app.add_middleware(SlowRequestWatchdog, threshold=THRESHOLD)
    return app


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get(path)


def _lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "apps.api.watchdog"]


async def test_a_request_still_waiting_past_the_threshold_is_logged_while_it_waits(
    caplog,
):
    caplog.set_level(logging.INFO, logger="apps.api.watchdog")
    await _get("/slow/abc")
    lines = _lines(caplog)
    assert any(
        "still running" in line and "GET /slow/{item_id}" in line for line in lines
    )


async def test_a_slow_request_logs_its_time_to_answer_when_it_answers(caplog):
    caplog.set_level(logging.INFO, logger="apps.api.watchdog")
    await _get("/slow/abc")
    assert any(
        "answered after" in line and "GET /slow/{item_id}" in line
        for line in _lines(caplog)
    )


async def test_a_fast_request_logs_nothing(caplog):
    caplog.set_level(logging.INFO, logger="apps.api.watchdog")
    response = await _get("/fast")
    assert response.status_code == 200
    assert _lines(caplog) == []


async def test_a_stream_that_answers_at_once_is_not_slow_however_long_it_runs(
    caplog,
):
    caplog.set_level(logging.INFO, logger="apps.api.watchdog")
    response = await _get("/stream")
    assert response.content == b"firstlast"
    assert _lines(caplog) == []


async def test_the_log_names_the_route_pattern_never_the_raw_path_or_query(caplog):
    caplog.set_level(logging.INFO, logger="apps.api.watchdog")
    await _get("/slow/secret-value?token=hunter2")
    text = " ".join(_lines(caplog))
    assert "/slow/{item_id}" in text
    assert "secret-value" not in text
    assert "hunter2" not in text


async def test_the_watchdog_leaves_the_response_unchanged():
    response = await _get("/slow/abc")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_the_api_app_runs_the_watchdog():
    from apps.api.main import app

    assert any(m.cls is SlowRequestWatchdog for m in app.user_middleware)
