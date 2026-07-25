import os

from langchain_text_splitters import RecursiveCharacterTextSplitter

# Sizes are in characters (~1600 ≈ 400 tokens), ~12% overlap so a sentence
# straddling a boundary isn't orphaned. Changing them requires re-ingest. The
# recursive splitter cuts on structure (paragraph -> line -> word -> char).
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1600"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "200"))

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
