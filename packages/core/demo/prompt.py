"""The system prompt for anonymous demo visitors (a user with no email).

A visitor gets no tools: no document search, no uploads. prompt.md carries the
guest instructions and the reference text about hax the demo answers from, and
asks for a sign-up line in the first answer only. Read once at import: the
file changes only with a new image, and a deploy restarts the process. On its
own it is under the default model's prompt-cache minimum, so a visitor's
first turn is never a cache hit; later turns cache the prefix as any chat
does.
"""

from pathlib import Path

DEMO_SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
