"""Logs requests that are slow to start answering.

A request that has sent no response after the threshold is logged while it is
still waiting, so a hang shows up in the logs before anything times out; when
it finally answers, its time to answer is logged too. The clock stops at the
response's first byte, not its last: chat replies stream for minutes by design
and are slow only if they are slow to start.

The log names the method and the route pattern (`/api/conversations/{id}`),
never the raw path, query, headers or body: those can carry ids, tokens or a
user's text.
"""

import asyncio
import logging
import os

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = float(os.getenv("SLOW_REQUEST_SECONDS", "2"))


def route_label(scope) -> str:
    """`<METHOD> <public route pattern>` for a matched request, e.g.
    `GET /api/conversations/{conversation_id}`; never the raw path."""
    # The router writes the matched route into the scope. An included
    # router's route carries its path relative to the include's prefix
    # (FastAPI keeps the full pattern only in a private scope key), so the
    # prefix is the request path's leading segments that the pattern's own
    # segments do not account for. No route here takes a multi-segment
    # {x:path} parameter, which would break the count.
    route = scope.get("route")
    pattern = getattr(route, "path", None)
    if pattern is None:
        return f"{scope['method']} (unmatched)"
    actual = scope["path"].rstrip("/").split("/")
    own = pattern.rstrip("/").split("/")
    prefix = "/".join(actual[: len(actual) - len(own) + 1])
    return f"{scope['method']} {prefix}{pattern}"


class SlowRequestWatchdog:
    def __init__(self, app: ASGIApp, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.app = app
        self.threshold = threshold

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        answered = False

        async def warn_while_waiting() -> None:
            await asyncio.sleep(self.threshold)
            logger.warning(
                "still running: %s after %.1fs",
                route_label(scope),
                loop.time() - started_at,
            )

        warning = asyncio.create_task(warn_while_waiting())

        async def send_and_time(message: Message) -> None:
            nonlocal answered
            if message["type"] == "http.response.start" and not answered:
                answered = True
                warning.cancel()
                elapsed = loop.time() - started_at
                if elapsed >= self.threshold:
                    logger.warning(
                        "slow: %s answered after %.1fs", route_label(scope), elapsed
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_and_time)
        finally:
            warning.cancel()
            elapsed = loop.time() - started_at
            if not answered and elapsed >= self.threshold:
                logger.warning(
                    "slow: %s ended without answering after %.1fs",
                    route_label(scope),
                    elapsed,
                )
