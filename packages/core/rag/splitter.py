from langchain_text_splitters import RecursiveCharacterTextSplitter

from packages.core.rag.config import CHUNK_OVERLAP, CHUNK_SIZE

# Chunk sizing is in characters (length_function=len; CHUNK_SIZE/OVERLAP come from
# rag.config, env-tunable). ~1600 chars ≈ 400 tokens, ~12% overlap so a sentence
# straddling a boundary isn't orphaned. The recursive splitter tries paragraph ->
# line -> word -> character separators (LangChain's defaults: "\n\n", "\n", " ",
# "") so it cuts on structure rather than mid-word where it can.
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    length_function=len,
)


def split_text(text: str) -> list[str]:
    """Split a document into overlapping chunks; drops empty/whitespace pieces.

    A document shorter than CHUNK_SIZE comes back as a single chunk — the
    splitter only subdivides once content exceeds the size.
    """
    return [c for c in _splitter.split_text(text) if c.strip()]
