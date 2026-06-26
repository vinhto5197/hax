from anthropic.types import MessageParam

from packages.core.rag.retrieval import RetrievedChunk, retrieve

# Stable system prompt (kept constant so it stays cache-friendly). Retrieved
# context is volatile and goes in the user turn, not here.
RAG_SYSTEM = (
    "You answer questions using the provided context from the user's uploaded "
    "documents. Prefer the context when it is relevant. If the answer is not in "
    "the context, say so plainly — you may then answer from general knowledge, "
    "but make the distinction clear. When you use the context, mention which "
    "document(s) it came from."
)


def _format_context(chunks: list[RetrievedChunk]) -> str:
    # Fence the chunks in <context> tags: the model is trained to treat tagged
    # blocks as reference material distinct from the instruction, which is what
    # lets us prepend this to the user turn (below) and have it read as "here's
    # context, then my question" rather than an abrupt splice. Each block is
    # labelled with its source filename so the model can cite it.
    blocks = [f"[from {c.filename}]\n{c.content}" for c in chunks]
    return "<context>\n" + "\n\n".join(blocks) + "\n</context>"


async def augment_messages(
    query: str, messages: list[MessageParam]
) -> tuple[str | None, list[MessageParam]]:
    """Retrieve context for `query` and inject it into the final user turn.

    Returns (system, messages). On no retrieval, returns (None, messages
    unchanged) so the caller streams plain history-only chat. The context is
    prepended to the last user message (the volatile tail) rather than the
    system prompt, keeping the stable prefix cache-friendly.
    """
    chunks = await retrieve(query)
    if not chunks:
        return None, messages

    last = messages[-1]
    # Invariant from load_history + persist_user_turn: the final turn is the
    # just-persisted user message with string content. Assert it so a future
    # contract break (e.g. RAG wired into a tool-use/block-content path) fails
    # loudly instead of producing a malformed prompt.
    assert last["role"] == "user" and isinstance(last["content"], str), (
        "augment_messages expects the final turn to be a string-content user message"
    )
    augmented = dict(last)
    augmented["content"] = f"{_format_context(chunks)}\n\n{last['content']}"
    return RAG_SYSTEM, [*messages[:-1], augmented]
