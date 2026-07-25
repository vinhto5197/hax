"""Agentic tool registry: name -> Tool.

harness.py uses it both ways: advertise `tools=[…]` to the Anthropic API
(to_anthropic) and dispatch incoming tool_use blocks to executors by name.
"""

import ast
import logging
import operator
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from packages.core.rag.retrieval import retrieve

logger = logging.getLogger(__name__)

# Recipient for the MOCKED send_email tool (v0 stub — logged, not really sent).
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "you@example.com")


@dataclass(frozen=True)
class Tool:
    """One agent tool.

    - `description`: what the MODEL reads to decide when to call it.
    - `label`: status line shown to the USER while it runs.
    - `input_model`: Pydantic model for the arguments — its JSON Schema becomes
      the Anthropic `input_schema`, and it validates incoming tool_use input.
    - `run`: async executor (validated input in, `tool_result` string out).
    """

    name: str
    description: str
    label: str
    input_model: type[BaseModel]
    run: Callable[[Any], Awaitable[str]]

    def to_anthropic(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


# ── search_documents (the RAG anchor) ────────────────────────────────────────
class SearchDocumentsInput(BaseModel):
    query: str = Field(
        description="Natural-language query to find relevant passages in the "
        "user's uploaded documents via semantic (vector) search."
    )


async def _run_search_documents(inp: SearchDocumentsInput) -> str:
    chunks = await retrieve(inp.query)
    if not chunks:
        return "No relevant passages were found in the uploaded documents."
    # Returned as a structured tool_result block — no text fence for document
    # content to break out of (prompt-injection surface).
    return "\n\n".join(
        f"[{i}] from {c.filename}:\n{c.content}" for i, c in enumerate(chunks, 1)
    )


SEARCH_DOCUMENTS = Tool(
    name="search_documents",
    label="Searching documents…",
    description=(
        "Search the user's uploaded documents for passages relevant to a query, "
        "using semantic (vector) search. Use this whenever the answer might be in "
        "the user's own documents; you may call it more than once to refine."
    ),
    input_model=SearchDocumentsInput,
    run=_run_search_documents,
)


# ── calculator (AST-safe arithmetic — never eval()) ──────────────────────────
class CalculatorInput(BaseModel):
    expression: str = Field(
        description="An arithmetic expression to evaluate, e.g. '19381 * 22.5 + 7'."
    )


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_POW_EXP = 1000  # cap the exponent so `2**10**9` can't wedge the process


def _eval_expr(node: ast.AST) -> float:
    # Allowlist walk: only arithmetic nodes are interpreted; anything else
    # (names, calls, attributes, …) hits the raise. Never eval().
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_expr(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_expr(node.left), _eval_expr(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW_EXP:
            raise ValueError(f"exponent too large (> {_MAX_POW_EXP})")
        return _BIN_OPS[type(node.op)](left, right)
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


async def _run_calculator(inp: CalculatorInput) -> str:
    try:
        result = _eval_expr(ast.parse(inp.expression, mode="eval").body)
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as exc:
        raise ValueError(f"could not evaluate {inp.expression!r}: {exc}") from exc
    return str(result)


CALCULATOR = Tool(
    name="calculator",
    label="Calculating…",
    description=(
        "Evaluate a single arithmetic expression (+ - * / // % ** and parentheses) "
        "and return the result. Use this for any exact calculation rather than "
        "doing the arithmetic yourself."
    ),
    input_model=CalculatorInput,
    run=_run_calculator,
)


# ── get_current_datetime (zero-argument) ─────────────────────────────────────
class GetCurrentDatetimeInput(BaseModel):
    pass  # zero-argument tool


async def _run_get_current_datetime(inp: GetCurrentDatetimeInput) -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


GET_CURRENT_DATETIME = Tool(
    name="get_current_datetime",
    label="Checking the time…",
    description=(
        "Return the current local date and time (ISO 8601). Use this whenever the "
        "answer depends on the current date or time."
    ),
    input_model=GetCurrentDatetimeInput,
    run=_run_get_current_datetime,
)


# ── send_email (MOCKED — v0 stub, no real Gmail) ─────────────────────────────
class SendEmailInput(BaseModel):
    subject: str = Field(description="The email subject line.")
    body: str = Field(description="The email body text.")


async def _run_send_email(inp: SendEmailInput) -> str:
    # v0 stub: logs the would-be send, sends nothing (real Gmail is v1). The
    # hardcoded recipient bounds prompt-injection blast radius.
    logger.info(
        "send_email (MOCKED) → to=%s | subject=%r | body=%r",
        EMAIL_RECIPIENT,
        inp.subject,
        inp.body,
    )
    return f"Email sent to {EMAIL_RECIPIENT} (subject: {inp.subject!r})."


SEND_EMAIL = Tool(
    name="send_email",
    label="Sending email…",
    description=(
        "Send an email to the user with a subject and body. Use this when the user "
        "asks to be emailed something (e.g. a summary)."
    ),
    input_model=SendEmailInput,
    run=_run_send_email,
)


TOOLS: dict[str, Tool] = {
    t.name: t for t in (SEARCH_DOCUMENTS, CALCULATOR, GET_CURRENT_DATETIME, SEND_EMAIL)
}
