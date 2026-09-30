"""The system prompt for anonymous demo visitors (a user with no email).

A visitor gets no tools: no document search, no uploads. prompt.md carries the
guest instructions and the reference text about hax the demo answers from, and
asks for a sign-up line at the end of every answer. Read once at import: the
file changes only with a new image, and a deploy restarts the process. The
text is identical for every visitor, so Anthropic's prompt cache hits.
"""

from pathlib import Path

DEMO_SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
