"""The system prompt for anonymous demo visitors (a user with no email).

A visitor gets no tools: no document search, no uploads. prompt.md carries the
guest instructions and the reference text about hax the demo answers from, and
asks for a sign-up line in the first answer only. Read once at import: the
file changes only with a new image, and a deploy restarts the process. The
text is the same for every visitor but shorter than the model's prompt-cache
minimum, so it is not cached; accepted.
"""

from pathlib import Path

DEMO_SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
