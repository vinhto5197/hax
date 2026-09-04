import inspect
import uuid

from packages.core.agent.tools import (
    SEARCH_DOCUMENTS,
    SearchDocumentsInput,
    ToolContext,
)


def test_user_id_is_not_a_model_parameter():
    # The prompt-injection fence (spec threat table): identity rides the
    # request context; the model's input schema must never expose it.
    schema = SearchDocumentsInput.model_json_schema()
    assert "user_id" not in schema.get("properties", {})


def test_search_documents_executor_takes_context():
    params = list(inspect.signature(SEARCH_DOCUMENTS.run).parameters)
    assert len(params) == 2  # (input, ctx)


def test_tool_context_is_immutable():
    ctx = ToolContext(user_id=uuid.uuid4())
    try:
        ctx.user_id = uuid.uuid4()
        raise AssertionError("ToolContext must be frozen")
    except AttributeError:
        pass
