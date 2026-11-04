import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
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


# On the real app (apps.api.main:app). SLOW_REQUEST_SECONDS is read when the
# app is imported, so these scenarios run in one child interpreter that sets it
# first, drives the app over ASGI and prints the watchdog's records per
# scenario as JSON. Slowness is staged by overriding `current_user` with a
# dependency that sleeps, then refuses, so no database is reached.

ROOT = Path(__file__).resolve().parents[2]

APP_THRESHOLD = 0.3
SLEEP = 1.0
CONVERSATION_ID = "1b2c3d4e-0000-4000-8000-00000000abcd"
QUERY_SECRET = "QSECRETvalue123"
HEADER_SECRET = "HSECRETvalue456"
BODY_SECRET = "BSECRETvalue789"

_DRIVER = r"""
import asyncio, json, logging, sys, time

import httpx
from fastapi import HTTPException

from apps.api.main import app
from apps.api.auth import current_user

SLEEP, CID, QS, HS, BS = json.loads(sys.argv[1])

records = []


class Capture(logging.Handler):
    def emit(self, record):
        if record.name == "apps.api.watchdog":
            records.append(
                {"msg": record.getMessage(), "args": repr(record.args),
                 "created": record.created,
                 "extra": repr({k: v for k, v in record.__dict__.items()
                                if k not in logging.LogRecord(
                                    "", 0, "", 0, "", None, None).__dict__})}
            )


root = logging.getLogger()
root.addHandler(Capture(level=logging.DEBUG))
root.setLevel(logging.DEBUG)


async def slow_user():
    await asyncio.sleep(SLEEP)
    raise HTTPException(status_code=403, detail="no")


async def scenario(method, path, **kw):
    records.clear()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        started = time.time()
        resp = await c.request(method, path, **kw)
        answered = time.time()
    await asyncio.sleep(0.05)
    return {"status": resp.status_code, "started": started,
            "answered": answered, "records": list(records)}


async def main():
    out = {}
    app.dependency_overrides[current_user] = slow_user
    out["slow_get"] = await scenario(
        "GET", f"/api/conversations/{CID}?token={QS}",
        headers={"X-Probe": HS, "Authorization": f"Bearer {HS}"})
    out["slow_put"] = await scenario(
        "PUT", f"/api/me/profile?token={QS}",
        headers={"X-Probe": HS}, json={"about": BS})
    app.dependency_overrides.clear()
    print("RESULT " + json.dumps(out))


asyncio.run(main())
"""


@pytest.fixture(scope="module")
def app_runs():
    env = {**os.environ, "SLOW_REQUEST_SECONDS": str(APP_THRESHOLD)}
    args = json.dumps(
        [SLEEP, CONVERSATION_ID, QUERY_SECRET, HEADER_SECRET, BODY_SECRET]
    )
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER, args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert proc.returncode == 0 and lines, proc.stdout + proc.stderr
    return json.loads(lines[-1][len("RESULT ") :])


def _text(records) -> str:
    return "\n".join(r["msg"] + " " + r["args"] + " " + r["extra"] for r in records)


def test_on_the_app_a_waiting_request_logs_one_still_running_record_at_the_threshold(
    app_runs,
):
    run = app_runs["slow_get"]
    assert run["status"] == 403
    waiting = [r for r in run["records"] if r["created"] < run["answered"] - 0.1]
    assert len(waiting) == 1, run["records"]
    assert "still running" in waiting[0]["msg"]
    assert waiting[0]["created"] - run["started"] < SLEEP - 0.2


def test_on_the_app_a_slow_request_logs_a_second_record_with_its_time_to_answer(
    app_runs,
):
    run = app_runs["slow_get"]
    records = run["records"]
    assert len(records) == 2, records
    answer = records[1]
    assert answer["created"] >= run["answered"] - 0.1
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer["msg"])]
    assert any(
        SLEEP * 0.8 <= n <= SLEEP * 5 or SLEEP * 800 <= n <= SLEEP * 5000
        for n in numbers
    ), answer["msg"]


def test_the_log_names_the_method_and_the_full_public_route_pattern_with_the_api_prefix(
    app_runs,
):
    get_text = _text(app_runs["slow_get"]["records"])
    assert "GET /api/conversations/{conversation_id}" in get_text, get_text
    put_text = _text(app_runs["slow_put"]["records"])
    assert "PUT /api/me/profile" in put_text, put_text


def test_the_log_never_carries_the_raw_paths_ids_query_headers_or_body(app_runs):
    everything = _text(
        app_runs["slow_get"]["records"] + app_runs["slow_put"]["records"]
    )
    assert everything, "no records to check"
    assert CONVERSATION_ID not in everything
    assert QUERY_SECRET not in everything
    assert "token=" not in everything
    assert HEADER_SECRET not in everything
    assert BODY_SECRET not in everything
