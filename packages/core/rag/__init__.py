"""RAG: chunking, embeddings (Voyage), retrieval, and prompt augmentation.

LangChain is used here for text splitting only; embeddings call the Voyage SDK
directly and retrieval is our own pgvector SQL (ADR 0009).
"""
