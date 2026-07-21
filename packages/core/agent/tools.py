"""Agentic tool registry: name -> Tool(input schema, description, executor).

The hand-rolled tool-use harness (harness.py, slice-3 step 2) uses this registry
to (a) advertise `tools=[…schemas…]` on the Anthropic Messages API and (b)
dispatch an incoming `tool_use` block to its executor by name.

These are plain in-process Python functions surfaced via *native Anthropic tool
use* — NOT MCP: there is no separate tool server and no protocol. MCP would be
the way to expose these tools for reuse across other apps; a self-contained v0
doesn't need it.
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

    - `description`: what the MODEL reads to decide when to call this tool.
    - `label`: short present-tense status shown to the USER while it runs (e.g.
      "Searching documents…"). Colocated here — not a parallel map in the harness
      — so a new tool must supply its own; it's a required field of adding a tool.
    - `input_model`: a Pydantic model for the tool's arguments; its JSON Schema
      becomes the Anthropic `input_schema` (and validates the model's tool_use
      input before we run it).
    - `run`: async executor taking the validated input model, returning a string
      that is fed back to the model as the `tool_result` content.
    """

    name: str
    description: str
    label: str
    input_model: type[BaseModel]
    run: Callable[[Any], Awaitable[str]]

    def to_anthropic(self) -> dict:
        # Anthropic tool definition: name + description + JSON-Schema input_schema.
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
    # Numbered, filename-labelled hits. This is returned as a structured
    # tool_result block (not spliced into a text fence), so there's no delimiter
    # for document content to break out of; residual indirect-injection risk is
    # bounded by the mocked, hardcoded-recipient send_email (slice-3 design).
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
    # Walk ONLY arithmetic AST nodes. Anything else (names, calls, attributes,
    # subscripts, …) falls through to the raise, so this can never execute
    # arbitrary code the way eval() would.
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
    pass  # no arguments — the model calls it with {}


async def _run_get_current_datetime(inp: GetCurrentDatetimeInput) -> str:
    # Local time + timezone offset, ISO 8601. Fills the "the model doesn't know
    # *now*" gap.
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
    # v0 stub: log the would-be send and return success — exercises the full
    # action-tool flow (model decides → we "execute" → return a result) with no
    # Google deps / OAuth; the real Gmail send is v1. The hardcoded EMAIL_RECIPIENT
    # bounds prompt-injection blast radius: a tricked model can only "email" the
    # fixed address, and nothing is actually sent.
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


# The registry the harness drives: advertise via `.values()`, dispatch via
# `TOOLS[name]`.
TOOLS: dict[str, Tool] = {
    t.name: t for t in (SEARCH_DOCUMENTS, CALCULATOR, GET_CURRENT_DATETIME, SEND_EMAIL)
}
