"""RAG: chunking, embeddings (Voyage), and retrieval.

LangChain is used here for text splitting only; embeddings call the Voyage SDK
directly and retrieval is our own pgvector SQL (ADR 0009). Retrieval is consumed
by the agent's search_documents tool (packages/core/agent/tools.py) — the model
invokes it; nothing is injected into prompts up front.
"""
