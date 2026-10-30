"""The guest system prompt loads and keeps its load-bearing instructions."""

import re

from packages.core.demo.prompt import DEMO_SYSTEM_PROMPT


def test_prompt_has_the_reference_text_and_the_sign_up_ask():
    assert "# Reference documents" in DEMO_SYSTEM_PROMPT
    assert "In your first answer only" in DEMO_SYSTEM_PROMPT
    assert "sign up" in DEMO_SYSTEM_PROMPT


def test_prompt_leads_capability_answers_with_what_needs_an_account():
    assert "start with what needs an account" in " ".join(DEMO_SYSTEM_PROMPT.split())


def test_both_system_prompts_name_the_product_hax_capitalized():
    from apps.api.routers.chat import AGENTIC_SYSTEM

    for prompt in (DEMO_SYSTEM_PROMPT, AGENTIC_SYSTEM):
        assert re.search(r"\bhax\b", prompt) is None
        assert "Hax" in prompt
