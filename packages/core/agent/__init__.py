"""Agentic tools + the hand-rolled tool-use harness (M2 slice 3).

`tools.py` is the tool registry (Pydantic input schemas + async executors);
`harness.py` (step 2) drives the Anthropic tool-use loop over it. Native
Anthropic tool use — not MCP. Consumers import from the submodules directly
(e.g. `from packages.core.agent.tools import TOOLS`), matching rag/llm.
"""
