"""Deleting a document's chunks (its cascade, an ingest retry) is an index
lookup on chunks.document_id, never a scan of every user's chunks."""

import uuid

from sqlalchemy import text


async def test_chunks_by_document_id_is_an_index_lookup(admin_engine):
    async with admin_engine.connect() as conn:
        # The test table is near-empty, where a scan is always cheapest; with
        # scans priced out, the plan shows whether an index can serve this.
        await conn.execute(text("SET enable_seqscan = off"))
        plan = await conn.execute(
            text("EXPLAIN DELETE FROM chunks WHERE document_id = :id"),
            {"id": uuid.uuid4()},
        )
        lines = "\n".join(row[0] for row in plan)
    assert "Seq Scan" not in lines, lines
    assert "chunks_document_id_idx" in lines, lines
