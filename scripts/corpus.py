#!/usr/bin/env python
"""Ad-hoc DB inspection — view the ingested corpus (documents + their chunks).

Read-only. Uses the app's own DB layer (packages.db), so there are no raw-SQL
column gotchas (e.g. the chunk's `metadata` column vs the `chunk_metadata`
Python attribute) and it stays in sync with the models.

Usage (from anywhere; the venv must have the deps):
    python scripts/corpus.py                  # list all documents + chunk counts
    python scripts/corpus.py glimmerwick.md   # full content of one doc's chunks
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bootstrap() -> None:
    """Make the script runnable standalone: put the repo root on sys.path (so
    `import packages...` resolves no matter the cwd) and load the root .env (so
    DATABASE_URL is set without sourcing it first). Existing env wins."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip("\"'"))

    # Inspection needs the all-rows view: under RLS (slice 2) the app role with
    # no announced identity sees zero rows — correct for the app, useless here.
    if os.environ.get("MIGRATIONS_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["MIGRATIONS_DATABASE_URL"]


async def list_documents() -> None:
    from sqlalchemy import func, select

    from packages.db import AsyncSessionLocal
    from packages.db.models import Chunk, Document

    async with AsyncSessionLocal() as s:
        rows = list(
            await s.execute(
                select(
                    Document.filename,
                    Document.status,
                    func.count(Chunk.id),
                    func.coalesce(func.sum(func.length(Chunk.content)), 0),
                )
                .outerjoin(Chunk, Chunk.document_id == Document.id)
                .group_by(Document.id)
                .order_by(Document.created_at)
            )
        )
    if not rows:
        print("No documents ingested yet.")
        return
    print(f"{'FILENAME':<28} {'STATUS':<10} {'CHUNKS':>6} {'CHARS':>8}")
    for fn, status, n, chars in rows:
        print(f"{fn:<28} {status:<10} {n:>6} {chars:>8}")
    print(
        "\nPass a filename to dump its chunk content, e.g. "
        "`python scripts/corpus.py glimmerwick.md`."
    )


async def get_corpus(filename: str) -> None:
    from sqlalchemy import func, select

    from packages.db import AsyncSessionLocal
    from packages.db.models import Chunk, Document

    async with AsyncSessionLocal() as s:
        rows = list(
            await s.execute(
                select(Chunk.idx, func.length(Chunk.content), Chunk.content)
                .join(Document, Document.id == Chunk.document_id)
                .where(Document.filename == filename)
                .order_by(Chunk.idx)
            )
        )
    if not rows:
        print(f"No chunks for {filename!r}. Run with no args to list documents.")
        return
    for idx, chars, content in rows:
        print(f"\n=== {filename}  [chunk {idx}, {chars} chars] ===")
        print(content)


def main() -> None:
    _bootstrap()
    # asyncio.run is the sync->async entry point: it spawns a fresh event loop,
    # drives the coroutine to completion on THIS thread, then closes the loop —
    # right for a short-lived command that runs one thing and exits. (Contrast a
    # long-lived server like uvicorn, which creates ONE loop and runs it forever,
    # serving request after request; here the loop lives only for this command.)
    # Can't use a bare `await` here — main() is sync, so no loop exists yet.
    if len(sys.argv) > 1:
        asyncio.run(get_corpus(sys.argv[1]))
    else:
        asyncio.run(list_documents())


if __name__ == "__main__":
    main()


# Usage:
#   python scripts/corpus.py                  # list all documents + chunk counts
#   python scripts/corpus.py glimmerwick.md   # dump one document's chunk content
