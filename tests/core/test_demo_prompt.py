"""The guest system prompt loads and keeps its load-bearing instructions."""

from packages.core.demo.prompt import DEMO_SYSTEM_PROMPT


def test_prompt_has_the_reference_text_and_the_sign_up_ask():
    assert "# Reference documents" in DEMO_SYSTEM_PROMPT
    assert "End every answer" in DEMO_SYSTEM_PROMPT
    assert "sign up" in DEMO_SYSTEM_PROMPT
