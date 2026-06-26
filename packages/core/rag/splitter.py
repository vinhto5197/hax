from langchain_text_splitters import RecursiveCharacterTextSplitter

# Chunk sizing is in characters (length_function=len). ~1600 chars ≈ 400 tokens,
# with ~12% overlap so a sentence straddling a boundary isn't orphaned. The
# recursive splitter tries paragraph -> line -> word -> character separators
# (LangChain's defaults: "\n\n", "\n", " ", "") so it cuts on structure rather
# than mid-word where it can. Tuning (size/overlap/k) is an M2 slice-2 concern.
CHUNK_SIZE = 1600
CHUNK_OVERLAP = 200

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
