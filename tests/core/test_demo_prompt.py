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


# The sign-up rules (the maintainer, 2026-11-03): an account-only ask is answered with
# "that takes signing up" in whichever answer it comes; otherwise the
# invitation goes in the first answer only. Checked by text over the guest
# instructions, sentence by sentence, so a rewording keeps passing as long as
# both rules are there and nothing contradicts them.

_SCOPE_ANY_ANSWER = re.compile(
    r"\b(any answer|every answer|whichever answer|each answer|in that answer"
    r"|even (?:in )?(?:a )?later|later answers? too|also in later"
    r"|not (?:just|only) (?:in )?the first)\b"
)
_CARVE_OUT = re.compile(r"\b(unless|except|otherwise|other than|apart from|outside)\b")
_FORBIDS_LATER = re.compile(
    r"\b(do not|don't|never|must not)\b.*\b(repeat|again|later answers?)\b"
    r"|\b(repeat|again|later answers?)\b.*\b(do not|don't|never|must not)\b"
)


def _instruction_sentences() -> list[str]:
    instructions = DEMO_SYSTEM_PROMPT.split("# Reference documents")[0]
    flat = " ".join(instructions.split()).lower()
    return [s for s in re.split(r"(?<=[.!?])\s+", flat) if s]


def test_prompt_says_an_account_only_ask_takes_signing_up_in_whichever_answer():
    sentences = _instruction_sentences()
    windows = [" ".join(sentences[i : i + 2]) for i in range(len(sentences))]
    assert any(
        "sign" in w
        and "document" in w
        and "upload" in w
        and "tool" in w
        and _SCOPE_ANY_ANSWER.search(w)
        for w in windows
    ), sentences


def test_prompt_invites_sign_up_in_the_first_answer_only_and_never_again():
    sentences = _instruction_sentences()
    assert any(
        "first answer" in s and ("invit" in s or "sign up" in s) for s in sentences
    ), sentences
    assert any(_FORBIDS_LATER.search(s) for s in sentences), sentences


def test_prompt_carves_account_only_asks_out_of_no_repeat_in_the_same_sentence():
    forbidding = [s for s in _instruction_sentences() if _FORBIDS_LATER.search(s)]
    for sentence in forbidding:
        assert _CARVE_OUT.search(sentence), sentence


def test_prompt_adds_no_account_pitch_to_general_answers_beyond_the_first():
    for sentence in _instruction_sentences():
        if "general knowledge" in sentence and "account" in sentence:
            assert "first answer" in sentence, sentence


_INVITATION = re.compile(r"invit|closing sentence|end with")
_SKIPS = re.compile(
    r"\b(do not|don't|never|skip|omit|leave out|instead of|rather than)\b"
)
_OPENED_WITH_SIGN_UP = re.compile(
    r"\b(open(?:s|ed)?|start(?:s|ed)?|began|begins?|leads?|led)\b"
    r"|already (?:said|says|told|tells|stated|states|mentioned|mentions)"
)
_COVERS_THE_FIRST_ANSWER = re.compile(
    r"first answer|any answer|every answer|whichever answer|each answer"
)


def test_an_answer_that_opened_with_sign_up_does_not_also_end_with_the_invitation():
    sentences = _instruction_sentences()
    windows = [" ".join(sentences[i : i + 2]) for i in range(len(sentences))]
    assert any(
        _INVITATION.search(w)
        and _SKIPS.search(w)
        and _OPENED_WITH_SIGN_UP.search(w)
        and _COVERS_THE_FIRST_ANSWER.search(w)
        and "sign" in w
        for w in windows
    ), sentences
