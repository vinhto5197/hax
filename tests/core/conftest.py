import uuid

import fakeredis.aioredis
import pytest

from packages.core.agent.tools import ToolContext


@pytest.fixture
def ctx():
    return ToolContext(user_id=uuid.uuid4())


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()
