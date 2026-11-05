"""A scripted stand-in for the anthropic client's `messages.stream`, for the
harness tests. A turn is a dict: `text` (the streamed pieces), `content` (the
final message's blocks), `stop_reason`, and optionally `usage` (default
`usage()`)."""

from types import SimpleNamespace


class _Stream:
    def __init__(self, turn):
        self._turn = turn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    async def text_stream(self):
        for t in self._turn["text"]:
            yield t

    async def get_final_message(self):
        return SimpleNamespace(
            content=self._turn["content"],
            stop_reason=self._turn["stop_reason"],
            usage=self._turn.get("usage") or usage(),
        )


class FakeClient:
    """Each call to messages.stream consumes the next scripted turn and
    records the kwargs it was called with."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _Stream(self.turns.pop(0))


def usage(
    inp: int = 1,
    out: int = 1,
    cache_read: int | None = 0,
    cache_write: int | None = 0,
):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def tool_use(name, inp, id_="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=inp, id=id_)


def text_block(text):
    return SimpleNamespace(type="text", text=text)


async def collect(gen):
    return [e async for e in gen]
